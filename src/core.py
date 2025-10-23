"""
Interactive query refinement module - Domain-agnostic, schema-based architecture.

This module helps users improve their queries through iterative refinement,
working with ANY user-defined schema across ANY research domain.

Pipeline Flow:
=====
1. User provides initial query + schema (e.g., PICO_SCHEMA, CLIMATE_SCHEMA, custom)
2. Manager.initialize() uses query_analyzer to detect missing dimensions and generate questions using dimensions' analysis_prompt
3. For each needed dimension:
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
- /skip                  - Skip current dimension entirely
- /done                  - Mark current step as complete (stop follow-ups)
- /continue              - Continue with remaining steps
- /finish                - Complete session with current refinements

Information:
- /status                - Show session progress
- /help                  - Show available commands
- /steps                 - List all refinement steps

These commands are detected via is_user_command() and processed via parse_user_command().
"""

import logging
from dataclasses import dataclass, field
from enum import Enum
from time import time
from typing import Any, Dict, List, Optional, Tuple

from .interfaces import LLMProviderInterface, TracingProviderInterface, QueryAnalyzerInterface
from .schemas import RefinementDimension

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
    CONTINUE = "continue"
    FINISH = "finish"
    
    # Information
    STATUS = "status"
    HELP = "help"
    STEPS = "steps"
    
    # Not a command
    NONE = "none"


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
    parts = user_input.strip()[1:].split(maxsplit=1)
    cmd_str = parts[0].lower()
    argument = parts[1] if len(parts) > 1 else None
    
    # Map command string to enum
    command_map = {
        "back": UserCommand.BACK,
        "prev": UserCommand.PREVIOUS,
        "previous": UserCommand.PREVIOUS,
        "goto": UserCommand.GOTO,
        "restart": UserCommand.RESTART,
        "skip": UserCommand.SKIP,
        "done": UserCommand.DONE,
        "continue": UserCommand.CONTINUE,
        "finish": UserCommand.FINISH,
        "status": UserCommand.STATUS,
        "help": UserCommand.HELP,
        "steps": UserCommand.STEPS,
    }
    
    if cmd_str not in command_map:
        return CommandResult(
            command=UserCommand.NONE,
            is_valid=False,
            error_message=f"Unknown command: /{cmd_str}. Type /help for available commands."
        )
    
    command = command_map[cmd_str]
    
    # Validate arguments for specific commands
    if command == UserCommand.GOTO:
        if not argument:
            return CommandResult(
                command=command,
                is_valid=False,
                error_message="/goto requires a step number. Example: /goto 2"
            )
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
  /back, /prev          Go back to previous step
  /goto <number>        Jump to specific step (e.g., /goto 2)
  /restart              Start refinement from beginning

CONTROL:
  /skip                 Skip current dimension entirely
  /done                 Mark current step complete (stop follow-ups)
  /continue             Continue with remaining steps
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

logger = logging.getLogger(__name__)

# =======
# Data Classes
# =======

