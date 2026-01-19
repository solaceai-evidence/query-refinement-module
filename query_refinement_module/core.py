"""
Interactive query refinement module - Domain-agnostic, schema-based architecture.

This module helps users improve their queries through iterative refinement,
working with ANY user-defined schema across ANY research domain.

Pipeline Flow:
=====
1. User provides initial query + schema (e.g., PICO, Solace-ai, etc)
2. Manager.initialize() uses query_analyzer to detect missing refinement aspects and generate questions using refinement aspects' analysis_prompt
3. For each needed refinement aspect:
   a. Present question to user
   b. Receive and store user's response
   c. Check if follow-ups are needed; if so, repeat
4. Synthesize all refinements into improved query (natural language, structured, etc.)
5. Return refined query for processing

User Control Commands:
=====================
Users can use these commands to control the refinement flow:

Navigation:
- /back or /prev          - Go back to previous step
- /goto <step_number>     - Jump to specific step (e.g., /goto 2)
- /restart               - Start refinement from beginning

Control:
- /skip                  - Skip current refinement aspect entirely
- /done                  - Mark current step as complete (stop follow-ups)
- /submit or /end        - Finish session immediately using current answers

Information:
- /status                - Show session progress
- /help                  - Show available commands
- /steps                 - List all refinement steps

These commands are detected via is_user_command() and processed via parse_user_command().

Logging and Tracing:
===================
This module includes comprehensive logging and tracing support:
- All major operations log entry, exit, and key events
- Request IDs propagate through the call stack for distributed tracing
- LLM interactions capture tokens, duration, and costs
- Performance metrics are logged for optimization
- Errors include full context for debugging
"""

import asyncio
import json
import logging
import textwrap
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Union

from .interfaces import (
    LLMProviderInterface,
    TracingProviderInterface,
    QueryAnalyzerInterface,
)
from .providers import NoOpTracingProvider, TraceEventEmitter
from .schema import RefinementAspect

from .prompt.system_role import (
    SYSTEM_PROMPT_REFINEMENT_END_LOWER,
    SYSTEM_PROMPT_REFINEMENT_END_UPPER,
)

# Module logger - use get_logger() in functions for request context
logger = logging.getLogger(__name__)

# =======
# User Control Commands
# =======

class UserCommand(Enum):
    """Commands users can issue to control refinement flow."""
    # Navigation
    BACK = "back"
    PREVIOUS = "prev"
    GOTO = "goto"
    RESTART = "restart"
    
    # Control
    SKIP = "skip"
    DONE = "done"
    SUBMIT = "submit"
    
    # Information
    STATUS = "status"
    HELP = "help"
    STEPS = "steps"
    
    # Not a command
    NONE = "none"


COMMAND_ALIASES: Dict[str, UserCommand] = {
    "back": UserCommand.BACK,
    "prev": UserCommand.PREVIOUS,
    "previous": UserCommand.PREVIOUS,
    "goto": UserCommand.GOTO,
    "restart": UserCommand.RESTART,
    "skip": UserCommand.SKIP,
    "done": UserCommand.DONE,
    "status": UserCommand.STATUS,
    "help": UserCommand.HELP,
    "steps": UserCommand.STEPS,
    "submit": UserCommand.SUBMIT,
    "end": UserCommand.SUBMIT,
}


COMMANDS_REQUIRING_ARGUMENT = {UserCommand.GOTO}


@dataclass
class CommandResult:
    """Result of parsing and validating a user command."""
    command: UserCommand
    argument: Optional[str] = None
    is_valid: bool = True
    error_message: Optional[str] = None


def is_user_command(user_input: str) -> bool:
    """
    Check if user input is a control command (starts with /).
    
    Args:
        user_input: The user's input string
        
    Returns:
        True if input is a command, False otherwise
    """
    if not user_input:
        return False
    return user_input.strip().startswith("/")


def parse_user_command(user_input: str) -> CommandResult:
    """
    Parse user input into a command.
    
    Args:
        user_input: The user's input string
        
    Returns:
        CommandResult with parsed command and validation status
        
    Examples:
        >>> parse_user_command("/back")
        CommandResult(command=UserCommand.BACK, ...)
        
        >>> parse_user_command("/goto 3")
        CommandResult(command=UserCommand.GOTO, argument="3", ...)
    """
    if not is_user_command(user_input):
        return CommandResult(command=UserCommand.NONE, is_valid=False)
    
    # Remove leading slash and split
    remainder = user_input.strip()[1:].strip()
    if not remainder:
        return CommandResult(
            command=UserCommand.NONE,
            is_valid=False,
            error_message="Empty command. Type /help for available commands."
        )

    parts = remainder.split(maxsplit=1)
    cmd_str = parts[0].lower()
    argument = parts[1].strip() if len(parts) > 1 else None

    command = COMMAND_ALIASES.get(cmd_str)
    if not command:
        return CommandResult(
            command=UserCommand.NONE,
            is_valid=False,
            error_message=f"Unknown command: /{cmd_str}. Type /help for available commands."
        )

    if command in COMMANDS_REQUIRING_ARGUMENT:
        if not argument:
            return CommandResult(
                command=command,
                is_valid=False,
                error_message=f"/{command.value} requires a step number. Example: /{command.value} 2"
            )
        if command is UserCommand.GOTO and not argument.isdigit():
            return CommandResult(
                command=command,
                argument=argument,
                is_valid=False,
                error_message=f"Step number must be an integer, got: {argument}"
            )
    
    return CommandResult(command=command, argument=argument, is_valid=True)


def get_help_text() -> str:
    """
    Get help text explaining all available commands.
    
    Returns:
        Formatted help text string
    """
    return """
Available Commands:
==================

NAVIGATION:
  /back, /prev          Go back to previous step
  /goto <number>        Jump to specific step (e.g., /goto 2)
  /restart              Start refinement from beginning

CONTROL:
  /skip                 Skip current refinement aspect entirely
  /done                 Mark current step complete (stop follow-ups)
  /submit, /end         Finish session immediately using current answers

INFORMATION:
  /status               Show session progress
  /steps                List all refinement steps
  /help                 Show this help message

Examples:
  /goto 1               - Jump to first step
  /skip                 - Skip current question
  /done                 - Accept current answer, no more follow-ups
  /back                 - Go to previous step
"""


# =======
# Data Classes
# =======

