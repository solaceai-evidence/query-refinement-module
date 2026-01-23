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
from typing import Any, Callable, Dict, List, Literal, Optional, Union

from .interfaces import (
    LLMProviderInterface,
    TracingProviderInterface,
)
from .providers import NoOpTracingProvider, TraceEventEmitter
from .schema import (
    RefinementAspect,
    DimensionEvaluationResponse,
    SynthesisPromptBuilder,
    QueryRefinementResponse,
)

from .prompt.system_role import (
    GLOBAL_SYSTEM_PROMPT,
)
from .session_commands import SessionCommands

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
    RESTART = "restart"
    
    # Control
    SKIP = "skip"
    DONE = "done"
    CLEAR = "clear"
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
    "restart": UserCommand.RESTART,
    "skip": UserCommand.SKIP,
    "done": UserCommand.DONE,
    "clear": UserCommand.CLEAR,
    "status": UserCommand.STATUS,
    "help": UserCommand.HELP,
    "steps": UserCommand.STEPS,
    "submit": UserCommand.SUBMIT,
    "end": UserCommand.SUBMIT,
}


COMMANDS_REQUIRING_ARGUMENT = set()  # No commands require arguments in sequential mode


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
        # Validate numeric arguments (all current commands requiring arguments expect numbers)
        if not argument.isdigit():
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
  /back, /prev          Go back to previous step (clears current & future aspects)
  /restart              Start refinement from beginning

CONTROL:
  /skip                 Skip current aspect entirely (no data saved)
  /clear                Clear current aspect and regenerate question
  /done                 Mark current step complete (stop follow-ups)
  /submit, /end         Finish session immediately using current answers

INFORMATION:
  /status               Show session progress
  /steps                List processed aspects
  /help                 Show this help message

Examples:
  /skip                 - Skip current question (provides no context to dependents)
  /clear                - Restart current aspect from scratch
  /done                 - Accept current answer, no more follow-ups
  /back                 - Go to previous step (removes current and future)