@dataclass
class RefinementStep:
    """
    Represents a single query refinement interaction in the dialogue.
    Stores a single RefinementDimension, the generated question (optional), user response (optional), and completion status, and context.
    Additionally, it supports multi-turn follow-up questions for deeper clarification.
    """

    dimension: RefinementDimension
    # Init question/response pair
    question_generated: Optional[str] = None
    user_response: Optional[str] = None

    # Follow-up tracking
    follow_up_count: int = 0
    follow_up_history: List[Dict[str, str]] = field(default_factory=list)
    # Each entry in follow_up_history is a dict with 'question' and 'response' keys

    is_complete: bool = False
    final_value: Optional[Any] = None # Final refined value after all Q&A

    # Additional context for prompt formatting
    context: Dict[str, Any] = field(default_factory=dict)

    def format_prompt(
            self,
            query: str,
            **kwargs,
    )-> str:
        """
        Format the user prompt for this dimension using the current query and any additional context.
        
        For system prompt, use get_system_prompt() or get_prompts() for both.
        """
        prompt = self.dimension.get_full_prompt(
            query=query,
            **kwargs,
        )
        return prompt
    
    def get_system_prompt(self) -> str:
        """
        Get the system prompt for this dimension.
        
        Returns:
            System prompt string (from dimension or default)
        """
        return self.dimension.get_system_prompt()
    
    def get_prompts(self, query: str, dependency_context: Optional[Dict[str, str]] = None, **kwargs) -> tuple[str, str]:
        """
        Get both system and user prompts for this dimension with dependency context.
        
        Args:
            query: The query to analyze
            dependency_context: Dictionary mapping dimension IDs to their final values
            **kwargs: Additional context for prompt formatting
            
        Returns:
            Tuple of (system_prompt, user_prompt)
        """
        system_prompt = self.dimension.get_system_prompt()
        
        # Build user prompt with dependency context
        user_prompt_parts = []
        
        # Add dependency context if provided
        if dependency_context and self.dimension.depends_on:
            missing_deps = []
            context_lines = []
            
            for dep_id in self.dimension.depends_on:
                if dep_id in dependency_context and dependency_context[dep_id]:
                    # Find dimension name for more readable output
                    dep_name = dep_id.replace("_", " ").title()
                    context_lines.append(f"- {dep_name}: {dependency_context[dep_id]}")
                else:
                    missing_deps.append(dep_id)
            
            if context_lines:
                user_prompt_parts.append("Previous refinements:")
                user_prompt_parts.extend(context_lines)
                user_prompt_parts.append("")  # Blank line
            
            if missing_deps:
                import logging
                logger = logging.getLogger(__name__)
                logger.warning(
                    f"Dimension '{self.dimension.id}' depends on {missing_deps} but they have no values. "
                    "Continuing without that context."
                )
        
        # Add main analysis prompt
        user_prompt_parts.append(self.dimension.get_full_prompt(query=query, **kwargs))
        
        return system_prompt, "\n".join(user_prompt_parts)
    
    def can_ask_followup(self) -> bool:
        """
        Determines if a follow-up question can be asked based on the dimension's max_follow_ups.
        """
        return self.dimension.allow_follow_up and (self.follow_up_count < self.dimension.max_follow_ups)

    def add_follow_up(self, question: str, response: str):
        """
        Adds a follow-up question/response pair to the history and increments the follow-up count.
        """
        self.follow_up_history.append({
            "question": question,
            "answer": response
        })
        self.follow_up_count += 1
    
    def get_conversation_history_text(self) -> str:
        """
        Format follow-up history for use in prompts.
        """
        if not self.follow_up_history:
            return "no previous follow-up questions."
        
        history_lines = []
        for i, qa in enumerate(self.follow_up_history, start=0):
            history_lines.append(f"Follow-up {i+1}:") # i+1 to make it human-friendly
            history_lines.append(f" Q: {qa['question']}")
            history_lines.append(f" A: {qa['answer']}")
        return "\n".join(history_lines)
    
    def format_follow_up_prompt_template(
            self,
            original_query: str, 
            latest_answer: str,
    ) -> str:
        """
        Format the follow-up prompt for this dimension using the current query and latest answer.
        Uses UNIVERSAL_FOLLOWUP_ANALYSIS_PROMPT, and includes previous follow-up history.
        """
        from .followup_prompt import UNIVERSAL_FOLLOWUP_ANALYSIS_PROMPT

        conversation_history = self.get_conversation_history_text()

        prompt = UNIVERSAL_FOLLOWUP_ANALYSIS_PROMPT.format(
            original_query=original_query,
            dimension_name=self.dimension.name,
            dimension_description=self.dimension.description,
            conversation_history=conversation_history,
            latest_answer=latest_answer,
        )
        return prompt
    
    def complete_with_value(self, final_value: str):
        """Mark the step as complete with the final refined value."""
        self.is_complete = True
        self.final_value = final_value
    
