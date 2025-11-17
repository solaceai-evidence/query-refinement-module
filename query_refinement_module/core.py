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
- /synthesize            - Finish session immediately using current answers
- /finish                - Complete session with current refinements

Information:
- /status                - Show session progress
- /help                  - Show available commands
- /steps                 - List all refinement steps

These commands are detected via is_user_command() and processed via parse_user_command().
"""

import json
import logging
import textwrap
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional

from .interfaces import (
    LLMProviderInterface,
    TracingProviderInterface,
    QueryAnalyzerInterface,
)
from .providers import NoOpTracingProvider, TraceEventEmitter
from .schema import RefinementAspect

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
    FINISH = "finish"
    SYNTHESIZE = "synthesize"
    
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
    "finish": UserCommand.FINISH,
    "status": UserCommand.STATUS,
    "help": UserCommand.HELP,
    "steps": UserCommand.STEPS,
    "synthesize": UserCommand.SYNTHESIZE,
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
    /synthesize           Finish session immediately using current answers
    /finish               Complete session with current refinements

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
    # Contains: reason (why refinement needed/not), suggested_question (what to ask)
    analysis_reason: Optional[str] = None
    analysis_suggested_question: Optional[str] = None
    initial_summary: Optional[str] = None
    
    @property
    def follow_up_count(self) -> int:
        """Number of follow-up rounds completed."""
        return len(self.follow_up_history)
    
    @property
    def final_response(self) -> Optional[str]:
        """Return the last response recorded for this aspect, if any."""
        if not self.follow_up_history:
            return None
        return self.follow_up_history[-1]['response']

    def get_system_prompt(self) -> str:
        """
        Get the system prompt for this refinement aspect.
        
        Returns:
            System prompt string (from refinement aspect or default)
        """
        return self.refinement_aspect.get_system_prompt()
    
    def get_prompts(self, query: str, dependency_context: Optional[Dict[str, str]] = None, **kwargs) -> tuple[str, str]:
        """
        Get both system and user prompts for this refinement aspect with dependency context.
        
        Args:
            query: The query to analyze
            dependency_context: Mapping of dependency IDs to dictionaries containing
                human-readable names and values used for prompt context
            **kwargs: Additional context for prompt formatting
            
        Returns:
            Tuple of (system_prompt, analysis_prompt)
        """
        system_prompt = self.refinement_aspect.get_system_prompt()
        
        # Build user prompt with dependency context
        analysis_prompt_context = []
        
        # Add dependency context if provided
        if dependency_context and self.refinement_aspect.depends_on:
            missing_deps: List[str] = []
            context_lines: List[str] = []

            for dep_id in self.refinement_aspect.depends_on:
                entry = dependency_context.get(dep_id)
                if entry and entry.get("value"):
                    dep_name = entry.get("name") or dep_id.replace("_", " ").title()
                    context_lines.append(f"- {dep_name}: {entry['value']}")
                else:
                    missing_deps.append(dep_id)

            if context_lines:
                analysis_prompt_context.append(
                    "Previous refinements (use these details when evaluating this aspect):"
                )
                analysis_prompt_context.extend(context_lines)
                analysis_prompt_context.append("")  # Blank line

            if missing_deps:
                logger.warning(
                    "refinement aspect '%s' depends on %s but they have no values. Continuing without that context.",
                    self.refinement_aspect.id,
                    missing_deps,
                )
        
        # Add main analysis prompt
        analysis_prompt_context.append(self.refinement_aspect.get_user_prompt(query=query, **kwargs))
        
        return system_prompt, "\n".join(analysis_prompt_context)
    
    def can_ask_followup(self) -> bool:
        """
        Determines if a follow-up question can be asked based on the refinement aspect's max_follow_ups.
        """
        return self.refinement_aspect.allow_follow_up and (self.follow_up_count < self.refinement_aspect.max_follow_ups)

    def add_follow_up(self, question: str, response: str):
        """
        Adds a follow-up question/response pair to the history.
        
        The last response in history becomes the refined_value.
        """
        self.was_skipped = False
        self.follow_up_history.append({
            "question": question,
            "response": response
        })
    
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
        latest_answer = self.final_response or ""

        follow_up_preamble = textwrap.dedent(
            f"""
            FOLLOW-UP CONTEXT:
            You are evaluating whether additional clarification is required for the
            refinement aspect "{self.refinement_aspect.name}". This is a follow-up
            turn, so review the conversation history carefully before deciding if a
            new question is needed. Only request information that is still missing.
            If the aspect is now sufficiently specified, respond according to the
            schema with ``needs_refinement`` set to ``false`` and explain why no
            further follow-up is necessary.
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

        base_prompt = self.refinement_aspect.get_user_prompt(
            query=original_query,
            include_examples=include_examples,
            include_user_answer=True,
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
        """
        Returns the current active refinement step (first incomplete or needs review).
        """
        for step in self.steps:
            if not step.is_complete or step.needs_review:
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
            Dictionary mapping dependency IDs to metadata containing the dependency name and value
        """
        step_index = {step.refinement_aspect.id: step for step in self.steps}
        target_step = step_index.get(target_refinement_aspect_id)
        if not target_step:
            logger.warning(
                "Requested dependency context for unknown refinement aspect '%s'",
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
                logger.warning(
                    "Refinement aspect '%s' declares dependency on missing aspect '%s'",
                    target_refinement_aspect_id,
                    dep_id,
                )
                continue

            if dep_step.final_response:
                context[dep_id] = {
                    "name": dep_step.refinement_aspect.name,
                    "value": dep_step.final_response,
                }
            elif dep_step.is_complete and not dep_step.was_skipped:
                context[dep_id] = {
                    "name": dep_step.refinement_aspect.name,
                    "value": (
                        f"[{dep_step.refinement_aspect.name} is clear in original query: \"{self.original_query}\"]"
                    ),
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
                    "refinement_aspect": step.refinement_aspect.name,
                    "is_complete": step.is_complete,
                    "needs_review": step.needs_review,
                    "follow_up_count": step.follow_up_count,
                    "has_refined_value": step.final_response is not None,
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
        lines = [f"Original Query: {self.original_query}", ""]
        
        for step in self.steps:
            if not step.follow_up_history:
                continue
                
            lines.append(f"[{step.refinement_aspect.name}]")
            
            for i, qa in enumerate(step.follow_up_history, 1):
                interaction_type = "initial" if i == 1 else f"follow-up {i-1}"
                lines.append(f"  [{interaction_type}]")
                lines.append(f"  Q: {qa.get('question', '')}")
                if qa.get('response'):
                    lines.append(f"  A: {qa['response']}")
                lines.append("")  # Blank line
            
            if step.final_response:
                lines.append(f"  ✓ Final value: {step.final_response}")
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
            UserCommand.FINISH: self._finish_current,
            UserCommand.STATUS: self._get_status,
            UserCommand.STEPS: self._list_steps,
            UserCommand.SYNTHESIZE: self._request_synthesis,
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
                invalidated.append(step.refinement_aspect.name)
                
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
        
        message = f"Returned to step {active_idx}: {prev_step.refinement_aspect.name}"
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
                if self.steps[i].refinement_aspect.name not in invalidated:
                    invalidated.append(self.steps[i].refinement_aspect.name)
        
        message = f"Jumped to step {step_number}: {target_step.refinement_aspect.name}"
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
        """Skip the current refinement aspect without providing a value."""
        active = self.get_active_step()
        if not active:
            return {"success": False, "message": "No active step to skip"}
        
        # Mark as complete without adding to history (no refined value)
        active.is_complete = True
        active.was_skipped = True
        
        return {
            "success": True,
            "message": f"Skipped refinement aspect: {active.refinement_aspect.name}",
            "step": active,
        }
    
    def _finish_current(self) -> Dict[str, Any]:
        """Finish the current step, accepting the current refined value."""
        active = self.get_active_step()
        if not active:
            return {"success": False, "message": "No active step to finish"}
        if not active.final_response:
            return {
                "success": False,
                "message": "Cannot finish: no value has been provided yet. Provide an answer or use /skip.",
            }
        
        # Mark as complete and clear review flag
        active.is_complete = True
        active.needs_review = False
        active.was_skipped = False
        
        return {
            "success": True,
            "message": f"Completed refinement aspect: {active.refinement_aspect.name}",
            "step": active,
        }

    def _request_synthesis(self) -> Dict[str, Any]:
        """Request immediate synthesis using currently captured clarifications."""
        self.synthesis_requested = True
        return {
            "success": True,
            "message": "Generating refined query with current clarifications.",
            "synthesize": True,
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
            status_lines.append(f"  Current: Step {active_idx} - {active.refinement_aspect.name}{status_tag}")
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
            lines.append(f"  {i}. [{status}] {step.refinement_aspect.name}{followups}")
        
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
            "refinement_aspects": [aspect.name for aspect in self.refinement_framework],
            "steps": [
                {
                    "refinement_aspect_id": step.refinement_aspect.id,
                    "refinement_aspect_name": step.refinement_aspect.name,
                    "refinement_aspect_description": step.refinement_aspect.description,
                    # Multi-turn conversation
                    "follow_up_history": step.follow_up_history,
                    # Completion status
                    "is_complete": step.is_complete,
                    "refined_value": step.final_response,
                }
                for step in self.steps
            ],
        }
    

class QueryRefinementManager:
    """
    Orchestrates the multi-step query refinement process using provided LLM, tracing, and query analysis interfaces.

    Refinement logic is domain-agnostic and driven by the provided schema refinement aspects.
    All methods work with RefinementSession objects, allowing external management of state and persistence (files/Redis/databases).

    Key responsibilities:
    - Detecting wich refinement aspects need refinement based on the initial query
    - Generating questions for each refinement aspect using the query analyzer
    - Processing user responses and managing follow-up questions
    - Synthesizing the final refined query
    - Maintaining conversation history and session state
    - Tracing and logging interactions for debugging and analysis

    Attributes:
        llm_provider (LLMProviderInterface): Interface for interacting with the LLM.
        tracing_provider (TracingProviderInterface): Interface for tracing and logging.
        query_analyzer (QueryAnalyzerInterface): Interface for analyzing queries against schemas.
    
    Args:
        llm_provider: LLM provider for question generation and synthesis
        query_analyzer: Analyzer for detecting missing refinement aspects
                    (if None, will assume all refinement aspects need refinement)
        tracing_provider: Tracing provider for observability
            (if None, will use no-op implementation)
    """

    def __init__(
        self,
        llm_provider: LLMProviderInterface,
        query_analyzer: QueryAnalyzerInterface,
        tracing_provider: Optional[TracingProviderInterface] = None,
    ):
        """Initialize the manager with injected dependencies

        Args:
            llm_provider (LLMProviderInterface): LLM provider for question generation and synthesis
            query_analyzer (QueryAnalyzerInterface): Analyzer for detecting missing refinement aspects
                    (if None, will assume all refinement aspects need refinement)
            tracing_provider (TracingProviderInterface): Tracing provider for observability
                    (if None, will use no-op implementation)
        """
        self.llm_provider = llm_provider
        self.query_analyzer = query_analyzer
        
        # Use no-op tracing provider if none provided
        self.tracing_provider = tracing_provider or NoOpTracingProvider()
        self.trace_emitter = TraceEventEmitter(self.tracing_provider)
        
        logger.info("QueryRefinementManager initialized with "
                    "LLM provider: %s, Query Analyzer: %s, Tracing Provider: %s",
                    llm_provider.__class__.__name__, 
                    query_analyzer.__class__.__name__ if query_analyzer else "None", 
                    self.tracing_provider.__class__.__name__)

        # Maximum number of retries when enforcing structured response validation
        self.validation_max_retries = 2

        self.trace_emitter.emit(
            "manager_initialized",
            metadata={
                "llm_provider": llm_provider.__class__.__name__,
                "query_analyzer": query_analyzer.__class__.__name__ if query_analyzer else "None",
            }
        )

    def initialize(
        self,
        original_query: str,
        refinement_framework: List[RefinementAspect],
    ) -> QueryRefinementSession:
        """
        Initialize a new refinement session for the given query and refinement aspects.

        This method performs dependency-aware sequential analysis:
        1. Creates a new session with the original query
        2. For EACH aspect in dependency order:
           a. Gets dependency context from previously analyzed aspects
           b. Analyzes the aspect (with context) to determine if refinement is needed
           c. Marks aspect as complete (clear) or incomplete (needs refinement and adds the LLM suggested query and explanation)
        3. Returns the session with analysis complete

        After initialization:
        - If session.is_complete() == True: All aspects are clear, refinement not needed
        - If session.is_complete() == False: Use process_next_step() to refine incomplete aspects
        - Use session.get_step_summary() to see which aspects need refinement and why

        This approach enables:
        - Dependency-aware analysis (later aspects see earlier results)
        - Complete initialization picture (API can show "3 aspects need work")
        - More accurate determination of what needs refinement

        Args:
            original_query (str): The original query to refine.
            refinement_framework (List[RefinementAspect]): The refinement aspects to consider.

        Returns:
            QueryRefinementSession: Session with analysis complete, ready for refinement.
        """
        with self.tracing_provider.trace_operation("initialize_refinement_session") as trace:
            if hasattr(trace, 'add_attribute'):
                trace.add_attribute("original_query", original_query)
                trace.add_attribute("num_refinement_aspects", len(refinement_framework))

            logger.info("Initializing refinement session for query: %s", original_query)
            logger.debug("Refinement framework aspects: %s",
                         [aspect.name for aspect in refinement_framework])
            
            # Create a new session
            session = QueryRefinementSession(
                original_query=original_query,
            )

            # Analyze each aspect sequentially in dependency order
            # This allows later aspects to be analyzed with context from earlier ones
            aspects_needing_refinement_count = 0
            
            for aspect in refinement_framework:
                # Add the aspect as a step
                step = session.add_step(aspect)
                
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
                analysis_result = self.query_analyzer.analyze_aspect(
                    query=original_query,
                    aspect=aspect,
                    dependency_context=analyzer_context,
                    llm_provider=self.llm_provider
                )

                self.trace_emitter.emit(
                    "aspect_analysis_complete",
                    metadata={
                        "aspect_id": aspect.id,
                        "needs_refinement": analysis_result.needs_refinement,
                    }
                )
                
                # Store the analysis results (from LLM's structured output)
                step.analysis_reason = analysis_result.explanation
                step.analysis_suggested_question = analysis_result.suggested_question
                
                if analysis_result.needs_refinement:
                    # Aspect needs refinement - leave incomplete for process_next_step()
                    step.is_complete = False
                    aspects_needing_refinement_count += 1
                    logger.debug("Aspect %s needs refinement: %s", aspect.name, analysis_result.explanation)
                else:
                    # Aspect is already clear - mark complete, original query has the info
                    step.is_complete = True
                    summary_text = (
                        analysis_result.explanation
                        or step.refinement_aspect.description
                        or f"Aspect '{step.refinement_aspect.name}' is sufficiently specified in the original query."
                    )
                    step.initial_summary = summary_text.strip()
                    logger.debug("Aspect %s is already clear in original query", aspect.name)
            
            logger.info(
                "Session initialized with %d total steps (%d need refinement, %d already clear)", 
                len(session.steps), 
                aspects_needing_refinement_count,
                len(session.steps) - aspects_needing_refinement_count
            )

            self.trace_emitter.emit(
                "session_initialized",
                metadata={
                    "total_steps": len(session.steps),
                    "needs_refinement": aspects_needing_refinement_count,
                    "already_clear": len(session.steps) - aspects_needing_refinement_count,
                }
            )
            
            return session

    @staticmethod
    def _dependencies_ready(
        candidate: QueryAspectRefiner,
        step_lookup: Dict[str, QueryAspectRefiner],
    ) -> bool:
        """Check whether all declared dependencies for a step are satisfied."""
        dependencies = candidate.refinement_aspect.depends_on or []
        if not dependencies:
            return True

        pending: List[str] = []

        for dep_id in dependencies:
            dep_step = step_lookup.get(dep_id)
            if not dep_step:
                logger.warning(
                    "Aspect %s declares dependency on %s but it's not in the session",
                    candidate.refinement_aspect.id,
                    dep_id,
                )
                return False

            if not dep_step.is_complete and not dep_step.final_response:
                pending.append(dep_id)

        if pending:
            logger.debug(
                "Aspect %s waiting on dependencies %s",
                candidate.refinement_aspect.id,
                pending,
            )
            return False

        return True

    def process_next_step(self, session: QueryRefinementSession) -> Optional[Dict[str, Any]]:
        """
        Process the next incomplete refinement step with exactly ONE LLM interaction.

        Selects the next step whose dependencies are satisfied, builds dependency context
        from completed steps (using refined values or original query references), calls
        the LLM once, and stores the response.

        Args:
            session: The refinement session to process

        Returns:
            Dict with {"aspect_id", "aspect_name", "question", "response"} when a step was
            processed, or None if there are no remaining steps.
        """
        with self.tracing_provider.trace_operation("process_next_step"):
            # Find the next step whose dependencies are satisfied (dependency-aware ordering)
            step: Optional[QueryAspectRefiner] = None
            step_lookup = {candidate.refinement_aspect.id: candidate for candidate in session.steps}

            for candidate in session.steps:
                if candidate.is_complete and not candidate.needs_review:
                    continue

                if self._dependencies_ready(candidate, step_lookup):
                    step = candidate
                    break

            if step is None:
                logger.debug("No active step with satisfied dependencies to process")
                self.trace_emitter.emit(
                    "no_eligible_step",
                    metadata={"session_steps": len(session.steps)}
                )
                return None

            aspect = step.refinement_aspect
            
            # Build dependency context from completed steps
            dependency_context = session.get_dependency_context(aspect.id)

            logger.debug(
                "Processing aspect '%s' with dependency context keys: %s",
                aspect.id,
                list(dependency_context.keys()) if dependency_context else [],
            )
            self.trace_emitter.emit(
                "aspect_processing_start",
                metadata={
                    "aspect_id": aspect.id,
                    "needs_review": step.needs_review,
                    "dependency_count": len(dependency_context),
                }
            )

            # Get prompts with dependency context
            system_prompt, user_prompt = step.get_prompts(
                query=session.original_query,
                dependency_context=dependency_context
            )

            # Perform the LLM interaction with validation enforcement
            response_text, parsed_payload, is_error, error_message = self._get_llm_response_with_validation(
                aspect=aspect,
                system_prompt=system_prompt,
                user_prompt=user_prompt
            )

            if is_error:
                failure_response = f"[Validation error: {error_message}]" if error_message else "[Validation error]"
                question_text = step.analysis_suggested_question or aspect.name
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
                    "aspect_name": aspect.name,
                    "question": question_text,
                    "response": failure_response,
                    "error": True
                }

            # Store the interaction in follow_up_history
            question_text = step.analysis_suggested_question or aspect.name
            step.add_follow_up(question=question_text, response=response_text)

            # Mark step as complete after this single interaction
            # (For multi-round follow-ups, external code can set needs_review=True)
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
                "aspect_name": aspect.name,
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
        """Call the LLM and enforce structured response validation when required.

        Returns:
            Tuple of (normalized_response_text, parsed_payload, is_error, error_message)
        """
        prompt = user_prompt
        base_prompt = user_prompt

        self.trace_emitter.emit(
            "llm_validation_start",
            metadata={
                "aspect_id": aspect.id,
                "max_retries": self.validation_max_retries,
            }
        )

        for attempt in range(self.validation_max_retries + 1):
            attempt_number = attempt + 1
            self.trace_emitter.emit(
                "llm_completion_attempt",
                metadata={
                    "aspect_id": aspect.id,
                    "attempt": attempt_number,
                }
            )
            try:
                result = self.llm_provider.complete(
                    system_prompt=system_prompt,
                    user_prompt=prompt
                )
            except Exception as exc:  # pragma: no cover - surface provider exceptions
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
                return "", None, True, f"LLM error: {exc}"

            response_text = (result.context or "").strip()

            if not aspect.response_format:
                # No structured schema required; return raw text
                self.trace_emitter.emit(
                    "llm_validation_skipped",
                    metadata={
                        "aspect_id": aspect.id,
                        "attempt": attempt_number,
                    }
                )
                return response_text, None, False, None

            # Parse structured response
            try:
                parsed_payload = json.loads(response_text)
            except json.JSONDecodeError as json_error:
                error_message = f"Response is not valid JSON: {json_error}"
                logger.warning(
                    "Aspect %s produced non-JSON response on attempt %d: %s",
                    aspect.id,
                    attempt_number,
                    error_message,
                )
                if attempt < self.validation_max_retries:
                    self.trace_emitter.emit(
                        "llm_validation_retry",
                        level="warning",
                        metadata={
                            "aspect_id": aspect.id,
                            "attempt": attempt_number,
                            "error": error_message,
                        }
                    )
                    prompt = self._augment_prompt_for_retry(base_prompt, error_message, attempt_number, response_text)
                    continue
                self.trace_emitter.emit(
                    "llm_validation_failed",
                    level="error",
                    metadata={
                        "aspect_id": aspect.id,
                        "attempt": attempt_number,
                        "error": error_message,
                    }
                )
                return response_text, None, True, error_message

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
                return normalized_text, parsed_payload, False, None

            error_message = validation_error or "Structured response failed validation"
            logger.warning(
                "Aspect %s response failed schema validation on attempt %d: %s",
                aspect.id,
                attempt_number,
                error_message,
            )

            if attempt < self.validation_max_retries:
                self.trace_emitter.emit(
                    "llm_validation_retry",
                    level="warning",
                    metadata={
                        "aspect_id": aspect.id,
                        "attempt": attempt_number,
                        "error": error_message,
                    }
                )
                prompt = self._augment_prompt_for_retry(base_prompt, error_message, attempt_number, response_text)
                continue

            self.trace_emitter.emit(
                "llm_validation_failed",
                level="error",
                metadata={
                    "aspect_id": aspect.id,
                    "attempt": attempt_number,
                    "error": error_message,
                }
            )
            return response_text, parsed_payload, True, error_message

        # Should not be reached, but return safe fallback
        return "", None, True, "Unknown validation failure"

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

        system_prompt = step.get_system_prompt()
        user_prompt = step.format_follow_up_prompt_template(
            original_query=session.original_query,
            include_examples=include_examples,
        )

        return system_prompt, user_prompt

    def _gather_refinement_details(
        self, session: QueryRefinementSession
    ) -> tuple[List[tuple[str, str]], List[tuple[str, str]]]:
        """Collect refinement clarifications and baseline summaries for synthesis."""

        clarifications: List[tuple[str, str]] = []
        baseline_summaries: List[tuple[str, str]] = []

        for step in session.steps:
            final_value = (step.final_response or "").strip()
            if final_value:
                clarifications.append((step.refinement_aspect.name, final_value))
                continue

            if step.was_skipped:
                continue

            if step.is_complete:
                summary = (step.initial_summary or step.analysis_reason or "").strip()
                if summary:
                    baseline_summaries.append((step.refinement_aspect.name, summary))

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
            return {
                "refined_query": session.original_query,
                "used_llm": False,
                "clarifications": [],
                "baseline_summaries": [],
                "metadata": {
                    "reason": "no_clarifications",
                },
            }

        system_prompt = (
            "You are an expert research assistant who rewrites user queries. "
            "Blend the initial query with clarified aspect details into a single, "
            "well-formed refined query. Do not add new information beyond the "
            "provided clarifications."
        )

        user_sections = [
            "ORIGINAL QUERY:",
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
            (
                "Compose a single refined query that integrates all provided details. "
                "Return only the refined query text without extra commentary."
            )
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

        return {
            "refined_query": refined_query,
            "used_llm": True,
            "clarifications": clarifications,
            "baseline_summaries": baseline_summaries,
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
        """
        aspects_needing_refinement = []
        aspects_clear = []
        
        for step in session.steps:
            aspect_info = {
                "id": step.refinement_aspect.id,
                "name": step.refinement_aspect.name,
                "description": step.refinement_aspect.description,
                "status": "clear" if step.is_complete else "needs_refinement"
            }
            
            # Add analysis details for aspects that need refinement
            if not step.is_complete:
                if step.analysis_reason:
                    aspect_info["reason"] = step.analysis_reason
                if step.analysis_suggested_question:
                    aspect_info["suggested_question"] = step.analysis_suggested_question
            
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