@dataclass
class QueryAspectRefiner:
    """
    Represents the complete refinement process for a single aspect.
    
    Tracks the multi-turn conversation (initial question + follow-ups) until
    a final refined value for the aspect is obtained and accepted.
    """

    refinement_aspect: RefinementAspect
    
    # Multi-turn conversation history (initial + all follow-ups)
    # Each entry: {'question': '...', 'response': '...'}
    follow_up_history: List[Dict[str, str]] = field(default_factory=list)
    
    # Completion status - set when refinement is accepted/skipped or not needed as info is clear
    is_complete: bool = False
    
    # Review status - set when dependencies change, preserves history for review
    needs_review: bool = False

    # Whether the step was explicitly skipped by the user without supplying a value
    was_skipped: bool = False
    
    # Analysis result - stored from LLM's structured analysis output during initialize()
    # Contains: needs_refinement_rationale (why refinement needed/not), refinement_question (what to ask)
    needs_refinement_rationale: Optional[str] = None
    refinement_question: Optional[str] = None
    
    # Stores the extracted value from the dynamic field (labelled as aspect.id) in its native type
    refined_value: Optional[Union[str, Dict, List, bool, int, float]] = None
    
    @property
    def follow_up_count(self) -> int:
        """Number of follow-up rounds completed."""
        return len(self.follow_up_history)
    
    @property
    def refined_value_as_str(self) -> Optional[str]:
        """
        Get string representation of refined value for display/storage.
        
        Returns:
            String representation of refined_value (JSON for complex types)
        """
        if self.refined_value is not None:
            if isinstance(self.refined_value, (dict, list)):
                return json.dumps(self.refined_value, ensure_ascii=False)
            return str(self.refined_value)
        return None
    
    def extract_and_store_value(self, response: str) -> None:
        """
        Extract value from dynamic field in response and store in refined_value.
        
        Single extraction point - eliminates duplicate logic across codebase.
        Parses JSON response, extracts aspect.id field, stores with native type.
        If not JSON, stores the plain text response directly.
        
        Args:
            response: JSON response string from LLM, or plain text
        """
        if not response or not isinstance(response, str):
            return
            
        # Try to parse as JSON
        if response.strip().startswith("{"):
            try:
                parsed = json.loads(response)
                if isinstance(parsed, dict):
                    field_name = self.refinement_aspect.id
                    if field_name in parsed:
                        value = parsed[field_name]
                        # Store non-empty values (handle empty strings, lists, dicts)
                        if value or isinstance(value, (bool, int, float)):
                            self.refined_value = value
                            return
            except (json.JSONDecodeError, TypeError):
                pass  # Not valid JSON, fall to plain text handling
        
        # For non-JSON responses, store the plain text directly
        # This preserves the behavior where any response contributes to the value
        if response.strip():
            self.refined_value = response.strip()

    def get_system_role(self) -> str:
        """
        Get the system role prompt for this refinement aspect.
        
        Returns:
            System prompt string (from refinement aspect or default)
        """
        return self.refinement_aspect.get_system_role()
    
    def get_prompts(self, query: str, dependency_context: Optional[Dict[str, Dict[str, str]]] = None, **kwargs) -> tuple[str, str]:
        """
        Get both system and user prompts for this refinement aspect with dependency context.
        
        Args:
            query: The query to analyze
            dependency_context: Mapping of dependency IDs to dictionaries containing
                human-readable names, descriptions, and values used for prompt context
            **kwargs: Additional context for prompt formatting
            
        Returns:
            Tuple of (system_prompt, analysis_prompt)
        """
        system_prompt = self.refinement_aspect.get_system_role()

        context_lines: List[str] = []
        missing_deps: List[str] = []

        if dependency_context and self.refinement_aspect.depends_on:
            for dep_id in self.refinement_aspect.depends_on:
                entry = dependency_context.get(dep_id)
                if entry and entry.get("value"):
                    dep_name = entry.get("name") or dep_id.replace("_", " ").title()
                    dep_desc = entry.get("description", "")
                    dep_value = entry["value"]
                    
                    # Format: **Name** (Description): Value
                    if dep_desc:
                        context_lines.append(f"- **{dep_name}** ({dep_desc}): {dep_value}")
                    else:
                        context_lines.append(f"- **{dep_name}**: {dep_value}")
                else:
                    missing_deps.append(dep_id)

            if missing_deps:
                logger.warning(
                    "refinement aspect '%s' depends on %s but they have no values. Continuing without that context.",
                    self.refinement_aspect.id,
                    missing_deps,
                )

        refinement_instructions_prompt_sections = [
            self.refinement_aspect.get_refinement_instructions_prompt(statement=query, **kwargs)
        ]

        if context_lines:
            refinement_instructions_prompt_sections.extend(
                [
                    "",
                    "### Previous refinements (authoritative context)\n"
                    "Use the following confirmed refinements as fixed constraints when evaluating the user-submitted input, "
                    "according to the definition of this refinement aspect:",
                    *context_lines,
                ]
            )
        
        # Include conversation history for multi-turn refinement
        if self.follow_up_history:
            conversation_lines = [
                "",
                "### Conversation history for this aspect\n"
                "The following is the conversation history so far for this specific refinement aspect. "
                "Use it as context when determining if further follow-up is needed:",
                ""
            ]
            
            for idx, exchange in enumerate(self.follow_up_history, 1):
                question = exchange.get('question', '')
                response = exchange.get('response', '')
                conversation_lines.append(f"**Turn {idx}:**")
                conversation_lines.append(f"Question: {question}")
                conversation_lines.append(f"Answer: {response}")
                conversation_lines.append("")
            
            refinement_instructions_prompt_sections.extend(conversation_lines)

        return system_prompt, "\n".join(refinement_instructions_prompt_sections)
    
    def can_ask_followup(self) -> bool:
        """
        Determines if a follow-up question can be asked based on the refinement aspect's max_follow_ups.
        """
        return self.refinement_aspect.allow_follow_up and (self.follow_up_count < self.refinement_aspect.max_follow_ups)

    def add_follow_up(self, question: str, response: str) -> None:
        """
        Adds a follow-up question/response pair to the history.
        
        Automatically extracts and stores the refined value from the response.
        """
        self.was_skipped = False
        self.follow_up_history.append({
            "question": question,
            "response": response
        })
        # Extract and store value from response
        self.extract_and_store_value(response)
    
    def get_conversation_history_text(self) -> str:
        """
        Format follow-up history for use in prompts.
        """
        if not self.follow_up_history:
            return "no previous follow-up questions."
        
        history_lines = []
        for i, qa in enumerate(self.follow_up_history, start=0):
            history_lines.append(f"Follow-up {i+1}:") # i+1 to make it human-friendly
            history_lines.append(f" Q: {qa.get('question', '')}")
            history_lines.append(f" A: {qa.get('response', '')}")
        return "\n".join(history_lines)
    
    def format_follow_up_prompt_template(
        self,
        original_query: str,
        *,
        include_examples: bool = True,
    ) -> str:
        """Build a follow-up analysis prompt with explicit context history guidance.

        The follow-up flow reuses the refinement aspect's schema while adding
        instructions that clarify this is a subsequent turn. The conversation
        history for the aspect is appended so the LLM can avoid repetition and
        focus on unresolved details.

        Args:
            original_query: The initial user query for the session.
            include_examples: Whether to include the aspect's examples section.

        Returns:
            Formatted prompt string ready for an LLM follow-up call.
        """

        history_text = self.get_conversation_history_text()
        latest_answer = self.refined_value_as_str or ""
        
        # Get current refined value for display
        current_value = self.refined_value
        value_display = ""
        if current_value is not None:
            field_name = self.refinement_aspect.id
            if isinstance(current_value, (dict, list)):
                value_json = json.dumps(current_value, indent=2, ensure_ascii=False)
                value_display = f"\n\nCURRENT VALUE FOR '{field_name}':\n{value_json}"
            else:
                value_display = f"\n\nCURRENT VALUE FOR '{field_name}': {current_value}"

        follow_up_preamble = textwrap.dedent(
            f"""
            FOLLOW-UP CONTEXT:
            For aspect "{self.refinement_aspect.aspect_name}", review the conversation history below.
            Only ask for information that is still missing or unclear.{value_display}
            
            At each response, you MUST update the '{self.refinement_aspect.id}' field with the CUMULATIVE SYNTHESIZED value.
            This means each response should build upon previous answers, progressively refining the value.
            
            If complete, set ``needs_refinement`` to ``false`` and provide:
            1. A brief explanation of why no further follow-up is needed (explanation field)
            2. In the ``{self.refinement_aspect.id}`` field, provide the FINAL SYNTHESIZED value that:
               - Combines ALL user responses from the entire conversation history
               - Forms ONE coherent, complete statement (or structured object/array)
               - Removes conversational language ("I think", "maybe", "probably", "I guess", "kind of")
               - Removes filler words and unnecessary elaboration ("well", "you know", "obviously", "definitely")
               - Removes meta-commentary ("I want to study", "I'm interested in", "This research focuses on")
               - Includes all key factual details from ALL answers
               - Is written as a clear, declarative statement (not as an answer to a question)
               - Focuses on essential information only
            
            Example conversation:
              Q1: What age group?
              A1: Well, I'm thinking probably adults, you know, not kids
              Q2: Specific ages?
              A2: Maybe like 18 to 65 or so
              Q3: Any conditions?
              A3: Yeah definitely Type 2 diabetes, but not the gestational kind obviously
            
            GOOD {self.refinement_aspect.id}: "Adults aged 18-65 with Type 2 diabetes (excluding gestational diabetes)"
            (Synthesizes all 3 answers, removes conversational fluff, forms coherent statement)
            
            BAD {self.refinement_aspect.id}: "Yeah definitely Type 2 diabetes, but not the gestational kind obviously"
            (Only last answer - missing age information! Keeps conversational language!)
            
            BAD {self.refinement_aspect.id}: "The user wants to study adults probably 18-65 with Type 2 diabetes"
            (Keeps meta-commentary and uncertain language like "wants to study", "probably")
            """
        ).strip()

        history_section_lines = ["Conversation history for this aspect:", history_text]
        if latest_answer:
            history_section_lines.extend(
                [
                    "",
                    "Most recent user answer:",
                    latest_answer,
                ]
            )
        history_section = "\n".join(history_section_lines)

        base_prompt = self.refinement_aspect.get_refinement_instructions_prompt(
            statement=original_query
        )

        sections = [follow_up_preamble, history_section, base_prompt]
        return "\n\n".join(section for section in sections if section)
    