@dataclass
class RefinementSession:
    """
    Represents an entire query refinement session with conversation history.

    Accepts a list of RefinementDimension defining what aspects can be refined (domain-agnostic).

    Stores the original query, refinement_framework, current query state, conversation history, and all refinement steps taken, and metadata.
    """

    original_query: str
    refinement_framework: List[RefinementDimension]
    current_query: str = "" # Updated query as refinements are made
    conversation_history: List[Dict[str, str]] = field(default_factory=list)
    steps: List[RefinementStep] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        # Initialize current_query to original_query if not set
        if not self.current_query:
            self.current_query = self.original_query

    def add_step(
            self,
            dimension: RefinementDimension,
            context: Optional[Dict[str, Any]] = None,
        ) -> RefinementStep:
        """
        Adds a new refinement step to the session for a dimension.

        Args:
            dimension (RefinementDimension): The dimension being refined.
            context (Optional[Dict[str, Any]]): Additional context for prompt formatting.
        
        Returns:
            RefinementStep: The newly created refinement step.
        """
        step = RefinementStep(
            dimension=dimension,
            context=context or {},
        )
        self.steps.append(step)
        return step
    
    def get_active_step(self) -> Optional[RefinementStep]:
        """
        Returns the current active refinement step (the last one that is not complete).
        """
        for step in self.steps:
            if not step.is_complete:
                return step
        return None
    
    def get_dependency_context(self, target_dimension_id: str) -> Dict[str, str]:
        """
        Build dependency context for a specific dimension.
        
        Only includes dependencies declared by the target dimension.
        
        Args:
            target_dimension_id: The dimension ID that needs dependency context
            
        Returns:
            Dictionary mapping dependency IDs to their final values
        """
        context = {}
        
        # Find the target dimension's dependencies
        target_dim = None
        for step in self.steps:
            if step.dimension.id == target_dimension_id:
                target_dim = step.dimension
                break
        
        if not target_dim or not target_dim.depends_on:
            return context
        
        # Collect final values for declared dependencies
        for step in self.steps:
            if step.dimension.id in target_dim.depends_on:
                if step.final_value:
                    context[step.dimension.id] = step.final_value
        
        return context
    
    def add_to_history(
            self,
            role: str,
            content: str
    ):
        """
        Adds a message to the conversation history.
        """
        self.conversation_history.append({
            "role": role,
            "content": content
        })
    
    def is_complete(self) -> bool:
        """
        Checks if all refinement steps are complete.
        """
        return all(step.is_complete for step in self.steps)
    
    def get_total_follow_ups(self) -> int:
        """
        Get total number of follow-up questions across all steps.
        
        Returns:
            Total count of follow-up questions asked in this session.
        """
        return sum(step.follow_up_count for step in self.steps)
    
    def get_step_summary(self) -> Dict[str, Any]:
        """
        Get a summary of all steps with their follow-up status.
        
        Returns:
            Dictionary with step statistics and status.
        """
        completed = sum(1 for step in self.steps if step.is_complete)
        in_progress = sum(1 for step in self.steps if not step.is_complete)
        total_followups = self.get_total_follow_ups()
        
        return {
            "total_steps": len(self.steps),
            "completed": completed,
            "in_progress": in_progress,
            "total_follow_ups": total_followups,
            "steps": [
                {
                    "dimension": step.dimension.name,
                    "is_complete": step.is_complete,
                    "follow_up_count": step.follow_up_count,
                    "has_final_value": step.final_value is not None,
                }
                for step in self.steps
            ]
        }
    
    def add_interaction(
        self, 
        step: RefinementStep,
        question: str,
        answer: Optional[str] = None,
        is_follow_up: bool = False
    ):
        """
        Add an interaction to both the step and session-level conversation history.
        
        Args:
            step: The refinement step this interaction belongs to
            question: The question asked
            answer: The user's answer (None if not yet answered)
            is_follow_up: Whether this is a follow-up question
        """
        interaction_type = "follow_up" if is_follow_up else "initial"
        
        # Add to session-level history
        self.add_to_history(
            role="assistant",
            content=f"[{step.dimension.name}] [{interaction_type}] {question}"
        )
        
        if answer:
            self.add_to_history(
                role="user",
                content=f"[{step.dimension.name}] [{interaction_type}] {answer}"
            )
    
    def get_full_conversation(self) -> str:
        """
        Get the complete conversation as formatted text.
        
        Returns:
            Human-readable conversation history.
        """
        lines = [f"Original Query: {self.original_query}", ""]
        
        for msg in self.conversation_history:
            role_label = "Assistant" if msg["role"] == "assistant" else "User"
            lines.append(f"{role_label}: {msg['content']}")
        
        if self.current_query != self.original_query:
            lines.append("")
            lines.append(f"Refined Query: {self.current_query}")
        
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
        
        # Navigation commands
        if command == UserCommand.BACK or command == UserCommand.PREVIOUS:
            return self._go_back()
        elif command == UserCommand.GOTO:
            if cmd_result.argument is None:
                return {"success": False, "message": "/goto requires step number"}
            return self._go_to_step(int(cmd_result.argument))
        elif command == UserCommand.RESTART:
            return self._restart()
        
        # Control commands
        elif command == UserCommand.SKIP:
            return self._skip_current()
        elif command == UserCommand.DONE or command == UserCommand.FINISH:
            return self._finish_current()
        elif command == UserCommand.CONTINUE:
            return {"success": True, "message": "Continuing with current step"}
        
        # Information commands
        elif command == UserCommand.STATUS:
            return self._get_status()
        elif command == UserCommand.STEPS:
            return self._list_steps()
        elif command == UserCommand.HELP:
            return {"success": True, "message": get_help_text()}
        
        return {"success": False, "message": f"Command {command.name} not implemented"}
    
    def _invalidate_dependents(self, changed_dimension_id: str) -> List[str]:
        """
        Invalidate all dimensions that depend on the changed dimension.
        
        Args:
            changed_dimension_id: The dimension ID that was changed
            
        Returns:
            List of invalidated dimension names
        """
        invalidated = []
        
        for step in self.steps:
            if changed_dimension_id in step.dimension.depends_on:
                # Mark dependent as incomplete and clear its data
                step.is_complete = False
                step.user_response = None
                step.final_value = None
                step.follow_up_count = 0
                step.follow_up_history = []
                invalidated.append(step.dimension.name)
                
                # Recursively invalidate dependents of this step
                sub_invalidated = self._invalidate_dependents(step.dimension.id)
                invalidated.extend(sub_invalidated)
        
        return invalidated
    
    def _go_back(self) -> Dict[str, Any]:
        """Navigate to the previous step and invalidate dependent dimensions."""
        active = self.get_active_step()
        if not active:
            return {"success": False, "message": "No active step to go back from"}
        
        active_idx = self.steps.index(active)
        if active_idx == 0:
            return {"success": False, "message": "Already at first step"}
        
        # Mark current as incomplete and clear its data
        active.is_complete = False
        active.user_response = None
        active.final_value = None
        
        # Reactivate previous step
        prev_step = self.steps[active_idx - 1]
        prev_step.is_complete = False
        prev_step.final_value = None
        
        # Invalidate dimensions that depend on the previous step
        invalidated = self._invalidate_dependents(prev_step.dimension.id)
        
        message = f"Returned to step {active_idx}: {prev_step.dimension.name}"
        if invalidated:
            message += f". Invalidated dependent dimensions: {', '.join(invalidated)}"
        
        return {
            "success": True,
            "message": message,
            "step_index": active_idx - 1,
            "step": prev_step,
            "invalidated": invalidated,
        }
    
    def _go_to_step(self, step_number: int) -> Dict[str, Any]:
        """Navigate to a specific step and invalidate dependent dimensions."""
        if step_number < 1 or step_number > len(self.steps):
            return {
                "success": False,
                "message": f"Invalid step number. Valid range: 1-{len(self.steps)}",
            }
        
        step_idx = step_number - 1
        target_step = self.steps[step_idx]
        
        # Mark target as incomplete
        target_step.is_complete = False
        target_step.final_value = None
        
        # Invalidate all dependents of the target dimension
        invalidated = self._invalidate_dependents(target_step.dimension.id)
        
        # Also invalidate all steps after the target (they come after in sequence)
        for i in range(step_idx + 1, len(self.steps)):
            if not self.steps[i].is_complete:
                continue  # Already incomplete
            self.steps[i].is_complete = False
            self.steps[i].user_response = None
            self.steps[i].final_value = None
            self.steps[i].follow_up_count = 0
            self.steps[i].follow_up_history = []
            if self.steps[i].dimension.name not in invalidated:
                invalidated.append(self.steps[i].dimension.name)
        
        message = f"Jumped to step {step_number}: {target_step.dimension.name}"
        if invalidated:
            message += f". Invalidated: {', '.join(invalidated)}"
        
        return {
            "success": True,
            "message": message,
            "step_index": step_idx,
            "step": target_step,
            "invalidated": invalidated,
        }
    
    def _restart(self) -> Dict[str, Any]:
        """Restart the entire refinement session."""
        # Mark all steps incomplete and clear data
        for step in self.steps:
            step.is_complete = False
            step.user_response = None
            step.final_value = None
            step.follow_up_count = 0
            step.follow_up_history = []
        
        # Reset query to original
        self.current_query = self.original_query
        
        # Clear conversation history
        self.conversation_history = []
        
        return {
            "success": True,
            "message": "Session restarted. All progress cleared.",
        }
    
    def _skip_current(self) -> Dict[str, Any]:
        """Skip the current dimension without providing a value."""
        active = self.get_active_step()
        if not active:
            return {"success": False, "message": "No active step to skip"}
        
        # Mark as complete without setting final_value
        active.is_complete = True
        active.final_value = None  # Explicitly no value
        
        return {
            "success": True,
            "message": f"Skipped dimension: {active.dimension.name}",
            "step": active,
        }
    
    def _finish_current(self) -> Dict[str, Any]:
        """Finish the current step with the last response as final value."""
        active = self.get_active_step()
        if not active:
            return {"success": False, "message": "No active step to finish"}
        
        if not active.user_response:
            return {
                "success": False,
                "message": "Cannot finish: no response provided yet",
            }
        
        # Mark complete with current response as final value
        active.is_complete = True
        active.final_value = active.user_response
        
        return {
            "success": True,
            "message": f"Completed dimension: {active.dimension.name}",
            "step": active,
        }
    
    def _get_status(self) -> Dict[str, Any]:
        """Get current session status."""
        active = self.get_active_step()
        summary = self.get_step_summary()
        
        status_lines = [
            "Session Status:",
            f"  Steps: {summary['completed']}/{summary['total_steps']} complete",
            f"  Follow-ups asked: {summary['total_follow_ups']}",
        ]
        
        if active:
            active_idx = self.steps.index(active) + 1
            status_lines.append(f"  Current: Step {active_idx} - {active.dimension.name}")
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
            status = "completed" if step.is_complete else ("currently active" if step == active else "not started")
            followups = f" ({step.follow_up_count} follow-ups)" if step.follow_up_count > 0 else ""
            lines.append(f"  {status} {i}. {step.dimension.name}{followups}")
        
        return {
            "success": True,
            "message": "\n".join(lines),
            "steps": self.steps,
        }
    
    def to_dict(self) -> Dict[str, Any]:
        """
        Serializes the session to a dictionary, including all follow-up data.

        Returns:
            Dict[str, Any]: The serialized session.
        """
        return {
            "original_query": self.original_query,
            "dimensions": [dim.name for dim in self.refinement_framework],
            "current_query": self.current_query,
            "conversation_history": self.conversation_history,
            "steps": [
                {
                    "dimension_id": step.dimension.id,
                    "dimension_name": step.dimension.name,
                    "dimension_description": step.dimension.description,
                    # Initial question/response
                    "question_generated": step.question_generated,
                    "user_response": step.user_response,
                    # Follow-up tracking
                    "follow_up_count": step.follow_up_count,
                    "follow_up_history": step.follow_up_history,
                    # Completion
                    "is_complete": step.is_complete,
                    "final_value": step.final_value,
                    # Context
                    "context": step.context,
                }
                for step in self.steps
            ],
            "metadata": self.metadata,
        }
    