"""


# =======
# Data Classes
# =======

@dataclass
class AspectRefinementState:
    """
    Represents the state of the evaluation for a single research dimension (aspect).
    
    Tracks the multi-turn conversation (initial question + follow-ups) until
    a final refined value for the aspect is obtained and accepted.

    Attributes:
        refinement_aspect: The RefinementAspect being refined   
        conversation_history: List of Q&A dicts for multi-turn refinement
        is_complete: Whether refinement is complete for this aspect
        needs_review: Whether the aspect needs review due to dependency changes
        was_skipped: Whether the user skipped this aspect entirely
        reasoning: Analysis result reasoning for refinement need/question
        follow_up_question: The clarification question for this aspect
        refinement_aspect_value: The extracted refined value in native type
    """

    refinement_aspect: RefinementAspect
    
    # Multi-turn conversation history (initial + all follow-ups)
    # Each entry: {'question': '...', 'response': '...'}
    conversation_history: List[Dict[str, str]] = field(default_factory=list)
    
    # Completion status - set when refinement is accepted/skipped or not needed as info is clear
    is_complete: bool = False
    
    # Review status - set when dependencies change, preserves history for review
    needs_review: bool = False

    # Whether the step was explicitly skipped by the user without supplying a value (or if supplied, value will be discarded)
    was_skipped: bool = False
    
    # Analysis result - stored from LLM's structured analysis output during initialize()
    # Contains: needs_refinement_rationale (why refinement needed/not), follow_up_question (what to ask)
    reasoning: Optional[str] = None
    follow_up_question: Optional[str] = None
    
    # Stores the aspect specification as refined by user interaction 
    normalized_value: Optional[Union[str, Dict, List, bool, int, float]] = None
    
    @property
    def follow_up_count(self) -> int:
        """Number of follow-up rounds completed."""
        return len(self.conversation_history)
    
    @property
    def normalized_value_as_str(self) -> Optional[str]:
        """
        Get string representation of refinement aspect value for display/storage.
        
        Returns:
            String representation of normalized_value (JSON for complex types)
        """
        if self.normalized_value is not None:
            if isinstance(self.normalized_value, (dict, list)):
                return json.dumps(self.normalized_value, ensure_ascii=False)
            return str(self.normalized_value)
        return None
    
    def extract_and_store_value(self, response: str) -> None:
        """
        Extract value from dynamic field in response and store in normalized_value.
        
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
                            self.normalized_value = value
                            return
            except (json.JSONDecodeError, TypeError):
                pass  # Not valid JSON, fall to plain text handling
        
        # For non-JSON responses, store the plain text directly
        # This preserves the behavior where any response contributes to the value
        if response.strip():
            self.normalized_value = response.strip()

    def get_global_system_role(self) -> str:
        """
        Get the global system role prompt for this refinement aspect.
        
        Returns:
            Global system prompt string
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
            self.refinement_aspect.get_evaluation_instructions_prompt(statement=query, **kwargs)
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
        if self.conversation_history:
            conversation_lines = [
                "",
                "### Conversation history for this aspect\n"
                "The following is the conversation history so far for this specific refinement aspect. "
                "Use it as context when determining if further follow-up is needed:",
                ""
            ]
            
            for idx, exchange in enumerate(self.conversation_history, 1):
                question = exchange.get('question', '')
                response = exchange.get('response', '')
                conversation_lines.append(f"**Turn {idx}:**")
                conversation_lines.append(f"Question: {question}")
                conversation_lines.append(f"Answer: {response}")
                conversation_lines.append("")
            
            refinement_instructions_prompt_sections.extend(conversation_lines)

        return system_prompt, "\n".join(refinement_instructions_prompt_sections)
    
    def get_messages(
        self,
        query: str,
        dependency_context: Optional[Dict[str, Dict[str, str]]] = None,
        **kwargs
    ) -> List[Dict[str, str]]:
        """
        Build messages array for LLM API (multi-turn dialogue representation).
        
        Constructs structured messages with:
        1. System message: Global platform instructions
        2. System message: Current dimension name, description, evaluation criteria
        3. System message: Previously completed dimensions (for context)
        4. System message: Dependency specifications (dimensions this one depends on)
        5. User message: Original query to analyze
        6. Conversation history: Alternating assistant/user messages
        
        Args:
            query: The query to analyze
            dependency_context: Values from completed dependencies
            **kwargs: Additional context for prompt formatting
            
        Returns:
            List of message dicts with 'role' and 'content' keys
        """
        messages = []
        
        # 1. System message: Global platform instructions
        messages.append({
            'role': 'system',
            'content': GLOBAL_SYSTEM_PROMPT
        })
        
        # 2. System message: Current dimension specification
        dimension_spec = "\n".join([
            f"# Current Dimension: {self.refinement_aspect.aspect_name}",
            f"\n**Description:** {self.refinement_aspect.aspect_description}",
            f"\n## Evaluation Criteria\n",
            self.refinement_aspect.evaluation_instructions
        ])
        messages.append({
            'role': 'system',
            'content': dimension_spec
        })
        
        # 3. System message: Previously completed dimensions (for context)
        if dependency_context:
            completed_dims = []
            for dep_id, entry in dependency_context.items():
                if entry and entry.get("value"):
                    dep_name = entry.get("name") or dep_id.replace("_", " ").title()
                    dep_desc = entry.get("description", "")
                    dep_value = entry["value"]
                    
                    if dep_desc:
                        completed_dims.append(f"**{dep_name}** ({dep_desc}): {dep_value}")
                    else:
                        completed_dims.append(f"**{dep_name}**: {dep_value}")
            
            if completed_dims:
                context_message = "\n".join([
                    "# Previously Completed Dimensions",
                    "\nThe following dimensions have been refined and clarified:",
                    "",
                    *completed_dims
                ])
                messages.append({
                    'role': 'system',
                    'content': context_message
                })
        
        # 4. System message: Dependency specifications (what this dimension must consider)
        if self.refinement_aspect.depends_on and dependency_context:
            dependency_specs = []
            for dep_id in self.refinement_aspect.depends_on:
                entry = dependency_context.get(dep_id)
                if entry and entry.get("value"):
                    dep_name = entry.get("name") or dep_id.replace("_", " ").title()
                    dep_desc = entry.get("description", "")
                    dep_value = entry["value"]
                    
                    if dep_desc:
                        dependency_specs.append(f"**{dep_name}** ({dep_desc}): {dep_value}")
                    else:
                        dependency_specs.append(f"**{dep_name}**: {dep_value}")
            
            if dependency_specs:
                depends_message = "\n".join([
                    "# Dimensions This Evaluation Must Consider",
                    "\nWhen evaluating the current dimension, you MUST take into account:",
                    "",
                    *dependency_specs,
                    "",
                    "Use these as authoritative constraints when analyzing the user's input."
                ])
                messages.append({
                    'role': 'system',
                    'content': depends_message
                })
        
        # 5. User message: Original query to analyze
        user_message = f"**Original Research Input:**\n{query}"
        messages.append({
            'role': 'user',
            'content': user_message
        })
        
        # 6. Conversation history: Alternating assistant/user messages
        for qa in self.conversation_history:
            # Assistant asks the question
            messages.append({
                'role': 'assistant',
                'content': qa['question']
            })
            # User provides the response
            messages.append({
                'role': 'user',
                'content': qa['response']
            })
        
        return messages
    
    def can_ask_followup(self) -> bool:
        """
        Check if follow-ups are allowed for this aspect.
        
        Note: This does NOT enforce max_follow_ups in web API (user controls pace).
        Only used by CLI batch mode to prevent infinite loops.
        """
        return self.refinement_aspect.allow_follow_up and (self.follow_up_count < self.refinement_aspect.max_follow_ups)

    def add_follow_up(self, question: str, response: str) -> None:
        """
        Adds a follow-up question/response pair to the history.
        
        Automatically extracts and stores the refined value from the response.
        """
        self.was_skipped = False
        self.conversation_history.append({
            "question": question,
            "response": response
        })
        # Extract and store value from response
        self.extract_and_store_value(response)
    
    def get_conversation_history_text(self) -> str:
        """
        Format follow-up history for use in prompts.
        """
        if not self.conversation_history:
            return "no previous follow-up questions."
        
        history_lines = []
        for i, qa in enumerate(self.conversation_history, start=0):
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
        latest_answer = self.normalized_value_as_str or ""
        
        # Get current refinement aspect value for display
        current_value = self.normalized_value
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

        base_prompt = self.refinement_aspect.get_evaluation_instructions_prompt(
            statement=original_query
        )

        sections = [follow_up_preamble, history_section, base_prompt]
        return "\n\n".join(section for section in sections if section)
    
@dataclass
class RefinementSession:
    """
    Represents an entire query refinement session.
    
    Tracks the original query and the multi-step refinement process through
    a list of QueryAspectRefiner objects, one per refinement aspect regardless of whether it needs refinement.
    """

    original_query: str
    steps: List[AspectRefinementState] = field(default_factory=list)
    synthesis_requested: bool = False
    
    @property
    def refinement_framework(self) -> List[RefinementAspect]:
        """Get the refinement framework from the steps."""
        return [step.refinement_aspect for step in self.steps]
    
    def add_step(
        self,
        refinement_aspect: RefinementAspect,
    ) -> AspectRefinementState:
        """
        Adds a new refinement step to the session for a refinement aspect.

        Args:
            refinement_aspect (RefinementAspect): The refinement aspect being refined.
        
        Returns:
            QueryAspectRefiner: The newly created query aspectrefiner.
        """
        step = AspectRefinementState(
            refinement_aspect=refinement_aspect,
            is_complete=False,
        )
        self.steps.append(step)
        return step
    
    def get_active_step(self) -> Optional[AspectRefinementState]:
        """Return the first step that still requires user attention."""

        for step in self.steps:
            if not step.is_complete or step.needs_review:
                return step

        return None
    
    def get_next_unrefined_aspect(self) -> Optional[AspectRefinementState]:
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
    
    def get_step_by_aspect_id(self, aspect_id: str) -> Optional[AspectRefinementState]:
        """
        Find a step by its refinement aspect ID.
        
        Args:
            aspect_id: The ID of the refinement aspect
            
        Returns:
            QueryAspectRefiner if found, None otherwise
        """
        for step in self.steps:
            if step.refinement_aspect.id == aspect_id:
                return step
        return None
    
    def get_dependency_context(self, target_refinement_aspect_id: str) -> Dict[str, Dict[str, Any]]:
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
            - type: The value type (string, object, array, etc.)
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

        context: Dict[str, Dict[str, Any]] = {}
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
            value_type = "string"
            
            # Get the refinement aspect value directly (single source of truth)
            raw_value = None
            
            # Skip entirely if aspect was skipped - no context provided
            if dep_step.was_skipped:
                logger.debug(
                    "Dependency '%s' was skipped - excluding from context for '%s'",
                    dep_id,
                    target_refinement_aspect_id,
                )
                continue
            
            if dep_step.normalized_value is not None:
                raw_value = dep_step.normalized_value
            elif dep_step.is_complete:
                # Aspect was clear in original query
                raw_value = f"[{aspect.aspect_name} is clear in original query: \"{self.original_query}\"]"
            
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
                    "has_refinement_aspect_value": step.normalized_value_as_str is not None,
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
            if not step.conversation_history:
                continue
                
            lines.append(f"[{step.refinement_aspect.aspect_name}]")
            lines.append("")
            
            for i, qa in enumerate(step.conversation_history, 1):
                interaction_type = "initial" if i == 1 else f"follow-up {i-1}"
                lines.append(f"  [{interaction_type}]")
                lines.append(f"  Q: {qa.get('question', '')}")
                if qa.get('response'):
                    lines.append(f"  A: {qa['response']}")
                lines.append("")  # Blank line
            
            if step.normalized_value_as_str:
                lines.append(f"  ✓ Final value: {step.normalized_value_as_str}")
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
        
        # Delegate to SessionCommands helper
        commands = SessionCommands(self)
        return commands.execute(cmd_result.command)
    
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
                    "follow_up_history": step.conversation_history,
                    # Completion status
                    "is_complete": step.is_complete,
                    "refinement_aspect_value": step.normalized_value_as_str,
                }
                for step in self.steps
            ],
        }
    


class QueryRefinementManager:
    async def run_followup_until_clear(
        self,
        session: RefinementSession,
        aspect_id: Optional[str] = None,
        max_rounds: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        Run follow-up analysis loop until aspect is complete or max rounds reached.
        
        **CLI/Batch Mode Only** - Auto-loops calling LLM multiple times.
        Web API should NOT use this - it should call get_analysis_prompts once per user answer.
        
        Uses unified prompt system for consistent handling of follow-up conversations.
        """
        import time
        from query_refinement_module.tracing import get_request_id, get_trace_id
        
        start_time = time.time()
        request_id = get_request_id() or "-"
        trace_id = get_trace_id() or "-"
        
        step = self._get_target_step(session, aspect_id)
        logger.info(
            "Starting follow-up analysis loop",
            extra={
                "request_id": request_id,
                "trace_id": trace_id,
                "aspect_id": aspect_id or "current",
                "max_rounds": max_rounds,
                "aspect_complete": step.is_complete,
            },
        )
        
        rounds = 0
        max_followups = max_rounds if max_rounds is not None else step.refinement_aspect.max_follow_ups

        if step.is_complete:
            return {
                "aspect_id": step.refinement_aspect.id,
                "aspect_name": step.refinement_aspect.aspect_name,
                "follow_up_history": step.conversation_history,
                "is_complete": step.is_complete,
                "final_value": step.normalized_value_as_str,
                "rounds": rounds,
            }

        while not step.is_complete and rounds < max_followups:
            try:
                # Use unified prompt system with followup mode
                result = await self.get_analysis_prompts(
                    session=session,
                    aspect_id=step.refinement_aspect.id,
                    mode='followup'
                )
                
                # Process the result and update step
                status = self.process_analysis_result(
                    session=session,
                    aspect_id=step.refinement_aspect.id,
                    result=result
                )
                
                rounds += 1
                
                # Log to follow-up history
                if status['complete']:
                    # Store final question and value in history
                    last_question = step.follow_up_question or step.refinement_aspect.aspect_name
                    step.add_follow_up(
                        question=last_question,
                        response=f"[Complete: {result.refinement_aspect_value}]"
                    )
                    break
                else:
                    # Store question for next round
                    # The last user response is already in follow_up_history from CLI/API
                    # Just update refinement_question for next iteration
                    step.follow_up_question = result.next_question
                    
                    if rounds >= max_followups:
                        # Reached max rounds without completion
                        step.is_complete = False
                        break
                        
            except ValueError as e:
                # LLM error - mark as complete with error
                logger.error(f"LLM error in followup for {step.refinement_aspect.id}: {e}")
                step.add_follow_up(
                    question=step.follow_up_question or step.refinement_aspect.aspect_name,
                    response=f"[Validation error: {e}]"
                )
                step.is_complete = True
                break

        duration_ms = (time.time() - start_time) * 1000
        logger.info(
            "Completed follow-up analysis loop",
            extra={
                "request_id": request_id,
                "trace_id": trace_id,
                "aspect_id": aspect_id or "current",
                "rounds_completed": rounds,
                "max_rounds": max_followups,
                "is_complete": step.is_complete,
                "duration_ms": round(duration_ms, 2),
            },
        )
        
        return {
            "aspect_id": step.refinement_aspect.id,
            "aspect_name": step.refinement_aspect.aspect_name,
            "follow_up_history": step.conversation_history,
            "is_complete": step.is_complete,
            "final_value": step.normalized_value_as_str,
            "rounds": rounds,
        }

    def _get_target_step(
        self,
        session: RefinementSession,
        aspect_id: Optional[str]
    ) -> AspectRefinementState:
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

     

    def __init__(
        self,
        llm_provider: LLMProviderInterface,
        tracing_provider: Optional[TracingProviderInterface] = None,
    ) -> None:
        self.llm_provider: LLMProviderInterface = llm_provider
        self.tracing_provider: TracingProviderInterface = tracing_provider or NoOpTracingProvider()
        self.trace_emitter: TraceEventEmitter = TraceEventEmitter(self.tracing_provider)
        
        logger.info(
            "QueryRefinementManager initialized with LLM provider: %s, Tracing Provider: %s",
            llm_provider.__class__.__name__,
            self.tracing_provider.__class__.__name__,
        )

    async def get_analysis_prompts(
        self,
        session: RefinementSession,
        aspect_id: str,
        mode: Literal['initial', 'followup'] = 'initial'
    ) -> DimensionEvaluationResponse:
        """Generate and execute analysis prompts for an aspect."""
        # Get aspect and step
        step = session.get_step_by_aspect_id(aspect_id)
        if not step:
            raise ValueError(f"No step found for aspect '{aspect_id}'")
        
        aspect = step.refinement_aspect
        
        # Build messages array
        dependency_context = session.get_dependency_context(aspect_id)
        messages = step.get_messages(
            query=session.original_query,
            dependency_context=dependency_context
        )
        
        # Call LLM with messages
        response_text, parsed_payload, is_error, error_message = await self._get_llm_response_with_validation(
            aspect=aspect,
            messages=messages
        )
        
        if is_error:
            raise ValueError(f"LLM error for aspect '{aspect_id}': {error_message}")
        
        if not parsed_payload:
            raise ValueError(f"No parsed payload from LLM for aspect '{aspect_id}'")
        
        # Add metadata to LLM response
        parsed_payload['context'] = mode
        parsed_payload['round'] = len(step.conversation_history) + 1
        
        # Create and validate response (Pydantic validators handle field validation)
        try:
            result = DimensionEvaluationResponse(**parsed_payload)
            return result
        except Exception as e:
            logger.error(f"Failed to create RefinementAnalysisResponse: {e}, payload: {parsed_payload}")
            raise ValueError(f"Invalid LLM response structure: {e}")

    def process_analysis_result(
        self,
        session: RefinementSession,
        aspect_id: str,
        result: DimensionEvaluationResponse
    ) -> Dict[str, Any]:
        """Process analysis result and update session step."""
        step = session.get_step_by_aspect_id(aspect_id)
        if not step:
            raise ValueError(f"No step found for aspect '{aspect_id}'")
        
        if result.is_complete:
            # Refinement complete - store final value
            step.normalized_value = result.refinement_aspect_value
            step.is_complete = True
            
            # Log the assembled value for debugging
            logger.info(
                f"Dimension complete for '{step.refinement_aspect.aspect_name}' | "
                f"Assembled value: {result.refinement_aspect_value}"
            )
            
            return {
                'complete': True,
                'aspect_id': aspect_id,
                'aspect_name': step.refinement_aspect.aspect_name,
                'refinement_aspect_value': result.refinement_aspect_value,
                'reasoning': result.reasoning
            }
        else:
            # Needs follow-up - store question
            step.follow_up_question = result.next_question
            step.is_complete = False
            
            return {
                'complete': False,
                'aspect_id': aspect_id,
                'aspect_name': step.refinement_aspect.aspect_name,
                'next_question': result.next_question,
                'reasoning': result.reasoning,
                'round': result.round
            }

    def initialize_sequential(
        self,
        original_query: str,
        refinement_framework: List[RefinementAspect],
    ) -> RefinementSession:
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
            session = RefinementSession(original_query=original_query)
            
            # Add all aspects as steps WITHOUT running analysis
            for aspect in refinement_framework:
                step = session.add_step(aspect)
                # Mark as incomplete and ready for refinement
                step.is_complete = False
                step.reasoning = None
                step.follow_up_question = None
                
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

    def ensure_step_is_ready(
        self,
        session: RefinementSession,
        step: AspectRefinementState,
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
        session: RefinementSession,
        step: AspectRefinementState,
    ) -> bool:
        aspect = step.refinement_aspect

        if not aspect.depends_on:
            return False

        if step.conversation_history:
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

        # In v2.0, no analyzer - dependencies are handled via sequential processing
        logger.debug(
            "Skipping re-analysis for dependent aspect '%s' (sequential mode in v2.0)",
            aspect.id,
        )
        return False

    async def process_next_step(self, session: RefinementSession) -> Optional[Dict[str, Any]]:
        """Process the next ready refinement step."""
        with self.tracing_provider.trace_operation("process_next_step"):
            # Find next ready step
            step = self._find_next_ready_step(session)
            
            if step is None:
                return None
            
            # Execute step
            return await self._execute_step(session, step)

    def _find_next_ready_step(
        self,
        session: RefinementSession
    ) -> Optional[AspectRefinementState]:
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
                return None

            if self.ensure_step_is_ready(session, step):
                return step

    async def _execute_step(
        self,
        session: RefinementSession,
        step: AspectRefinementState
    ) -> Dict[str, Any]:
        """Execute a single refinement step."""
        aspect = step.refinement_aspect
        dependency_context = session.get_dependency_context(aspect.id)
        
        # Get messages array for LLM
        messages = step.get_messages(
            query=session.original_query,
            dependency_context=dependency_context
        )
        
        response_text, parsed_payload, is_error, error_message = await self._get_llm_response_with_validation(
            aspect=aspect,
            messages=messages
        )
        
        # Handle error or success
        if is_error:
            return self._handle_step_error(step, aspect, error_message)
        
        return self._handle_step_success(step, aspect, response_text, parsed_payload)

    def _handle_step_error(
        self,
        step: AspectRefinementState,
        aspect: RefinementAspect,
        error_message: Optional[str]
    ) -> Dict[str, Any]:
        """
        Handle step execution error by recording failure and marking complete.
        
        Returns:
            Dict with error response.
        """
        failure_response = f"[Validation error: {error_message}]" if error_message else "[Validation error]"
        question_text = step.follow_up_question or aspect.aspect_name
        
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
        step: AspectRefinementState,
        aspect: RefinementAspect,
        response_text: str,
        parsed_payload: Optional[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """
        Handle successful step execution by storing response and marking complete.
        
        Returns:
            Dict with successful response.
        """
        question_text = step.follow_up_question or aspect.aspect_name
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

    async def _get_llm_response_with_validation(
        self,
        aspect: RefinementAspect,
        messages: Optional[List[Dict[str, str]]] = None,
        system_prompt: Optional[str] = None,
        user_prompt: Optional[str] = None,
    ) -> tuple[str, Optional[Dict[str, Any]], bool, Optional[str]]:
        """
        Call the LLM asynchronously with structured response validation.
        
        With structured outputs (response_format), the LLM provider guarantees
        valid JSON responses, eliminating the need for retry logic.
        
        Args:
            aspect: The refinement aspect being evaluated
            messages: Structured messages array (preferred)
            system_prompt: Legacy system prompt (deprecated, use messages)
            user_prompt: Legacy user prompt (deprecated, use messages)

        Returns:
            Tuple of (normalized_response_text, parsed_payload, is_error, error_message)
        """
        self.trace_emitter.emit(
            "llm_validation_start",
            metadata={
                "aspect_id": aspect.id,
            }
        )

        # Call LLM with structured outputs
        response_text, llm_error = await self._call_llm(
            aspect=aspect,
            messages=messages,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            attempt_number=1,
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
            attempt_number=1,
        )
        
        if validation_result.is_valid:
            result_text = validation_result.normalized_text or response_text or ""
            return result_text, validation_result.parsed_payload, False, None
        
        # Validation failed (should be rare with structured outputs)
        return response_text, validation_result.parsed_payload, True, validation_result.error_message

    async def _call_llm(
        self,
        aspect: RefinementAspect,
        messages: Optional[List[Dict[str, str]]] = None,
        system_prompt: Optional[str] = None,
        user_prompt: Optional[str] = None,
        attempt_number: int = 1,
    ) -> tuple[str, Optional[str]]:
        """
        Call the LLM provider with structured outputs.
        
        Args:
            aspect: The refinement aspect being evaluated
            messages: Structured messages array (preferred)
            system_prompt: Legacy system prompt (deprecated, use messages)
            user_prompt: Legacy user prompt (deprecated, use messages)
            attempt_number: Attempt number for logging
            
        Returns:
            Tuple of (response_text, error_message)
        """
        try:
            # Use structured outputs for guaranteed valid responses
            import time
            call_start = time.time()
            
            # Call LLM with messages or legacy prompts
            if messages:
                result = await self.llm_provider.complete_async(
                    messages=messages,
                    response_format=DimensionEvaluationResponse,  # ✨ Structured output
                    cache_system_prompt=True  # System prompts are static per-aspect
                )
            else:
                # Legacy path for backwards compatibility
                if not system_prompt or not user_prompt:
                    raise ValueError("Either messages or both system_prompt and user_prompt must be provided")
                result = await self.llm_provider.complete_async(
                    system_prompt=system_prompt,
                    user_prompt=user_prompt,
                    response_format=DimensionEvaluationResponse,  # ✨ Structured output
                    cache_system_prompt=True  # System prompts are static per-aspect
                )
            
            call_duration = (time.time() - call_start) * 1000
            
            # Check if response is already parsed (structured output)
            if isinstance(result.context, DimensionEvaluationResponse):
                # Success! LLM provider returned structured output
                logger.info(
                    "Received structured output for aspect '%s' in %.2fms",
                    aspect.id,
                    call_duration
                )
                # Convert to dict for downstream processing
                response_dict = result.context.model_dump()
                response_text = json.dumps(response_dict)
                return response_text, None
            
            # Fallback: treat as text response
            response_text = (result.context or "").strip()
            
            # Log LLM performance and caching info
            logger.info(f"LLM call completed in {call_duration:.2f}ms for aspect '{aspect.id}'")
            
            # Check if response metadata indicates cache hit (Anthropic-specific)
            if hasattr(result, 'usage') and result.usage:
                usage = result.usage if hasattr(result.usage, '__dict__') else {}
                cache_hit = getattr(usage, 'cache_read_input_tokens', 0) > 0 if hasattr(usage, '__dict__') else False
                if cache_hit:
                    logger.info(f"  -> Cache HIT: {getattr(usage, 'cache_read_input_tokens', 0)} tokens read from cache")
                else:
                    logger.info(f"  -> Cache MISS: System prompt cached for future requests")
            
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
                    "is_complete": parsed_payload.get("is_complete", False),
                    "has_refinement_value": bool(parsed_payload.get("refinement_aspect_value")),
                    "has_next_question": bool(parsed_payload.get("next_question")),
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

    def _gather_refinement_details(
        self, session: RefinementSession
    ) -> tuple[List[tuple[str, str]], List[tuple[str, str]]]:
        """Collect refinement clarifications and baseline summaries for synthesis.
        
        Uses refinement_aspect_value as single source of truth for synthesized values.
        """

        clarifications: List[tuple[str, str]] = []
        baseline_summaries: List[tuple[str, str]] = []

        for step in session.steps:
            if step.was_skipped:
                continue
            
            # Use refinement_aspect_value if available (single source of truth)
            if step.normalized_value is not None:
                # Convert to string representation
                if isinstance(step.normalized_value, (dict, list)):
                    summary = json.dumps(step.normalized_value, ensure_ascii=False)
                else:
                    summary = str(step.normalized_value)
                
                summary = summary.strip()
                if summary:
                    if step.conversation_history:
                        # Had follow-ups, so this is a refined/synthesized value
                        clarifications.append((step.refinement_aspect.aspect_name, summary))
                    else:
                        # No follow-ups, was clear in original query
                        baseline_summaries.append((step.refinement_aspect.aspect_name, summary))
                    continue
            
            # Fallback: needs_refinement_rationale (explanation why aspect was clear)
            if step.is_complete:
                rationale = (step.reasoning or "").strip()
                if rationale:
                    baseline_summaries.append((step.refinement_aspect.aspect_name, rationale))

        return clarifications, baseline_summaries

    async def synthesize_refined_query(
        self,
        session: RefinementSession,
        *,
        model: Optional[str] = None,
        temperature: float = 0.2,
        max_tokens: int = 512,
        additional_guidance: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Generate a refined query by combining the original query with clarifications.

        Args:
            session: Active refinement session containing user-provided clarifications.
            model: Optional model override for the synthesis call.
            temperature: Sampling temperature for the completion (default 0.2).
            max_tokens: Maximum tokens for the synthesis response (default 512).
            additional_guidance: Optional extra instruction appended to the prompt.

        Returns:
            Dictionary containing the refined query, whether the LLM was invoked,
            and supporting metadata.
        """
        import time
        from query_refinement_module.tracing import get_request_id, get_trace_id
        
        start_time = time.time()
        request_id = get_request_id() or "-"
        trace_id = get_trace_id() or "-"
        
        logger.info(
            "Starting query synthesis",
            extra={
                "request_id": request_id,
                "trace_id": trace_id,
                "model": model,
                "temperature": temperature,
                "max_tokens": max_tokens,
                "has_additional_guidance": additional_guidance is not None,
            },
        )

        clarifications, baseline_summaries = self._gather_refinement_details(session)

        # Build refinement_aspect_values map for structured consumption
        refinement_aspect_values = {}
        for step in session.steps:
            aspect_id = step.refinement_aspect.id
            # Check for non-empty value (None or empty string are considered "no value")
            if step.normalized_value is not None and step.normalized_value != "":
                # Use native value (dict/list/str/etc) - either extracted from original or from user dialogue
                refinement_aspect_values[aspect_id] = step.normalized_value
            elif step.was_skipped or (step.is_complete and not step.normalized_value):
                # Skipped explicitly (/skip) or completed without value (/done, or auto-complete without extraction)
                refinement_aspect_values[aspect_id] = "[SKIPPED]"
            # else: dimension incomplete - omit from synthesis (shouldn't happen for complete sessions)

        if not clarifications and not baseline_summaries:
            duration_ms = (time.time() - start_time) * 1000
            logger.info(
                "Skipping LLM synthesis: no refinement clarifications or summaries recorded.",
                extra={
                    "request_id": request_id,
                    "trace_id": trace_id,
                    "duration_ms": round(duration_ms, 2),
                },
            )
            return {
                "refined_query": session.original_query,
                "used_llm": False,
                "clarifications": [],
                "baseline_summaries": [],
                "refinement_aspect_values": refinement_aspect_values,
                "metadata": {
                    "reason": "no_clarifications",
                },
            }

        # Build prompts using SynthesisPromptBuilder for structured output
        aspects = [step.refinement_aspect for step in session.steps]
        prompt_builder = SynthesisPromptBuilder()
        
        user_prompt = prompt_builder.build_synthesis_prompt(
            original_input=session.original_query,
            aspectID_value_mapping=refinement_aspect_values,
            aspect_list=aspects,
        )
        
        if additional_guidance:
            user_prompt = f"{user_prompt}\n\nADDITIONAL GUIDANCE:\n{additional_guidance.strip()}"
        
        system_prompt = prompt_builder.get_system_prompt()

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
        
        # Try to use structured output for providers that support it
        # This works with OpenAI gpt-4o and later, Anthropic Claude Sonnet 4+
        # For other providers, the prompt already instructs to return JSON
        try:
            # Use basic JSON object format (more widely supported)
            completion_kwargs["response_format"] = {"type": "json_object"}
        except Exception:
            # Provider doesn't support response_format, rely on prompt instructions
            pass

        try:
            result = await self.llm_provider.complete_async(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                model=model,
                cache_system_prompt=True,  # Synthesis system prompt is static
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

        # Try to parse as structured JSON response with robust error handling
        synthesis_response = None
        try:
            # Strip markdown code fences if present (some models add these)
            cleaned_text = refined_query
            if cleaned_text.startswith("```"):
                lines = cleaned_text.splitlines()
                if len(lines) >= 2 and lines[0].startswith("```"):
                    # Drop opening fence and optional closing fence
                    body = lines[1:]
                    if body and body[-1].startswith("```"):
                        body = body[:-1]
                    cleaned_text = "\n".join(body)
            
            # Try to find JSON if it's embedded in text
            if not cleaned_text.startswith("{"):
                # Look for JSON object start
                json_start = cleaned_text.find("{")
                if json_start != -1:
                    cleaned_text = cleaned_text[json_start:]
                    # Find matching closing brace
                    brace_count = 0
                    for i, char in enumerate(cleaned_text):
                        if char == "{":
                            brace_count += 1
                        elif char == "}":
                            brace_count -= 1
                            if brace_count == 0:
                                cleaned_text = cleaned_text[:i+1]
                                break
            
            # Log the full raw response before JSON parsing to debug malformed JSON
            logger.info(
                "Raw synthesis LLM response | Length: %d chars | First 500 chars: %s",
                len(cleaned_text),
                cleaned_text[:500]
            )
            logger.debug("Full synthesis LLM response:\n%s", cleaned_text)
            
            # Parse JSON
            response_data = json.loads(cleaned_text)
            
            # Validate with Pydantic model
            synthesis_response = QueryRefinementResponse(**response_data)
            refined_query = synthesis_response.synthesized_statement
            
            logger.info(
                "Successfully parsed and validated structured synthesis response"
            )
            self.trace_emitter.emit(
                "synthesis_response_parsed",
                metadata={
                    "has_structured_response": True,
                    "response_length": len(refined_query),
                    "has_detail_values": bool(synthesis_response.detail_values),
                    "detail_values_count": len(synthesis_response.detail_values) if synthesis_response.detail_values else 0,
                }
            )
        except json.JSONDecodeError as parse_error:
            # JSON parsing failed - log detailed error
            logger.warning(
                "JSON parsing failed: %s at line %d column %d (char %d)",
                parse_error.msg,
                parse_error.lineno,
                parse_error.colno,
                parse_error.pos
            )
            self.trace_emitter.emit(
                "synthesis_response_parse_failed",
                level="warning",
                metadata={
                    "error_type": "JSONDecodeError",
                    "error_message": str(parse_error),
                    "error_line": parse_error.lineno,
                    "error_column": parse_error.colno,
                    "response_preview": cleaned_text[:200] if cleaned_text else "<empty>",
                    "response_length": len(cleaned_text) if cleaned_text else 0,
                }
            )
            # Use raw response as fallback
            if not refined_query or refined_query == cleaned_text:
                logger.warning("Using original query as fallback due to parsing failure")
                refined_query = session.original_query
        except (ValueError, TypeError) as validation_error:
            # Pydantic validation failed - JSON structure doesn't match schema
            logger.warning(
                "Response validation failed: %s",
                validation_error
            )
            self.trace_emitter.emit(
                "synthesis_response_parse_failed",
                level="warning",
                metadata={
                    "error_type": type(validation_error).__name__,
                    "error_message": str(validation_error),
                    "response_preview": cleaned_text[:200] if cleaned_text else "<empty>",
                    "response_length": len(cleaned_text) if cleaned_text else 0,
                }
            )
            if not refined_query:
                logger.warning("LLM synthesis returned empty response; using original query")
                refined_query = session.original_query

        self.trace_emitter.emit(
            "query_synthesis_complete",
            metadata={
                "clarification_count": len(clarifications),
                "baseline_count": len(baseline_summaries),
                "response_length": len(refined_query),
                "structured_response": synthesis_response is not None,
            },
        )

        duration_ms = (time.time() - start_time) * 1000
        logger.info(
            "Completed query synthesis",
            extra={
                "request_id": request_id,
                "trace_id": trace_id,
                "duration_ms": round(duration_ms, 2),
                "used_llm": True,
                "clarification_count": len(clarifications),
                "baseline_count": len(baseline_summaries),
                "response_length": len(refined_query),
                "structured_response": synthesis_response is not None,
                "prompt_tokens": result.metadata.get("prompt_tokens", 0) if result.metadata else 0,
                "completion_tokens": result.metadata.get("completion_tokens", 0) if result.metadata else 0,
            },
        )

        result_dict = {
            "refined_query": refined_query,
            "used_llm": True,
            "clarifications": clarifications,
            "baseline_summaries": baseline_summaries,
            "refinement_aspect_values": refinement_aspect_values,
            "metadata": result.metadata,
        }
        
        # Include structured response fields if available
        if synthesis_response:
            result_dict["detail_values"] = synthesis_response.detail_values
            result_dict["search_optimized"] = synthesis_response.search_optimized
            result_dict["search_filters"] = synthesis_response.search_filters
            result_dict["terminology"] = synthesis_response.terminology
            result_dict["synthesized_statement"] = synthesis_response.synthesized_statement

        return result_dict

    def get_initialization_summary(self, session: RefinementSession) -> Dict[str, Any]:
        """
        Get a user-friendly summary of the initialization analysis.

        Use this after initialize() to present to the user what needs refinement.

        Returns:
            Dictionary with:
            - is_complete: bool - whether all aspects are clear (no refinement needed)
            - total_aspects: int - total number of aspects
            - incomplete_count: int - count of incomplete aspects
            - complete_count: int - count of complete aspects
            - aspects: list of dicts with details per aspect:
              - id: aspect identifier
              - name: aspect name
              - is_complete: bool - whether aspect is complete
              - description: aspect description
              - reasoning: explanation of why refinement is needed (for incomplete aspects)
              - next_question: suggested question to ask the user (for incomplete aspects)
        """
        incomplete_aspects = []
        complete_aspects = []
        
        for step in session.steps:
            aspect_info = {
                "id": step.refinement_aspect.id,
                "name": step.refinement_aspect.aspect_name,
                "description": step.refinement_aspect.aspect_description,
                "is_complete": step.is_complete
            }
            
            # Add analysis details for aspects that are incomplete
            if not step.is_complete:
                if step.reasoning:
                    aspect_info["reasoning"] = step.reasoning
                if step.follow_up_question:
                    aspect_info["next_question"] = step.follow_up_question
            
            if step.is_complete:
                complete_aspects.append(aspect_info)
            else:
                incomplete_aspects.append(aspect_info)
        
        return {
            "is_complete": session.is_complete(),
            "total_aspects": len(session.steps),
            "incomplete_count": len(incomplete_aspects),
            "complete_count": len(complete_aspects),
            "aspects": incomplete_aspects + complete_aspects
        }