@dataclass
class QueryRefinementSession:
    """
    Represents an entire query refinement session.
    
    Tracks the original query and the multi-step refinement process through
    a list of QueryAspectRefiner objects, one per refinement aspect regardless of whether it needs refinement.
    """

    original_query: str
    steps: List[QueryAspectRefiner] = field(default_factory=list)
    synthesis_requested: bool = False
    
    @property
    def refinement_framework(self) -> List[RefinementAspect]:
        """Get the refinement framework from the steps."""
        return [step.refinement_aspect for step in self.steps]
    
    def add_step(
        self,
        refinement_aspect: RefinementAspect,
    ) -> QueryAspectRefiner:
        """
        Adds a new refinement step to the session for a refinement aspect.

        Args:
            refinement_aspect (RefinementAspect): The refinement aspect being refined.
        
        Returns:
            QueryAspectRefiner: The newly created query aspectrefiner.
        """
        step = QueryAspectRefiner(
            refinement_aspect=refinement_aspect,
            is_complete=False,
        )
        self.steps.append(step)
        return step
    
    def get_active_step(self) -> Optional[QueryAspectRefiner]:
        """Return the first step that still requires user attention."""

        for step in self.steps:
            if not step.is_complete or step.needs_review:
                return step

        return None
    
    def get_next_unrefined_aspect(self) -> Optional[QueryAspectRefiner]:
        """
        Get the next aspect that needs refinement in dependency order.
        
        Returns the first aspect where:
        - Not yet complete
        - All dependencies are complete
        
        This enables sequential on-demand refinement without upfront analysis.
        
        Returns:
            QueryAspectRefiner if there's a ready aspect, None if all done or blocked
        """
        for step in self.steps:
            # Skip completed or skipped steps
            if step.is_complete:
                continue
            
            # Check if all dependencies are satisfied
            dependencies = step.refinement_aspect.depends_on or []
            if not dependencies:
                # No dependencies, ready to refine
                return step
            
            # Check all dependencies are complete
            all_deps_complete = True
            for dep_id in dependencies:
                dep_step = next((s for s in self.steps if s.refinement_aspect.id == dep_id), None)
                if not dep_step or not dep_step.is_complete:
                    all_deps_complete = False
                    break
            
            if all_deps_complete:
                return step
        
        return None
    
    def get_dependency_context(self, target_refinement_aspect_id: str) -> Dict[str, Dict[str, str]]:
        """
        Build dependency context for a specific refinement aspect.
        
        Only includes dependencies declared by the target refinement aspect.
        Values come from either:
        - Refined values (for aspects that were refined through interaction)
        - Original query reference (for aspects that were already clear)
        
        Args:
            target_refinement_aspect_id: The refinement aspect ID that needs dependency context
            
        Returns:
            Dictionary mapping dependency IDs to metadata containing:
            - name: The aspect name
            - description: The aspect description
            - value: The actual value (formatted for complex types)
            - type: The value_field_type (string, object, array, etc.)
        """
        step_index = {step.refinement_aspect.id: step for step in self.steps}
        target_step = step_index.get(target_refinement_aspect_id)
        if not target_step:
            # This is expected during initialization before steps are populated
            logger.debug(
                "Dependency context requested for aspect '%s' before session populated",
                target_refinement_aspect_id,
            )
            return {}

        dependencies = target_step.refinement_aspect.depends_on or []
        if not dependencies:
            return {}

        context: Dict[str, Dict[str, str]] = {}
        for dep_id in dependencies:
            dep_step = step_index.get(dep_id)
            if not dep_step:
                logger.debug(
                    "Dependency '%s' not yet available for aspect '%s'",
                    dep_id,
                    target_refinement_aspect_id,
                )
                continue

            aspect = dep_step.refinement_aspect
            value_type = aspect.value_field_type
            
            # Get the refined value directly (single source of truth)
            raw_value = None
            
            if dep_step.refined_value is not None:
                raw_value = dep_step.refined_value
            elif dep_step.is_complete and not dep_step.was_skipped:
                # Aspect was clear in original query
                raw_value = f"[{aspect.aspect_name} is clear in original query: \"{self.original_query}\"]"
            elif dep_step.was_skipped:
                # Aspect was skipped
                raw_value = "[User declined to provide additional details for this aspect]"
            
            # Format value based on type
            formatted_value = raw_value
            if raw_value and value_type in ("object", "array"):
                # Pretty-print JSON for complex types
                if isinstance(raw_value, (dict, list)):
                    formatted_value = json.dumps(raw_value, indent=2, ensure_ascii=False)
                elif isinstance(raw_value, str) and raw_value.strip().startswith(('{', '[')):
                    try:
                        parsed = json.loads(raw_value)
                        formatted_value = json.dumps(parsed, indent=2, ensure_ascii=False)
                    except (json.JSONDecodeError, TypeError):
                        formatted_value = raw_value
            elif raw_value and not isinstance(raw_value, str):
                # Convert non-string simple types to string
                formatted_value = str(raw_value)
            
            if raw_value is not None:
                context[dep_id] = {
                    "name": aspect.aspect_name,
                    "description": aspect.aspect_description,
                    "value": formatted_value,
                    "type": value_type,
                }

        return context
    
    def is_complete(self) -> bool:
        """
        Checks if all refinement steps are complete.
        """
        return all(step.is_complete for step in self.steps)
    
    def get_step_summary(self) -> Dict[str, Any]:
        """
        Get a summary of all steps with their follow-up status.
        
        Returns:
            Dictionary with step statistics and status.
        """
        completed = needs_review = in_progress = 0
        total_followups = 0
        step_summaries = []

        for step in self.steps:
            total_followups += step.follow_up_count
            if step.is_complete and not step.needs_review:
                completed += 1
            elif step.needs_review:
                needs_review += 1
            else:
                in_progress += 1

            step_summaries.append(
                {
                    "refinement_aspect": step.refinement_aspect.aspect_name,
                    "is_complete": step.is_complete,
                    "needs_review": step.needs_review,
                    "follow_up_count": step.follow_up_count,
                    "has_refined_value": step.refined_value_as_str is not None,
                }
            )

        return {
            "total_steps": len(self.steps),
            "completed": completed,
            "needs_review": needs_review,
            "in_progress": in_progress,
            "total_follow_ups": total_followups,
            "steps": step_summaries,
        }
    
    def get_full_conversation(self) -> str:
        """
        Get the complete conversation as formatted text.
        
        Reconstructs the conversation from the step-by-step refinement history.
        
        Returns:
            Human-readable conversation history.
        """
        lines = ["CONVERSATION HISTORY", "="*80]
        lines.append(f"Original Query: {self.original_query}")
        lines.append("="*80)
        lines.append("")
        
        for step in self.steps:
            if not step.follow_up_history:
                continue
                
            lines.append(f"[{step.refinement_aspect.aspect_name}]")
            lines.append("")
            
            for i, qa in enumerate(step.follow_up_history, 1):
                interaction_type = "initial" if i == 1 else f"follow-up {i-1}"
                lines.append(f"  [{interaction_type}]")
                lines.append(f"  Q: {qa.get('question', '')}")
                if qa.get('response'):
                    lines.append(f"  A: {qa['response']}")
                lines.append("")  # Blank line
            
            if step.refined_value_as_str:
                lines.append(f"  ✓ Final value: {step.refined_value_as_str}")
                lines.append("")
        
        return "\n".join(lines)
    
    def handle_command(self, cmd_result: CommandResult) -> Dict[str, Any]:
        """
        Execute a user command and return the result.
        
        Args:
            cmd_result: Parsed command result from parse_user_command()
            
        Returns:
            Dict with 'success', 'message', and optional command-specific data
        """
        if not cmd_result.is_valid:
            return {
                "success": False,
                "message": cmd_result.error_message or "Invalid command",
            }
        
        command = cmd_result.command

        if command == UserCommand.GOTO:
            if cmd_result.argument is None:
                return {"success": False, "message": "/goto requires step number"}
            return self._go_to_step(int(cmd_result.argument))

        command_handlers: Dict[UserCommand, Callable[[], Dict[str, Any]]] = {
            UserCommand.BACK: self._go_back,
            UserCommand.PREVIOUS: self._go_back,
            UserCommand.RESTART: self._restart,
            UserCommand.SKIP: self._skip_current,
            UserCommand.DONE: self._finish_current,
            UserCommand.STATUS: self._get_status,
            UserCommand.STEPS: self._list_steps,
            UserCommand.SUBMIT: self._request_synthesis,
            UserCommand.HELP: lambda: {"success": True, "message": get_help_text()},
        }

        handler = command_handlers.get(command)
        if handler:
            return handler()

        return {"success": False, "message": f"Command {command.name} not implemented"}
    
    def _invalidate_dependents(self, changed_refinement_aspect_id: str) -> List[str]:
        """
        Soft-invalidate all refinement aspects that depend on the changed refinement aspect.
        
        Preserves conversation history but marks steps for review.
        
        Args:
            changed_refinement_aspect_id: The refinement aspect ID that was changed
            
        Returns:
            List of invalidated refinement aspect names
        """
        invalidated = []
        
        for step in self.steps:
            if changed_refinement_aspect_id in step.refinement_aspect.depends_on:
                # Soft invalidate: preserve history but mark for review
                step.is_complete = False
                step.needs_review = True  # Flag for review, DON'T clear history
                step.was_skipped = False
                invalidated.append(step.refinement_aspect.aspect_name)
                
                # Recursively invalidate dependents of this step
                sub_invalidated = self._invalidate_dependents(step.refinement_aspect.id)
                invalidated.extend(sub_invalidated)
        
        return invalidated
    
    def _go_back(self) -> Dict[str, Any]:
        """Navigate to the previous step and soft-invalidate dependent refinement aspects."""
        active = self.get_active_step()
        if not active:
            return {"success": False, "message": "No active step to go back from"}
        
        active_idx = self.steps.index(active)
        if active_idx == 0:
            return {"success": False, "message": "Already at first step"}
        
        # Clear current step's data (hard clear - user is abandoning this)
        active.is_complete = False
        active.follow_up_history = []
        active.needs_review = False
        active.was_skipped = False
        
        # Reactivate previous step (don't clear its history)
        prev_step = self.steps[active_idx - 1]
        prev_step.is_complete = False
        prev_step.needs_review = False  # Being actively edited now
        
        # Soft-invalidate dependent steps (preserve their history for review)
        invalidated = self._invalidate_dependents(prev_step.refinement_aspect.id)
        
        message = f"Returned to step {active_idx}: {prev_step.refinement_aspect.aspect_name}"
        if invalidated:
            message += f". Marked for review: {', '.join(invalidated)}"
        
        return {
            "success": True,
            "message": message,
            "step_index": active_idx - 1,
            "step": prev_step,
            "invalidated": invalidated,
        }
    
    def _go_to_step(self, step_number: int) -> Dict[str, Any]:
        """Navigate to a specific step and soft-invalidate dependent refinement aspects."""
        if step_number < 1 or step_number > len(self.steps):
            return {
                "success": False,
                "message": f"Invalid step number. Valid range: 1-{len(self.steps)}",
            }
        
        step_idx = step_number - 1
        target_step = self.steps[step_idx]
        
        # Clear target step's history (user is re-editing)
        target_step.is_complete = False
        target_step.follow_up_history = []
        target_step.needs_review = False
        target_step.was_skipped = False
        
        # Soft-invalidate all dependents of the target (preserve their history)
        invalidated = self._invalidate_dependents(target_step.refinement_aspect.id)
        
        # Also soft-invalidate all steps after the target
        for i in range(step_idx + 1, len(self.steps)):
            if self.steps[i].is_complete or self.steps[i].follow_up_history:
                self.steps[i].is_complete = False
                self.steps[i].needs_review = True  # Preserve history, mark for review
                if self.steps[i].refinement_aspect.aspect_name not in invalidated:
                    invalidated.append(self.steps[i].refinement_aspect.aspect_name)
        
        message = f"Jumped to step {step_number}: {target_step.refinement_aspect.aspect_name}"
        if invalidated:
            message += f". Marked for review: {', '.join(invalidated)}"
        
        return {
            "success": True,
            "message": message,
            "step_index": step_idx,
            "step": target_step,
            "invalidated": invalidated,
        }
    
    def _restart(self) -> Dict[str, Any]:
        """Restart the entire refinement session (hard clear all data)."""
        # Mark all steps incomplete and clear all data
        for step in self.steps:
            step.is_complete = False
            step.follow_up_history = []
            step.needs_review = False
            step.was_skipped = False
        self.synthesis_requested = False
        
        return {
            "success": True,
            "message": "Session restarted. All progress cleared.",
        }
    
    def _skip_current(self) -> Dict[str, Any]:
        """Skip the current refinement aspect while preserving any captured input."""
        active = self.get_active_step()
        if not active:
            return {"success": False, "message": "No active step to skip"}

        return self._finalize_active_step(
            active,
            mark_skipped=True,
            success_message=f"Skipped refinement aspect: {active.refinement_aspect.aspect_name}",
        )

    def _finish_current(self) -> Dict[str, Any]:
        """Finish the current step, preserving captured responses (if any)."""
        active = self.get_active_step()
        if not active:
            return {"success": False, "message": "No active step to finish"}

        message = f"Completed refinement aspect: {active.refinement_aspect.aspect_name}"
        if not active.refined_value:
            message += " (no additional details provided)."

        return self._finalize_active_step(
            active,
            mark_skipped=None,
            success_message=message,
        )

    def _finalize_active_step(
        self,
        active: QueryAspectRefiner,
        *,
        mark_skipped: Optional[bool],
        success_message: str,
    ) -> Dict[str, Any]:
        """Mark the provided step complete while preserving history."""

        active.is_complete = True
        active.needs_review = False
        if mark_skipped is None:
            mark_skipped = not bool(active.refined_value)
        active.was_skipped = mark_skipped

        return {
            "success": True,
            "message": success_message,
            "step": active,
        }

    def _request_synthesis(self) -> Dict[str, Any]:
        """Request immediate synthesis using currently captured clarifications."""
        self.synthesis_requested = True
        return {
            "success": True,
            "message": "Generating refined query with current clarifications.",
            "submit": True,
        }
    
    def _get_status(self) -> Dict[str, Any]:
        """Get current session status."""
        active = self.get_active_step()
        summary = self.get_step_summary()
        
        status_lines = [
            "Session Status:",
            f"  Steps: {summary['completed']}/{summary['total_steps']} complete",
            f"  Needs review: {summary['needs_review']}",
            f"  In progress: {summary['in_progress']}",
            f"  Follow-ups asked: {summary['total_follow_ups']}",
        ]
        
        if active:
            active_idx = self.steps.index(active) + 1
            status_tag = " (needs review)" if active.needs_review else ""
            status_lines.append(f"  Current: Step {active_idx} - {active.refinement_aspect.aspect_name}{status_tag}")
        else:
            status_lines.append("  Current: Session complete")
        
        return {
            "success": True,
            "message": "\n".join(status_lines),
            "summary": summary,
            "active_step": active,
        }
    
    def _list_steps(self) -> Dict[str, Any]:
        """List all steps with their status."""
        active = self.get_active_step()
        
        lines = ["Refinement Steps:"]
        for i, step in enumerate(self.steps, 1):
            if step.is_complete and not step.needs_review:
                status = "completed"
            elif step.needs_review:
                status = "needs review"
            elif step == active:
                status = "active"
            else:
                status = "not started"

            followups = f" ({step.follow_up_count} follow-ups)" if step.follow_up_count > 0 else ""
            lines.append(f"  {i}. [{status}] {step.refinement_aspect.aspect_name}{followups}")
        
        return {
            "success": True,
            "message": "\n".join(lines),
            "steps": self.steps,
        }
    
    def to_dict(self) -> Dict[str, Any]:
        """
        Serializes the session to a dictionary.

        Returns:
            Dict[str, Any]: The serialized session.
        """
        return {
            "original_query": self.original_query,
            "refinement_aspects": [aspect.aspect_name for aspect in self.refinement_framework],
            "steps": [
                {
                    "refinement_aspect_id": step.refinement_aspect.id,
                    "refinement_aspect_name": step.refinement_aspect.aspect_name,
                    "refinement_aspect_description": step.refinement_aspect.aspect_description,
                    # Multi-turn conversation
                    "follow_up_history": step.follow_up_history,
                    # Completion status
                    "is_complete": step.is_complete,
                    "refined_value": step.refined_value_as_str,
                }
                for step in self.steps
            ],
        }
    