#=====
# Refinement Process Orchestration
#=====

class QueryRefinementManager:
    """
    Orchestrates the multi-step query refinement process using provided LLM, tracing, and query analysis interfaces.

    Refinement logic is domain-agnostic and driven by the provided schema dimensions.
    All methods work with RefinementSession objects, allowing external management of state and persistence (files/Redis/databases).

    Key responsibilities:
    - Detecting wich dimensions need refinement based on the initial query
    - Generating questions for each dimension using the query analyzer
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
        query_analyzer: Analyzer for detecting missing dimensions
                    (if None, will assume all dimensions need refinement)
        tracing_provider: Tracing provider for observability
            (if None, will use no-op implementation)
    """

    def __init__(
        self,
        llm_provider: LLMProviderInterface,
        query_analyzer: QueryAnalyzerInterface,
        tracing_provider: TracingProviderInterface,
    ):
        """Initialize the manager with injected dependencies

        Args:
            llm_provider (LLMProviderInterface): LLM provider for question generation and synthesis
            query_analyzer (QueryAnalyzerInterface): Analyzer for detecting missing dimensions
                    (if None, will assume all dimensions need refinement)
            tracing_provider (TracingProviderInterface): Tracing provider for observability
                    (if None, will use no-op implementation)
        """
        self.llm_provider = llm_provider
        self.query_analyzer = query_analyzer
        self.tracing_provider = tracing_provider

        #Lazy import to avoid circular dependencies
        if tracing_provider is None:
            from .providers import NoOpTracingProvider
            self.tracing_provider = NoOpTracingProvider()
        
        logger.info("QueryRefinementManager initialized with "
                    "LLM provider: %s, Query Analyzer: %s, Tracing Provider: %s",
                    llm_provider.__class__.__name__, query_analyzer.__class__.__name__ if query_analyzer else "None", tracing_provider.__class__.__name__ if tracing_provider else "disabled")
        
        def initialize(
            self,
            original_query: str,
            refinement_framework: List[RefinementDimension],
            **kwargs,
        ) -> RefinementSession:
            """
            Initialize a new refinement session for the given query and dimensions.

            Analyzes the query against the refinement framework to determine which ones need refinement, then creates a session with appropriate steps.

            Args:
                original_query (str): The original query to refine.
                refinement_framework (List[RefinementDimension]): The dimensions to consider for refinement.
                **kwargs: Additional keyword arguments to pass to the session.

            Returns:
                RefinementSession: Initialized refinement session with steps for needed dimensions.
            """
            with self.tracing_provider.start_trace("initialize_refinement_session") as trace:
                trace.add_attribute("original_query", original_query)
                trace.add_attribute("num_refinement_dimensions", len(refinement_framework))

                init_start_time = time()

                logger.info("Initializing refinement session for query: %s", original_query)
                logger.debug("Refinement framework dimensions: %s",
                             [dim.name for dim in refinement_framework])
                
                #create a new session
                session = RefinementSession(
                    original_query=original_query,
                    refinement_framework=refinement_framework,
                )
                session.metadata.update(kwargs)

                # Analyze which dimensions need refinement
                dimensions_to_refine = self.query_analyzer.analyze_query(
                    query=original_query,
                    refinement_framework=refinement_framework,
                    llm_provider=(
                        self.llm_provider
                        if self.query_analyzer.supports_llm_integration
                        else None   
                    )
                )
                return session