class QueryRefinementManager:
    def run_followup_until_clear(
        self,
        session: QueryRefinementSession,
        aspect_id: Optional[str] = None,
        max_rounds: Optional[int] = None
    ) -> Dict[str, Any]:
        step = self._get_target_step(session, aspect_id)
        rounds = 0
        max_followups = max_rounds if max_rounds is not None else step.refinement_aspect.max_follow_ups

        if step.is_complete:
            return self._build_followup_result(step, step.refined_value_as_str, rounds)

        parsed_payload = None
        final_value = None
        followup_question = None
        reasoning = None
        response_text = None
        error_message = None
        is_error = False

        while not step.is_complete and rounds < max_followups:
            dependency_context = session.get_dependency_context(step.refinement_aspect.id)
            system_prompt, user_prompt = step.get_prompts(
                query=session.original_query,
                dependency_context=dependency_context
            )
            response_text, parsed_payload, is_error, error_message = self._get_llm_response_with_validation(
                aspect=step.refinement_aspect,
                system_prompt=system_prompt,
                user_prompt=user_prompt
            )
            
            if parsed_payload:
                final_value = parsed_payload.get("final_value")
                # BASE_SCHEMA_FIELDS uses "clarifying_question", not "followup_question"
                followup_question = parsed_payload.get("clarifying_question") or parsed_payload.get("followup_question")
                reasoning = parsed_payload.get("reasoning") or parsed_payload.get("explanation")
            if is_error:
                step.add_follow_up(question=step.refinement_question or step.refinement_aspect.aspect_name, response=f"[Validation error: {error_message}]")
                step.is_complete = True
                break
            step.add_follow_up(
                question=followup_question or step.refinement_question or step.refinement_aspect.aspect_name,
                response=response_text
            )
            rounds += 1
            if rounds == max_followups:
                if parsed_payload and parsed_payload.get("is_complete", False):
                    step.is_complete = True
                    step.needs_refinement_rationale = reasoning
                    # Value already extracted by add_follow_up() -> extract_and_store_value()
                else:
                    step.is_complete = False
                break
            if parsed_payload and parsed_payload.get("is_complete", False):
                step.is_complete = True
                step.needs_refinement_rationale = reasoning
                # Value already extracted by add_follow_up() -> extract_and_store_value()
                break
            # Only update refinement_question if followup_question is not empty
            if followup_question:
                step.refinement_question = followup_question

        return self._build_followup_result(step, step.refined_value_as_str, rounds)

    def _get_target_step(
        self,
        session: QueryRefinementSession,
        aspect_id: Optional[str]
    ) -> QueryAspectRefiner:
        """Get the target step for follow-up, or last completed if none active."""
        if aspect_id:
            step_lookup = {candidate.refinement_aspect.id: candidate for candidate in session.steps}
            step = step_lookup.get(aspect_id)
        else:
            step = session.get_active_step()
        if step is None:
            completed_steps = [s for s in session.steps if s.is_complete]
            if completed_steps:
                step = completed_steps[-1]
            else:
                raise ValueError("No refinement aspect available for follow-up loop")
        return step

    def _build_followup_result(
        self,
        step: QueryAspectRefiner,
        final_value: Optional[str],
        rounds: int
    ) -> Dict[str, Any]:
        """Build result dict for follow-up loop."""
        return {
            "aspect_id": step.refinement_aspect.id,
            "aspect_name": step.refinement_aspect.aspect_name,
            "follow_up_history": step.follow_up_history,
            "is_complete": step.is_complete,
            "final_value": final_value,
            "rounds": rounds,
        }

     

    def __init__(
        self,
        llm_provider: LLMProviderInterface,
        query_analyzer: QueryAnalyzerInterface,
        tracing_provider: Optional[TracingProviderInterface] = None,
        parallel_config: Optional["ParallelConfig"] = None,
    ) -> None:
        self.llm_provider: LLMProviderInterface = llm_provider
        self.query_analyzer: QueryAnalyzerInterface = query_analyzer
        self.tracing_provider: TracingProviderInterface = tracing_provider or NoOpTracingProvider()
        self.parallel_config: Optional["ParallelConfig"] = parallel_config
        self.trace_emitter: TraceEventEmitter = TraceEventEmitter(self.tracing_provider)
        logger.info(
            "QueryRefinementManager initialized with LLM provider: %s, Query Analyzer: %s, Tracing Provider: %s, Parallel: %s",
            llm_provider.__class__.__name__,
            query_analyzer.__class__.__name__ if query_analyzer else "None",
            self.tracing_provider.__class__.__name__,
            "enabled" if parallel_config else "disabled"
        )
        self.validation_max_retries: int = 2
        self.trace_emitter.emit(
            "manager_initialized",
            metadata={
                "llm_provider": llm_provider.__class__.__name__,
                "query_analyzer": query_analyzer.__class__.__name__ if query_analyzer else "None",
                "parallel_enabled": parallel_config is not None,
            }
        )

    def initialize(
        self,
        original_query: str,
        refinement_framework: List[RefinementAspect],
        parallel_config: Optional["ParallelConfig"] = None,
    ) -> QueryRefinementSession:
        """
        Initialize a new refinement session by analyzing all aspects.
        
        This method orchestrates the session creation process:
        1. Creates a new session
        2. Runs analysis (parallel or sequential based on config)
        3. Populates session steps with analysis results
        
        Args:
            original_query: The user's initial query text
            refinement_framework: List of aspects to refine
            parallel_config: Optional configuration for parallel execution
            
        Returns:
            Initialized QueryRefinementSession ready for user interaction
        """
        with self.tracing_provider.trace_operation("initialize_refinement_session") as trace:
            if hasattr(trace, 'add_attribute'):
                trace.add_attribute("original_query", original_query)
                trace.add_attribute("num_refinement_aspects", len(refinement_framework))

            logger.info("Initializing refinement session for query: %s", original_query)
            logger.debug("Refinement framework aspects: %s",
                         [aspect.aspect_name for aspect in refinement_framework])
            
            # Create session
            session = self._create_session(original_query)
            
            # Run analysis based on configuration
            analysis_results = self._run_aspect_analysis(
                original_query=original_query,
                refinement_framework=refinement_framework,
                session=session,
                parallel_config=parallel_config,
            )
            
            # Populate session with analysis results
            aspects_needing_refinement_count = self._populate_session_steps(
                session=session,
                refinement_framework=refinement_framework,
                analysis_results=analysis_results,
            )
            
            # Log summary
            self._log_session_summary(session, aspects_needing_refinement_count)
            
        return session

    def initialize_sequential(
        self,
        original_query: str,
        refinement_framework: List[RefinementAspect],
    ) -> QueryRefinementSession:
        """
        Initialize a refinement session without upfront LLM analysis.
        
        This creates a session with all aspects but does NOT run any initial
        analysis to determine which aspects need refinement. Instead, aspects
        are refined on-demand as the user progresses through them sequentially.
        
        This approach:
        - Eliminates upfront LLM costs and wait time
        - Enables a simpler question-by-question workflow
        - Refines aspects in dependency order automatically
        - Each aspect refined to completion before moving to next
        
        Args:
            original_query: The user's initial query text
            refinement_framework: List of aspects to refine
            
        Returns:
            QueryRefinementSession ready for sequential refinement
        """
        with self.tracing_provider.trace_operation("initialize_sequential_refinement_session") as trace:
            if hasattr(trace, 'add_attribute'):
                trace.add_attribute("original_query", original_query)
                trace.add_attribute("num_refinement_aspects", len(refinement_framework))

            logger.info("Initializing sequential refinement session for query: %s", original_query)
            logger.debug("Refinement framework aspects: %s",
                         [aspect.aspect_name for aspect in refinement_framework])
            
            # Create session
            session = self._create_session(original_query)
            
            # Add all aspects as steps WITHOUT running analysis
            for aspect in refinement_framework:
                step = session.add_step(aspect)
                # Mark as incomplete and ready for refinement
                step.is_complete = False
                step.needs_refinement_rationale = None
                step.refinement_question = None
                
                logger.debug(
                    "Added aspect '%s' to session (will refine on-demand)",
                    aspect.id
                )
            
            logger.info(
                "Sequential session initialized with %d aspects (no upfront analysis)",
                len(session.steps)
            )
            
            self.trace_emitter.emit(
                "sequential_session_initialized",
                metadata={
                    "total_steps": len(session.steps),
                    "mode": "on-demand"
                }
            )
            
        return session

    def _create_session(self, original_query: str) -> QueryRefinementSession:
        """Create a new refinement session."""
        return QueryRefinementSession(original_query=original_query)

    def _run_aspect_analysis(
        self,
        original_query: str,
        refinement_framework: List[RefinementAspect],
        session: QueryRefinementSession,
        parallel_config: Optional["ParallelConfig"],
    ) -> Dict[str, "AspectAnalysisResult"]:
        """
        Run aspect analysis using parallel or sequential execution.
        
        Returns:
            Dictionary mapping aspect IDs to their analysis results
        """
        use_parallel = parallel_config is not None and parallel_config.enabled
        
        if use_parallel:
            logger.info("Using parallel execution for aspect analysis")
            return self._analyze_aspects_parallel(
                original_query=original_query,
                refinement_framework=refinement_framework,
                session=session,
                parallel_config=parallel_config,
            )
        else:
            logger.debug("Using sequential execution for aspect analysis")
            return self._analyze_aspects_sequential(
                original_query=original_query,
                refinement_framework=refinement_framework,
                session=session,
            )

    def _populate_session_steps(
        self,
        session: QueryRefinementSession,
        refinement_framework: List[RefinementAspect],
        analysis_results: Dict[str, "AspectAnalysisResult"],
    ) -> int:
        """
        Populate session steps with analysis results.
        
        Returns:
            Count of aspects needing refinement
        """
        aspects_needing_refinement_count = 0
        
        for aspect in refinement_framework:
            step = session.add_step(aspect)
            analysis_result = analysis_results.get(aspect.id)
            
            if analysis_result is None:
                self._handle_failed_analysis(step, aspect)
                aspects_needing_refinement_count += 1
                continue
            
            # Store analysis results
            step.needs_refinement_rationale = analysis_result.explanation
            step.refinement_question = analysis_result.clarifying_question
            
            if analysis_result.needs_refinement:
                # Mark step as needing refinement
                step.is_complete = False
                logger.debug("Aspect %s needs refinement: %s", aspect.aspect_name, analysis_result.explanation)
                aspects_needing_refinement_count += 1
            else:
                # Mark step as complete with summary
                step.is_complete = True
                summary_text = (
                    analysis_result.explanation
                    or aspect.aspect_description
                    or f"Aspect '{aspect.aspect_name}' is sufficiently specified in the original query."
                )
                step.refined_value = summary_text.strip()
                logger.debug("Aspect %s is already clear in original query", aspect.aspect_name)
        
        return aspects_needing_refinement_count

    def _handle_failed_analysis(
        self,
        step: QueryAspectRefiner,
        aspect: RefinementAspect,
    ) -> None:
        """Handle failed analysis by marking step for refinement."""
        logger.warning("Analysis failed for aspect %s - marking for refinement", aspect.id)
        step.is_complete = False
        step.needs_refinement_rationale = "Analysis could not be completed"
        step.refinement_question = aspect.aspect_description or f"Please provide details about {aspect.aspect_name}"

    def _log_session_summary(
        self,
        session: QueryRefinementSession,
        aspects_needing_refinement_count: int,
    ) -> None:
        """Log session initialization summary."""
        already_clear_count = len(session.steps) - aspects_needing_refinement_count
        
        logger.info(
            "Session initialized with %d total steps (%d need refinement, %d already clear)",
            len(session.steps),
            aspects_needing_refinement_count,
            already_clear_count,
        )

        self.trace_emitter.emit(
            "session_initialized",
            metadata={
                "total_steps": len(session.steps),
                "needs_refinement": aspects_needing_refinement_count,
                "already_clear": already_clear_count,
            }
        )

    def _analyze_aspects_sequential(
        self,
        original_query: str,
        refinement_framework: List[RefinementAspect],
        session: QueryRefinementSession,
    ) -> Dict[str, "AspectAnalysisResult"]:
        """
        Analyze aspects sequentially in dependency order (original behavior).
        
        This is the default execution mode and fallback for parallel execution.
        """
        results = {}
        
        for aspect in refinement_framework:
            # Get dependency context from previously analyzed aspects
            dependency_context = session.get_dependency_context(aspect.id)
            analyzer_context = {
                dep_id: entry["value"]
                for dep_id, entry in dependency_context.items()
            }

            logger.debug(
                "Analyzing aspect '%s' with dependency context keys: %s",
                aspect.id,
                list(dependency_context.keys()) if dependency_context else [],
            )
            self.trace_emitter.emit(
                "aspect_analysis_start",
                metadata={
                    "aspect_id": aspect.id,
                    "depends_on": aspect.depends_on,
                    "has_dependency_context": bool(dependency_context),
                }
            )
            
            # Analyze this specific aspect with its dependency context
            analysis_result = None
            try:
                analysis_result = self.query_analyzer.analyze_aspect(
                    query=original_query,
                    aspect=aspect,
                    dependency_context=analyzer_context,
                    llm_provider=self.llm_provider
                )
                results[aspect.id] = analysis_result
                
                self.trace_emitter.emit(
                    "aspect_analysis_complete",
                    metadata={
                        "aspect_id": aspect.id,
                        "needs_refinement": analysis_result.needs_refinement,
                    }
                )
            except Exception as e:
                logger.error(
                    "Failed to analyze aspect %s: %s",
                    aspect.id,
                    e,
                    exc_info=True
                )
                results[aspect.id] = None
                
                self.trace_emitter.emit(
                    "aspect_analysis_complete",
                    metadata={
                        "aspect_id": aspect.id,
                        "needs_refinement": None,
                    }
                )
        
        return results

    def _analyze_aspects_parallel(
        self,
        original_query: str,
        refinement_framework: List[RefinementAspect],
        session: QueryRefinementSession,
        parallel_config: "ParallelConfig",
    ) -> Dict[str, "AspectAnalysisResult"]:
        """
        Analyze aspects in parallel using dependency-aware level-by-level execution.
        
        Falls back to sequential execution on errors or if async execution fails.
        """
        try:
            # Import here to avoid circular dependency
            from .parallel import ParallelQueryAnalyzer
            
            # Create parallel analyzer
            parallel_analyzer = ParallelQueryAnalyzer(
                query_analyzer=self.query_analyzer,
                config=parallel_config,
                trace_emitter=self.trace_emitter
            )
            
            # Define dependency context provider
            def get_dependency_context(aspect_id: str) -> Dict[str, str]:
                dependency_context = session.get_dependency_context(aspect_id)
                return {
                    dep_id: entry["value"]
                    for dep_id, entry in dependency_context.items()
                }
            
            # Run parallel analysis in event loop
            try:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    # Already in async context - this shouldn't happen in typical CLI usage
                    # but could occur in API context
                    logger.warning("Event loop already running - falling back to sequential execution")
                    return self._analyze_aspects_sequential(
                        original_query, refinement_framework, session
                    )
                else:
                    results = loop.run_until_complete(
                        parallel_analyzer.analyze_aspects_parallel(
                            query=original_query,
                            aspects=refinement_framework,
                            llm_provider=self.llm_provider,
                            dependency_context_provider=get_dependency_context,
                            user_id=None,  # TODO: Pass user_id from session if available
                        )
                    )
                    return results
            except RuntimeError:
                # No event loop - create one
                results = asyncio.run(
                    parallel_analyzer.analyze_aspects_parallel(
                        query=original_query,
                        aspects=refinement_framework,
                        llm_provider=self.llm_provider,
                        dependency_context_provider=get_dependency_context,
                        user_id=None,
                    )
                )
                return results
        
        except Exception as e:
            logger.error(
                "Parallel execution failed: %s - falling back to sequential",
                e,
                exc_info=True
            )
            self.trace_emitter.emit(
                "parallel_execution_error",
                metadata={"error": str(e), "fallback": "sequential"}
            )
            return self._analyze_aspects_sequential(
                original_query, refinement_framework, session
            )

    async def initialize_streaming(
        self,
        original_query: str,
        refinement_framework: List[RefinementAspect],
        parallel_config: Optional["ParallelConfig"] = None,
    ):
        """
        Initialize a new refinement session with streaming results.
        
        Yields analysis results as each dependency level completes, enabling
        incremental UI updates and faster perceived performance.
        
        Args:
            original_query: The user's initial query text
            refinement_framework: List of aspects to refine
            parallel_config: Optional configuration for parallel execution
            
        Yields:
            Tuple of (session, level_idx, level_results, metadata, is_final)
            - session: QueryRefinementSession (partial until is_final=True)
            - level_idx: Index of completed level (None if final)
            - level_results: Dict of AspectAnalysisResults for this level
            - metadata: Execution metadata (timing, counts)
            - is_final: True on final yield with complete session
        """
        with self.tracing_provider.trace_operation("initialize_refinement_session_streaming") as trace:
            if hasattr(trace, 'add_attribute'):
                trace.add_attribute("original_query", original_query)
                trace.add_attribute("num_refinement_aspects", len(refinement_framework))

            logger.info("Initializing refinement session (streaming) for query: %s", original_query)
            logger.debug("Refinement framework aspects: %s",
                         [aspect.aspect_name for aspect in refinement_framework])
            
            # Create session
            session = self._create_session(original_query)
            
            use_parallel = parallel_config is not None and parallel_config.enabled
            
            if not use_parallel:
                # Fallback to non-streaming for sequential execution
                analysis_results = self._analyze_aspects_sequential(
                    original_query=original_query,
                    refinement_framework=refinement_framework,
                    session=session,
                )
                aspects_needing_refinement_count = self._populate_session_steps(
                    session=session,
                    refinement_framework=refinement_framework,
                    analysis_results=analysis_results,
                )
                self._log_session_summary(session, aspects_needing_refinement_count)
                yield session, None, analysis_results, {"total_aspects": len(refinement_framework)}, True
                return
            
            # Run parallel analysis with streaming
            try:
                from .parallel import ParallelQueryAnalyzer
                
                parallel_analyzer = ParallelQueryAnalyzer(
                    query_analyzer=self.query_analyzer,
                    config=parallel_config,
                    trace_emitter=self.trace_emitter
                )
                
                def get_dependency_context(aspect_id: str) -> Dict[str, str]:
                    dependency_context = session.get_dependency_context(aspect_id)
                    return {
                        dep_id: entry["value"]
                        for dep_id, entry in dependency_context.items()
                    }
                
                # Stream results as each level completes - simple async iteration
                all_results: Dict[str, "AspectAnalysisResult"] = {}
                
                logger.debug("Starting async streaming iteration")
                async for level_idx, level_results, metadata in parallel_analyzer.analyze_aspects_parallel_streaming(
                    query=original_query,
                    aspects=refinement_framework,
                    llm_provider=self.llm_provider,
                    dependency_context_provider=get_dependency_context,
                    user_id=None,
                ):
                    all_results.update(level_results)
                    logger.debug("Yielding level %d results with %d aspects", level_idx, len(level_results))
                    yield session, level_idx, level_results, metadata, False
                
                # Populate final session with all results
                aspects_needing_refinement_count = self._populate_session_steps(
                    session=session,
                    refinement_framework=refinement_framework,
                    analysis_results=all_results,
                )
                self._log_session_summary(session, aspects_needing_refinement_count)
                
                # Yield final complete session
                yield session, None, all_results, {"total_aspects": len(refinement_framework), "final": True}, True
                
            except Exception as e:
                logger.error("Streaming initialization failed: %s - falling back", e, exc_info=True)
                self.trace_emitter.emit(
                    "streaming_initialization_error",
                    metadata={"error": str(e), "fallback": "non-streaming"}
                )
                # Fallback to non-streaming
                analysis_results = self._analyze_aspects_sequential(
                    original_query, refinement_framework, session
                )
                aspects_needing_refinement_count = self._populate_session_steps(
                    session, refinement_framework, analysis_results
                )
                self._log_session_summary(session, aspects_needing_refinement_count)
                yield session, None, analysis_results, {"total_aspects": len(refinement_framework)}, True

    def ensure_step_is_ready(
        self,
        session: QueryRefinementSession,
        step: QueryAspectRefiner,
    ) -> bool:
        aspect_id = step.refinement_aspect.id
        logger.debug("Ensuring readiness for aspect %s", aspect_id)
        self.trace_emitter.emit(
            "step_readiness_check",
            metadata={
                "aspect_id": aspect_id,
                "needs_review": step.needs_review,
                "follow_up_count": step.follow_up_count,
            },
        )

        if self._maybe_autocomplete_dependent_step(session, step):
            return False

        self.trace_emitter.emit(
            "step_ready_for_prompt",
            metadata={
                "aspect_id": aspect_id,
                "depends_on": step.refinement_aspect.depends_on,
            },
        )
        return True

    def _maybe_autocomplete_dependent_step(
        self,
        session: QueryRefinementSession,
        step: QueryAspectRefiner,
    ) -> bool:
        aspect = step.refinement_aspect

        if not aspect.depends_on:
            return False

        if step.follow_up_history:
            # User already supplied input; keep existing flow.
            self.trace_emitter.emit(
                "dependent_step_has_user_input",
                metadata={"aspect_id": aspect.id, "follow_up_count": step.follow_up_count},
            )
            return False

        dependency_context = session.get_dependency_context(aspect.id)
        missing = [dep for dep in (aspect.depends_on or []) if dep not in dependency_context]
        if missing:
            # Dependencies not ready; rely on ordering to handle them first.
            logger.debug(
                "Aspect %s waiting for dependency context from %s",
                aspect.id,
                missing,
            )
            self.trace_emitter.emit(
                "dependent_step_waiting_on_dependencies",
                metadata={"aspect_id": aspect.id, "pending_dependencies": missing},
            )
            return False

        analyzer_context = {
            dep_id: entry["value"] for dep_id, entry in dependency_context.items()
        }

        logger.debug(
            "Re-analyzing dependent aspect '%s' after dependency completion",
            aspect.id,
        )
        self.trace_emitter.emit(
            "dependent_step_reanalysis_start",
            metadata={
                "aspect_id": aspect.id,
                "dependency_keys": list(dependency_context.keys()),
            },
        )

        analysis_result = self.query_analyzer.analyze_aspect(
            query=session.original_query,
            aspect=aspect,
            dependency_context=analyzer_context,
            llm_provider=self.llm_provider,
        )

        step.needs_refinement_rationale = analysis_result.explanation
        step.refinement_question = analysis_result.clarifying_question
        step.needs_review = False

        if analysis_result.needs_refinement:
            step.is_complete = False
            self.trace_emitter.emit(
                "dependent_step_requires_followup",
                metadata={"aspect_id": aspect.id},
            )
            return False

        step.is_complete = True
        step.was_skipped = False
        summary_text = (
            analysis_result.explanation
            or aspect.aspect_description
            or f"Aspect '{aspect.aspect_name}' is sufficiently specified after refreshed analysis."
        )
        # Store as refined_value (single source of truth)
        step.refined_value = summary_text.strip()

        logger.debug(
            "Aspect %s marked complete after refreshed analysis", aspect.id
        )
        self.trace_emitter.emit(
            "dependent_step_autocompleted",
            metadata={
                "aspect_id": aspect.id,
                "summary_present": bool(step.refined_value),
            },
        )

        return True

    def process_next_step(self, session: QueryRefinementSession) -> Optional[Dict[str, Any]]:
        """
        Process the next incomplete refinement step with exactly ONE LLM interaction.

        Orchestrates:
        1. Finding next ready step
        2. Building dependency context
        3. Calling LLM
        4. Storing result

        Args:
            session: The refinement session to process

        Returns:
            Dict with {"aspect_id", "aspect_name", "question", "response"} when a step was
            processed, or None if there are no remaining steps.
        """
        with self.tracing_provider.trace_operation("process_next_step"):
            # Find next ready step
            step = self._find_next_ready_step(session)
            
            if step is None:
                return None
            
            # Execute step
            return self._execute_step(session, step)

    def _find_next_ready_step(
        self,
        session: QueryRefinementSession
    ) -> Optional[QueryAspectRefiner]:
        """
        Find the next step that is ready to process.
        
        Loops through active steps and checks readiness, handling dependencies.
        
        Returns:
            Next ready step, or None if no steps remain.
        """
        while True:
            step = session.get_active_step()

            if step is None:
                logger.debug("No active step remaining to process")
                self.trace_emitter.emit(
                    "no_eligible_step",
                    metadata={"session_steps": len(session.steps)}
                )
                return None

            if self.ensure_step_is_ready(session, step):
                return step

    def _execute_step(
        self,
        session: QueryRefinementSession,
        step: QueryAspectRefiner
    ) -> Dict[str, Any]:
        """
        Execute a single refinement step: get prompts, call LLM, store result.
        
        Returns:
            Dict with aspect_id, aspect_name, question, response, and error flag.
        """
        aspect = step.refinement_aspect
        dependency_context = session.get_dependency_context(aspect.id)
        
        logger.debug("Processing aspect '%s'", aspect.id)
        self.trace_emitter.emit(
            "aspect_processing_start",
            metadata={
                "aspect_id": aspect.id,
                "needs_review": step.needs_review,
                "dependency_count": len(dependency_context),
            }
        )
        
        # Get prompts and call LLM
        system_prompt, user_prompt = step.get_prompts(
            query=session.original_query,
            dependency_context=dependency_context
        )
        
        response_text, parsed_payload, is_error, error_message = self._get_llm_response_with_validation(
            aspect=aspect,
            system_prompt=system_prompt,
            user_prompt=user_prompt
        )
        
        # Handle error or success
        if is_error:
            return self._handle_step_error(step, aspect, error_message)
        
        return self._handle_step_success(step, aspect, response_text, parsed_payload)

    def _handle_step_error(
        self,
        step: QueryAspectRefiner,
        aspect: RefinementAspect,
        error_message: Optional[str]
    ) -> Dict[str, Any]:
        """
        Handle step execution error by recording failure and marking complete.
        
        Returns:
            Dict with error response.
        """
        failure_response = f"[Validation error: {error_message}]" if error_message else "[Validation error]"
        question_text = step.refinement_question or aspect.aspect_name
        
        step.add_follow_up(question=question_text, response=failure_response)
        step.is_complete = True
        
        self.trace_emitter.emit(
            "aspect_processing_failed",
            level="error",
            metadata={
                "aspect_id": aspect.id,
                "error": error_message,
            }
        )
        
        return {
            "aspect_id": aspect.id,
            "aspect_name": aspect.aspect_name,
            "question": question_text,
            "response": failure_response,
            "error": True
        }

    def _handle_step_success(
        self,
        step: QueryAspectRefiner,
        aspect: RefinementAspect,
        response_text: str,
        parsed_payload: Optional[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """
        Handle successful step execution by storing response and marking complete.
        
        Returns:
            Dict with successful response.
        """
        question_text = step.refinement_question or aspect.aspect_name
        step.add_follow_up(question=question_text, response=response_text)
        step.is_complete = True
        
        logger.info(
            "Processed aspect %s: %s",
            aspect.id,
            response_text[:80] + "..." if len(response_text) > 80 else response_text
        )
        
        self.trace_emitter.emit(
            "aspect_processing_complete",
            metadata={
                "aspect_id": aspect.id,
                "response_length": len(response_text),
                "structured": parsed_payload is not None,
            }
        )
        
        return {
            "aspect_id": aspect.id,
            "aspect_name": aspect.aspect_name,
            "question": question_text,
            "response": response_text,
            **({"structured_payload": parsed_payload} if parsed_payload is not None else {}),
            "error": False
        }

    def _get_llm_response_with_validation(
        self,
        aspect: RefinementAspect,
        system_prompt: str,
        user_prompt: str,
    ) -> tuple[str, Optional[Dict[str, Any]], bool, Optional[str]]:
        """
        Call the LLM and enforce structured response validation when required.
        
        Retries up to validation_max_retries times if validation fails.

        Returns:
            Tuple of (normalized_response_text, parsed_payload, is_error, error_message)
        """
        self.trace_emitter.emit(
            "llm_validation_start",
            metadata={
                "aspect_id": aspect.id,
                "max_retries": self.validation_max_retries,
            }
        )

        prompt = user_prompt
        base_prompt = user_prompt

        for attempt in range(self.validation_max_retries + 1):
            attempt_number = attempt + 1
            
            # Call LLM
            response_text, llm_error = self._call_llm(
                aspect=aspect,
                system_prompt=system_prompt,
                user_prompt=prompt,
                attempt_number=attempt_number,
            )
            
            if llm_error:
                return "", None, True, llm_error
            
            # Log raw response for debugging
            logger.info(
                "Raw LLM response for aspect '%s': %s",
                aspect.id,
                response_text[:500] if response_text else "(empty)"
            )
            
            # Parse and validate structured response
            validation_result = self._validate_structured_response(
                aspect=aspect,
                response_text=response_text,
                attempt_number=attempt_number,
            )
            
            if validation_result.is_valid:
                return validation_result.normalized_text, validation_result.parsed_payload, False, None
            
            # Retry if attempts remain
            if attempt < self.validation_max_retries:
                self.trace_emitter.emit(
                    "llm_validation_retry",
                    level="warning",
                    metadata={
                        "aspect_id": aspect.id,
                        "attempt": attempt_number,
                        "error": validation_result.error_message,
                    }
                )
                prompt = self._augment_prompt_for_retry(
                    base_prompt,
                    validation_result.error_message,
                    attempt_number,
                    response_text,
                )
                continue
            
            # Max retries exhausted
            self.trace_emitter.emit(
                "llm_validation_failed",
                level="error",
                metadata={
                    "aspect_id": aspect.id,
                    "attempt": attempt_number,
                    "error": validation_result.error_message,
                }
            )
            return response_text, validation_result.parsed_payload, True, validation_result.error_message

        return "", None, True, "Unknown validation failure"

    def _call_llm(
        self,
        aspect: RefinementAspect,
        system_prompt: str,
        user_prompt: str,
        attempt_number: int,
    ) -> tuple[str, Optional[str]]:
        """
        Call the LLM provider with the given prompts.
        
        Returns:
            Tuple of (response_text, error_message). error_message is None on success.
        """
        self.trace_emitter.emit(
            "llm_completion_attempt",
            metadata={
                "aspect_id": aspect.id,
                "attempt": attempt_number,
            }
        )
        self.trace_emitter.emit(
            "llm_prompt_attempt",
            metadata={
                "aspect_id": aspect.id,
                "attempt": attempt_number,
                "system_prompt": system_prompt,
                "user_prompt": user_prompt,
            },
        )
        
        logger.info(
            "LLM prompt attempt | aspect=%s | attempt=%d | system_prompt=%s | user_prompt=%s",
            aspect.id,
            attempt_number,
            system_prompt or "",
            user_prompt,
        )
        
        try:
            # Note: response_format parameter is not used because:
            # 1. Not all LLM providers support it consistently (especially Claude via LiteLLM)
            # 2. We handle JSON parsing with markdown stripping as a robust fallback
            # 3. Prompt engineering + validation works reliably across all models
            result = self.llm_provider.complete(
                system_prompt=system_prompt,
                user_prompt=user_prompt
            )
            response_text = (result.context or "").strip()
            return response_text, None
            
        except Exception as exc:  # pragma: no cover
            logger.exception(
                "LLM call failed while processing aspect %s on attempt %d: %s",
                aspect.id,
                attempt_number,
                exc,
            )
            self.trace_emitter.emit(
                "llm_completion_error",
                level="error",
                metadata={
                    "aspect_id": aspect.id,
                    "attempt": attempt_number,
                    "error": str(exc),
                }
            )
            return "", f"LLM error: {exc}"

    @dataclass
    class _ValidationResult:
        """Result of structured response validation."""
        is_valid: bool
        normalized_text: Optional[str] = None
        parsed_payload: Optional[Dict[str, Any]] = None
        error_message: Optional[str] = None
        warnings: Optional[List[str]] = None

    def _validate_structured_response(
        self,
        aspect: RefinementAspect,
        response_text: str,
        attempt_number: int,
    ) -> "_ValidationResult":
        """
        Parse and validate a structured JSON response.
        
        Returns:
            ValidationResult with validation status and details
        """
        # Strip markdown code fences if present (fallback for older responses or non-JSON mode)
        cleaned_text = response_text.strip()
        if cleaned_text.startswith("```"):
            lines = cleaned_text.splitlines()
            if len(lines) >= 2 and lines[0].startswith("```"):
                # Drop opening fence and optional closing fence
                body = lines[1:]
                if body and body[-1].startswith("```"):
                    body = body[:-1]
                cleaned_text = "\n".join(body)
        
        # Parse JSON
        try:
            parsed_payload = json.loads(cleaned_text)
        except json.JSONDecodeError as json_error:
            error_message = f"Response is not valid JSON: {json_error}"
            logger.warning(
                "Aspect %s produced non-JSON response on attempt %d: %s",
                aspect.id,
                attempt_number,
                error_message,
            )
            return self._ValidationResult(
                is_valid=False,
                parsed_payload=None,
                error_message=error_message,
            )
        
        # Validate against schema
        is_valid, validation_error, warnings = aspect.validate_response_strict(parsed_payload)
        
        if is_valid:
            if warnings:
                logger.warning(
                    "Response validation warnings for aspect %s: %s",
                    aspect.id,
                    "; ".join(warnings),
                )
                self.trace_emitter.emit(
                    "llm_validation_warning",
                    level="warning",
                    metadata={
                        "aspect_id": aspect.id,
                        "attempt": attempt_number,
                        "warnings": warnings,
                    }
                )
            
            normalized_text = json.dumps(parsed_payload, ensure_ascii=False)
            self.trace_emitter.emit(
                "llm_validation_success",
                metadata={
                    "aspect_id": aspect.id,
                    "attempt": attempt_number,
                }
            )
            return self._ValidationResult(
                is_valid=True,
                normalized_text=normalized_text,
                parsed_payload=parsed_payload,
                warnings=warnings,
            )
        
        # Validation failed
        error_message = validation_error or "Structured response failed validation"
        logger.warning(
            "Aspect %s response failed schema validation on attempt %d: %s",
            aspect.id,
            attempt_number,
            error_message,
        )
        return self._ValidationResult(
            is_valid=False,
            parsed_payload=parsed_payload,
            error_message=error_message,
        )

    @staticmethod
    def _augment_prompt_for_retry(
        base_prompt: str,
        error_details: str,
        attempt_number: int,
        previous_response: Optional[str] = None,
    ) -> str:
        """Append remediation guidance to the original prompt for retry attempts."""
        guidance_lines = [
            "\n\n---",
            f"ATTEMPT {attempt_number}: Your previous response did not satisfy the required JSON schema.",
            f"Error details: {error_details}",
            "Respond again with VALID JSON that matches the schema exactly.",
            "Return ONLY the JSON object. Do not include markdown, code fences, or explanations.",
        ]

        if previous_response:
            truncated_previous = previous_response[:400].replace("\n", " ")
            guidance_lines.append(
                f"Previous response (truncated): {truncated_previous}"
            )

        return base_prompt + "\n".join(guidance_lines)

    def build_follow_up_prompts(
        self,
        session: QueryRefinementSession,
        aspect_id: Optional[str] = None,
        *,
        include_examples: bool = True,
    ) -> tuple[str, str]:
        """Produce system/user prompts for an automated follow-up evaluation.

        The consumer is expected to call this after at least one response has been
        captured for the target aspect. The user prompt incorporates the fixed
        follow-up guidance plus the full conversation history for that aspect.

        Args:
            session: Active refinement session containing the step history.
            aspect_id: Optional explicit aspect identifier. When omitted, the
                current active step is used.
            include_examples: Whether to include examples in the follow-up prompt.

        Returns:
            Tuple of (system_prompt, user_prompt) ready for an LLM call.
        """

        step: Optional[QueryAspectRefiner]
        if aspect_id:
            step_lookup = {candidate.refinement_aspect.id: candidate for candidate in session.steps}
            step = step_lookup.get(aspect_id)
        else:
            step = session.get_active_step()

        if step is None:
            raise ValueError("No refinement aspect available for follow-up prompts")

        if not step.follow_up_history:
            raise ValueError(
                f"Follow-up prompts require at least one recorded response for aspect '{step.refinement_aspect.id}'."
            )

        system_prompt = step.get_system_role()
        user_prompt = step.format_follow_up_prompt_template(
            original_query=session.original_query,
            include_examples=include_examples,
        )

        return system_prompt, user_prompt

    def _gather_refinement_details(
        self, session: QueryRefinementSession
    ) -> tuple[List[tuple[str, str]], List[tuple[str, str]]]:
        """Collect refinement clarifications and baseline summaries for synthesis.
        
        Uses refined_value as single source of truth for synthesized values.
        """

        clarifications: List[tuple[str, str]] = []
        baseline_summaries: List[tuple[str, str]] = []

        for step in session.steps:
            if step.was_skipped:
                continue
            
            # Use refined_value if available (single source of truth)
            if step.refined_value is not None:
                # Convert to string representation
                if isinstance(step.refined_value, (dict, list)):
                    summary = json.dumps(step.refined_value, ensure_ascii=False)
                else:
                    summary = str(step.refined_value)
                
                summary = summary.strip()
                if summary:
                    if step.follow_up_history:
                        # Had follow-ups, so this is a refined/synthesized value
                        clarifications.append((step.refinement_aspect.aspect_name, summary))
                    else:
                        # No follow-ups, was clear in original query
                        baseline_summaries.append((step.refinement_aspect.aspect_name, summary))
                    continue
            
            # Fallback: needs_refinement_rationale (explanation why aspect was clear)
            if step.is_complete:
                rationale = (step.needs_refinement_rationale or "").strip()
                if rationale:
                    baseline_summaries.append((step.refinement_aspect.aspect_name, rationale))

        return clarifications, baseline_summaries

    def synthesize_refined_query(
        self,
        session: QueryRefinementSession,
        *,
        model: Optional[str] = None,
        temperature: float = 0.2,
        max_tokens: int = 256,
        additional_guidance: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Generate a refined query by combining the original query with clarifications.

        Args:
            session: Active refinement session containing user-provided clarifications.
            model: Optional model override for the synthesis call.
            temperature: Sampling temperature for the completion (default 0.2).
            max_tokens: Maximum tokens for the synthesis response (default 256).
            additional_guidance: Optional extra instruction appended to the prompt.

        Returns:
            Dictionary containing the refined query, whether the LLM was invoked,
            and supporting metadata.
        """

        clarifications, baseline_summaries = self._gather_refinement_details(session)

        if not clarifications and not baseline_summaries:
            logger.info(
                "Skipping LLM synthesis: no refinement clarifications or summaries recorded."
            )
            # Build refined_values map even when no LLM synthesis
            refined_values = {}
            for step in session.steps:
                aspect_id = step.refinement_aspect.id
                if step.refined_value is not None:
                    refined_values[aspect_id] = step.refined_value
                elif step.was_skipped:
                    refined_values[aspect_id] = "[SKIPPED]"
            
            return {
                "refined_query": session.original_query,
                "used_llm": False,
                "clarifications": [],
                "baseline_summaries": [],
                "refined_values": refined_values,  # ← Added
                "metadata": {
                    "reason": "no_clarifications",
                },
            }

        # TODO: extend and adapt the final refined query prompt to provide synonyms and a paragraph
        system_prompt = SYSTEM_PROMPT_REFINEMENT_END_UPPER

        user_sections = [
            "ORIGINAL USER-SUBMITTED RESEARCH INPUT:",
            session.original_query.strip(),
            "",
        ]

        if baseline_summaries:
            baseline_lines = "\n".join(
                f"- {name}: {value}" for name, value in baseline_summaries
            )
            user_sections.extend([
                "DETAILS ALREADY SPECIFIED IN THE ORIGINAL QUERY:",
                baseline_lines,
                "",
            ])

        if clarifications:
            clarification_lines = "\n".join(
                f"- {name}: {value}" for name, value in clarifications
            )
            user_sections.extend([
                "CONFIRMED CLARIFICATIONS FROM FOLLOW-UP QUESTIONS:",
                clarification_lines,
                "",
            ])

        user_sections.append(
            SYSTEM_PROMPT_REFINEMENT_END_LOWER
        )

        if additional_guidance:
            user_sections.append(additional_guidance.strip())

        user_prompt = "\n".join(section for section in user_sections if section).strip()

        self.trace_emitter.emit(
            "query_synthesis_start",
            metadata={
                "clarification_count": len(clarifications),
                "baseline_count": len(baseline_summaries),
                "model_override": model,
            },
        )

        completion_kwargs: Dict[str, Any] = {}
        if temperature is not None:
            completion_kwargs["temperature"] = temperature
        if max_tokens is not None:
            completion_kwargs["max_tokens"] = max_tokens

        try:
            result = self.llm_provider.complete(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                model=model,
                **completion_kwargs,
            )
        except Exception as exc:  # pragma: no cover - provider errors surfaced
            logger.exception("LLM synthesis failed: %s", exc)
            self.trace_emitter.emit(
                "query_synthesis_error",
                level="error",
                metadata={"error": str(exc)},
            )
            raise

        refined_query = (result.context or "").strip()

        if not refined_query:
            logger.warning("LLM synthesis returned empty response; using original query")
            refined_query = session.original_query

        self.trace_emitter.emit(
            "query_synthesis_complete",
            metadata={
                "clarification_count": len(clarifications),
                "baseline_count": len(baseline_summaries),
                "response_length": len(refined_query),
            },
        )

        # Build refined_values map for structured consumption
        refined_values = {}
        for step in session.steps:
            aspect_id = step.refinement_aspect.id
            if step.refined_value is not None:
                # Use native value (dict/list/str/etc)
                refined_values[aspect_id] = step.refined_value
            elif step.was_skipped:
                refined_values[aspect_id] = "[SKIPPED]"
            elif not step.follow_up_history and step.is_complete:
                # Was clear in original query
                refined_values[aspect_id] = "[CLEAR_IN_ORIGINAL]"

        return {
            "refined_query": refined_query,
            "used_llm": True,
            "clarifications": clarifications,
            "baseline_summaries": baseline_summaries,
            "refined_values": refined_values,  # ← Added for structured consumption
            "metadata": result.metadata,
        }

    def run_full_refinement(self, session: QueryRefinementSession, max_iterations: int = 100) -> QueryRefinementSession:
        """
        Run the full refinement session to completion (synchronous, blocking).

        Processes steps one-by-one in the order they appear in the session. Each
        step receives dependency context computed from previously completed/extracted steps.

        Args:
            session: The `QueryRefinementSession` to run.
            max_iterations: Safety cap to avoid infinite loops.

        Returns:
            The completed (or partially completed if hit cap) session object.
        """
        iterations = 0
        while not session.is_complete() and iterations < max_iterations:
            processed = self.process_next_step(session)
            if processed is None:
                break
            iterations += 1

        if iterations >= max_iterations:
            logger.warning("Reached max_iterations=%d while running refinement session", max_iterations)

        return session
    
    def get_initialization_summary(self, session: QueryRefinementSession) -> Dict[str, Any]:
        """
        Get a user-friendly summary of the initialization analysis.

        Use this after initialize() to present to the user what needs refinement.

        Returns:
            Dictionary with:
            - is_complete: bool - whether all aspects are clear (no refinement needed)
            - total_aspects: int - total number of aspects
            - aspects_needing_refinement: int - count needing refinement
            - aspects_clear: int - count already clear
            - aspects: list of dicts with details per aspect:
              - id: aspect identifier
              - name: aspect name
              - status: "clear" or "needs_refinement"
              - description: aspect description
              - reason: explanation of why refinement is needed (for needs_refinement only)
              - clarifying_question: suggested question to ask the user (for needs_refinement only)
        """
        aspects_needing_refinement = []
        aspects_clear = []
        
        for step in session.steps:
            aspect_info = {
                "id": step.refinement_aspect.id,
                "name": step.refinement_aspect.aspect_name,
                "description": step.refinement_aspect.aspect_description,
                "status": "clear" if step.is_complete else "needs_refinement"
            }
            
            # Add analysis details for aspects that need refinement
            if not step.is_complete:
                if step.needs_refinement_rationale:
                    aspect_info["reason"] = step.needs_refinement_rationale
                if step.refinement_question:
                    aspect_info["clarifying_question"] = step.refinement_question
            
            if step.is_complete:
                aspects_clear.append(aspect_info)
            else:
                aspects_needing_refinement.append(aspect_info)
        
        return {
            "is_complete": session.is_complete(),
            "total_aspects": len(session.steps),
            "aspects_needing_refinement": len(aspects_needing_refinement),
            "aspects_clear": len(aspects_clear),
            "aspects": aspects_needing_refinement + aspects_clear
        }