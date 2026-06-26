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
import time
from datetime import datetime, timezone
import json
import logging
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Literal, Optional, Union, Tuple

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
from .schema.response import (
    ConceptEntry,
    ResearchStatementResponse,
    SemanticRepresentationResponse,
    SearchConstructionResponse,
    SearchOptimized,
    Terminology,
)
from .schema.synthesis import (
    validate_synthesis_response,
    NormalizationPromptBuilder,
    SemanticRepresentationPromptBuilder,
    SearchConstructionPromptBuilder,
)
from .schema.response import (
    SearchFilters,
    SearchOptimized,
    KeywordSearch,
    SearchTerms,
    Terminology,
    CombinedBlock,
    SearchExpansionInput,
    SearchExpansionLLMResponse,
    SearchExpansionResponse,
    ExpansionLevel,
)
from .schema.search_expansion import (
    build_level0_query,
    build_level1_query,
    build_level1_blocks,
    build_leveln_query,
    build_leveln_blocks,
    build_keyword_statement,
    SearchExpansionPromptBuilder,
    GEOGRAPHY_ROLES,
    SETTING_ROLES,
    POPULATION_ROLES,
)

from .session_commands import SessionCommands
from .session_models import AspectRefinementState, RefinementSession

# Module logger - use get_logger() in functions for request context
logger = logging.getLogger(__name__)


PUBLICATION_TYPE_PATTERNS = [
    (r"\brcts?\b|\brandomi[sz]ed controlled trials?\b", "Randomized controlled trial"),
    (r"\bsystematic reviews?\b", "Systematic review"),
    (r"\bscoping reviews?\b", "Scoping review"),
    (r"\brapid reviews?\b", "Rapid review"),
    (r"\bliving reviews?\b", "Living review"),
    (r"\bmeta-analys(?:is|es)\b", "Meta-analysis"),
    (r"\bnarrative reviews?\b", "Narrative review"),
    (r"\breviews?\b", "Review"),
    (r"\bcohort studies?\b|\bcohort study\b", "Cohort study"),
    (r"\bcase[- ]control studies?\b|\bcase control studies?\b", "Case control study"),
    (r"\bcross[- ]sectional studies?\b|\bcross sectional studies?\b", "Cross-sectional study"),
    (r"\bobservational studies?\b", "Observational study"),
    (r"\bclinical trials?\b", "Clinical trial"),
    (r"\bclinical studies?\b", "Clinical study"),
    (r"\bcase reports?\b", "Case report"),
    (r"\bcase series\b", "Case series"),
    (r"\bpilot studies?\b", "Pilot study"),
    (r"\bevaluation studies?\b", "Evaluation study"),
    (r"\bquality improvement studies?\b|\bquality improvement\b", "Quality improvement study"),
    (r"\bvalidation studies?\b", "Validation study"),
    (r"\bdiagnostic test accuracy studies?\b", "Diagnostic test accuracy study"),
    (r"\bbefore and after studies?\b", "Before and after study"),
    (r"\bcomparative studies?\b", "Comparative study"),
    (r"\bguidelines?\b", "Guideline"),
    (r"\bpolicy documents?\b|\bpolicies\b", "Policy document"),
    (r"\bgovernment documents?\b", "Government document"),
    (r"\bconsensus conferences?\b", "Consensus conference"),
]

# Permitted values for the fields_of_study filter.
# Sourced from the synthesis template; the LLM must pick only from this list.
FIELDS_OF_STUDY_PERMITTED: List[str] = [
    "Agricultural and Food Sciences",
    "Art",
    "Biology",
    "Business",
    "Chemistry",
    "Computer Science",
    "Economics",
    "Education",
    "Engineering",
    "Environmental Science",
    "Geography",
    "Geology",
    "History",
    "Law",
    "Linguistics",
    "Materials Science",
    "Mathematics",
    "Medicine",
    "Philosophy",
    "Physics",
    "Political Science",
    "Psychology",
    "Public Health",
    "Sociology",
]

PUBLICATION_TYPES_PERMITTED: frozenset = frozenset([
    "Before and after study",
    "Case control study",
    "Case report",
    "Case series",
    "Clinical study",
    "Clinical trial",
    "Cohort study",
    "Comparative study",
    "Consensus conference",
    "Cross-sectional study",
    "Diagnostic test accuracy study",
    "Evaluation study",
    "Government document",
    "Guideline",
    "Living review",
    "Meta-analysis",
    "Narrative review",
    "Observational study",
    "Pilot study",
    "Policy document",
    "Quality improvement study",
    "Randomized controlled trial",
    "Rapid review",
    "Review",
    "Scoping review",
    "Systematic review",
    "Validation study",
])

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
        
        >>> parse_user_command("/back")
        CommandResult(command=UserCommand.BACK, argument=None, ...)
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
# Data Classes (Session models moved to session_models.py)
# =======


class QueryRefinementManager:
    def __init__(
        self,
        llm_provider: LLMProviderInterface,
        tracing_provider: Optional[TracingProviderInterface] = None,
        default_temperature: float = 0.2,
        default_max_tokens: int = 4096,
        terminal_reinforcement_threshold: Optional[int] = None,
    ) -> None:
        self.llm_provider: LLMProviderInterface = llm_provider
        self.tracing_provider: TracingProviderInterface = tracing_provider or NoOpTracingProvider()
        self.trace_emitter: TraceEventEmitter = TraceEventEmitter(self.tracing_provider)
        self.default_temperature: float = default_temperature
        self.default_max_tokens: int = default_max_tokens
        # Terminal reinforcement threshold: defaults to 3 (data-driven optimal value)
        # Can be overridden by passing explicit value to constructor
        self.terminal_reinforcement_threshold: int = terminal_reinforcement_threshold if terminal_reinforcement_threshold is not None else 3
        
        logger.info(
            "QueryRefinementManager initialized with LLM provider: %s, Tracing Provider: %s, default_temperature=%s, default_max_tokens=%s, Terminal Reinforcement Threshold: %d",
            llm_provider.__class__.__name__,
            self.tracing_provider.__class__.__name__,
            self.default_temperature,
            self.default_max_tokens,
            self.terminal_reinforcement_threshold,
        )

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
                "name": step.refinement_aspect.name,
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
                    last_question = step.follow_up_question or step.refinement_aspect.name
                    step.add_follow_up(
                        question=last_question,
                        response=result.current
                    )
                    break
                else:
                    # Store question for next round
                    # The last user response is already in follow_up_history from CLI/API
                    # Just update refinement_question for next iteration
                    step.follow_up_question = result.question
                    
                    if rounds >= max_followups:
                        # Reached max rounds without completion
                        step.is_complete = False
                        break
                        
            except ValueError as e:
                # LLM error - mark as complete but do NOT overwrite conversation history
                # with an error string, as add_follow_up() would corrupt normalized_value
                # (the user's real answer is already in history from before this call).
                logger.error(f"LLM error in followup for {step.refinement_aspect.id}: {e}")
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
            "name": step.refinement_aspect.name,
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
        completed_context = session.get_completed_context(aspect_id)
        messages = step.get_messages(
            query=session.original_query,
            dependency_context=dependency_context,
            completed_context=completed_context,
            terminal_reinforcement_threshold=self.terminal_reinforcement_threshold
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
        
        if result.complete:
            # Refinement complete - store final value
            step.normalized_value = result.current
            step.is_complete = True
            
            # Log the assembled value for debugging
            logger.info(
                f"Dimension complete for '{step.refinement_aspect.name}' | "
                f"Assembled value: {result.current}"
            )
            
            return {
                'complete': True,
                'aspect_id': aspect_id,
                'name': step.refinement_aspect.name,
                'current': result.current
            }
        else:
            # Needs follow-up - store question and preserve any partial value
            if result.current and result.current.strip():
                step.normalized_value = result.current
            step.follow_up_question = result.question
            step.quick_replies = result.examples
            step.is_complete = False

            return {
                'complete': False,
                'aspect_id': aspect_id,
                'name': step.refinement_aspect.name,
                'next_question': result.question,
                'examples': result.examples,
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
                         [aspect.name for aspect in refinement_framework])
            
            # Create session
            session = RefinementSession(original_query=original_query)
            
            # Store the complete framework for potential reconstruction (e.g., after /back command)
            session._complete_framework = list(refinement_framework)
            
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

        self.trace_emitter.emit(
            "step_ready_for_prompt",
            metadata={
                "aspect_id": aspect_id,
                "depends_on": step.refinement_aspect.depends_on,
            },
        )
        return True

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
            dependency_context=dependency_context,
            completed_context=session.get_completed_context(aspect.id),
            terminal_reinforcement_threshold=self.terminal_reinforcement_threshold
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
        question_text = step.follow_up_question or aspect.name
        
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
            "name": aspect.name,
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
        question_text = step.follow_up_question or aspect.name
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
            "aspect_name": aspect.name,
            "question": question_text,
            "response": response_text,
            **({"structured_payload": parsed_payload} if parsed_payload is not None else {}),
            "error": False
        }

    async def _get_llm_response_with_validation(
        self,
        aspect: RefinementAspect,
        messages: List[Dict[str, str]],
    ) -> tuple[str, Optional[Dict[str, Any]], bool, Optional[str]]:
        """
        Call the LLM asynchronously with structured response validation.
        
        With structured outputs (response_format), the LLM provider guarantees
        valid JSON responses, eliminating the need for retry logic.
        
        Args:
            aspect: The refinement aspect being evaluated
            messages: Structured messages array

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
            attempt_number=1,
        )

        prompt_metrics = {}
        if hasattr(self, "_last_llm_metadata"):
            prompt_metrics = getattr(self, "_last_llm_metadata", {}) or {}
            prompt_metrics = prompt_metrics.get("prompt_metrics", {}) or {}

        if prompt_metrics:
            self.trace_emitter.emit(
                "llm_validation_prompt_metrics",
                metadata={
                    "aspect_id": aspect.id,
                    "message_count": prompt_metrics.get("message_count", 0),
                    "prompt_char_count": prompt_metrics.get("prompt_char_count", 0),
                    "estimated_prompt_tokens": prompt_metrics.get("estimated_prompt_tokens", 0),
                    "max_output_tokens": prompt_metrics.get("max_output_tokens"),
                },
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
        messages: List[Dict[str, str]],
        attempt_number: int = 1,
    ) -> tuple[str, Optional[str]]:
        """
        Call the LLM provider with structured outputs.
        
        Args:
            aspect: The refinement aspect being evaluated
            messages: Structured messages array
            attempt_number: Attempt number for logging
            
        Returns:
            Tuple of (response_text, error_message)
        """
        try:
            # Use structured outputs for guaranteed valid responses
            import time
            call_start = time.time()

            self._last_llm_metadata = {}

            result = await self.llm_provider.complete_async(
                messages=messages,
                response_format=DimensionEvaluationResponse,  # ✨ Structured output
                cache_system_prompt=True  # System prompts are static per-aspect
            )

            self._last_llm_metadata = result.metadata or {}
            
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
            
            # Log raw response for debugging (truncate if very long)
            if len(response_text) <= 500:
                logger.debug(
                    "Raw LLM response for aspect %s: %s",
                    aspect.id,
                    response_text
                )
            else:
                logger.debug(
                    "Raw LLM response for aspect %s (truncated): %s... [%d more chars]",
                    aspect.id,
                    response_text[:500],
                    len(response_text) - 500
                )
            
            # Check if response metadata indicates cache hit (Anthropic-specific)
            usage = getattr(result, 'usage', None)
            if usage is not None:
                cache_read_input_tokens = (
                    usage.get('cache_read_input_tokens', 0)
                    if isinstance(usage, dict)
                    else getattr(usage, 'cache_read_input_tokens', 0)
                )
                cache_hit = cache_read_input_tokens > 0
                if cache_hit:
                    logger.info(f"  -> Cache HIT: {cache_read_input_tokens} tokens read from cache")
                else:
                    logger.info(f"  -> Cache MISS: System prompt cached for future requests")
            
            return response_text, None
            
        except Exception as exc:  # pragma: no cover
            self._last_llm_metadata = {}
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
        # Multi-strategy JSON extraction for robust handling of various LLM response formats
        cleaned_text = response_text.strip()
        extraction_method = "direct"  # Track which method succeeded for debugging
        
        logger.debug(
            "Starting JSON extraction for aspect %s (attempt %d)",
            aspect.id,
            attempt_number,
            extra={
                "response_length": len(response_text),
                "starts_with": response_text[:50] if response_text else "",
            }
        )
        
        # Strategy 1: Remove markdown code fences
        if cleaned_text.startswith("```"):
            lines = cleaned_text.splitlines()
            if len(lines) >= 2 and lines[0].startswith("```"):
                body = lines[1:]
                if body and body[-1].startswith("```"):
                    body = body[:-1]
                cleaned_text = "\n".join(body).strip()
                extraction_method = "markdown_fences_removed"
                logger.debug("Removed markdown code fences for aspect %s", aspect.id)
        
        # Strategy 2: Direct JSON if starts with {
        if not cleaned_text.startswith("{"):
            import re
            
            # Strategy 3: Look for JSON object with balanced braces (most robust)
            # This handles JSON embedded in text like "Here's the response: {json...}"
            brace_count = 0
            start_pos = -1
            end_pos = -1
            
            for i, char in enumerate(cleaned_text):
                if char == '{':
                    if brace_count == 0:
                        start_pos = i
                    brace_count += 1
                elif char == '}':
                    brace_count -= 1
                    if brace_count == 0 and start_pos >= 0:
                        end_pos = i + 1
                        break
            
            if start_pos >= 0 and end_pos > start_pos:
                json_candidate = cleaned_text[start_pos:end_pos]
                # Verify it's valid JSON before accepting
                try:
                    json.loads(json_candidate)
                    cleaned_text = json_candidate
                    extraction_method = "balanced_braces"
                    logger.info(
                        "Extracted JSON using balanced brace matching for aspect '%s' (found at position %d-%d)",
                        aspect.id,
                        start_pos,
                        end_pos
                    )
                except json.JSONDecodeError:
                    # Try fallback strategies
                    pass
            
            # Strategy 4: Regex fallback (greedy match for entire JSON object)
            if not cleaned_text.startswith("{"):
                # Try to match the outermost JSON object
                json_match = re.search(r'\{[\s\S]*\}', cleaned_text)
                if json_match:
                    cleaned_text = json_match.group(0)
                    extraction_method = "regex_match"
                    logger.info("Extracted JSON using regex for aspect '%s'", aspect.id)
                else:
                    # Strategy 5: Look for JSON with specific field markers
                    # Search for objects containing our expected fields (complete, current, question)
                    field_pattern = r'\{[^}]*"complete"[^}]*"current"[^}]*"question"[^}]*\}'
                    field_match = re.search(field_pattern, cleaned_text, re.DOTALL)
                    if field_match:
                        cleaned_text = field_match.group(0)
                        extraction_method = "field_pattern"
                        logger.info("Extracted JSON using field pattern matching for aspect '%s'", aspect.id)
                    else:
                        # No JSON found after all strategies - provide detailed error
                        error_message = (
                            f"No valid JSON found in response after trying multiple extraction strategies. "
                            f"Response appears to be plain text/markdown. "
                            f"LLM model may not support structured outputs. "
                            f"Consider: (1) Using a model with JSON mode support (gpt-4, claude-3.5+, gemini-1.5+), "
                            f"(2) Adding 'response_format': {{'type': 'json_object'}} to settings, "
                            f"(3) Checking API key and model availability."
                        )
                        logger.warning(
                            "Aspect %s failed JSON extraction on attempt %d: %s. Response preview: %s",
                            aspect.id,
                            attempt_number,
                            error_message,
                            cleaned_text[:300] if len(cleaned_text) > 300 else cleaned_text,
                            extra={
                                "response_length": len(response_text),
                                "strategies_tried": ["direct", "markdown_fences", "balanced_braces", "regex", "field_pattern"],
                            }
                        )
                        return self._ValidationResult(
                            is_valid=False,
                            parsed_payload=None,
                            error_message=error_message,
                        )
        
        logger.debug(
            "JSON extraction successful for aspect %s using method: %s",
            aspect.id,
            extraction_method,
            extra={"extracted_length": len(cleaned_text)}
        )
        
        # Parse JSON with detailed error reporting
        try:
            parsed_payload = json.loads(cleaned_text)
            logger.debug(
                "Successfully parsed JSON for aspect %s",
                aspect.id,
                extra={
                    "extraction_method": extraction_method,
                    "field_count": len(parsed_payload) if isinstance(parsed_payload, dict) else 0,
                    "has_complete": "complete" in parsed_payload if isinstance(parsed_payload, dict) else False,
                    "has_current": "current" in parsed_payload if isinstance(parsed_payload, dict) else False,
                    "has_question": "question" in parsed_payload if isinstance(parsed_payload, dict) else False,
                }
            )
        except json.JSONDecodeError as json_error:
            # Provide detailed error with context
            error_line = getattr(json_error, 'lineno', 0)
            error_col = getattr(json_error, 'colno', 0)
            error_message = (
                f"JSON parsing failed: {json_error.msg} at line {error_line}, column {error_col}. "
                f"The extracted text may be malformed or truncated. "
                f"Check max_tokens setting if response appears cut off."
            )
            
            # Show context around error if possible
            if error_line > 0:
                lines = cleaned_text.split('\n')
                context_start = max(0, error_line - 2)
                context_end = min(len(lines), error_line + 2)
                context = '\n'.join(lines[context_start:context_end])
                logger.warning(
                    "JSON parse error for aspect %s on attempt %d: %s\nContext:\n%s",
                    aspect.id,
                    attempt_number,
                    error_message,
                    context,
                    extra={
                        "error_line": error_line,
                        "error_col": error_col,
                        "json_length": len(cleaned_text),
                        "extraction_method": extraction_method,
                    }
                )
            else:
                logger.warning(
                    "JSON parse error for aspect %s on attempt %d: %s. Content: %s",
                    aspect.id,
                    attempt_number,
                    error_message,
                    cleaned_text[:200] if len(cleaned_text) > 200 else cleaned_text,
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
                # Only log warnings in DEBUG mode - LLMs often add harmless extra fields
                logger.debug(
                    "Response validation warnings for aspect %s: %s",
                    aspect.id,
                    "; ".join(warnings),
                )
                self.trace_emitter.emit(
                    "llm_validation_warning",
                    level="debug",
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
                    "complete": parsed_payload.get("complete", False),
                    "has_current_value": bool(parsed_payload.get("current")),
                    "has_question": bool(parsed_payload.get("question")),
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
                        clarifications.append((step.refinement_aspect.name, summary))
                    else:
                        # No follow-ups, was clear in original query
                        baseline_summaries.append((step.refinement_aspect.name, summary))
                    continue
            
            # Fallback: needs_refinement_rationale (explanation why aspect was clear)
            if step.is_complete:
                rationale = (step.reasoning or "").strip()
                if rationale:
                    baseline_summaries.append((step.refinement_aspect.name, rationale))

        return clarifications, baseline_summaries

    @staticmethod
    def _serialize_dimension_value(value: Any) -> Optional[str]:
        if value is None or value == "":
            return None
        if isinstance(value, (dict, list)):
            return json.dumps(value, ensure_ascii=False)
        return str(value)

    def _assemble_dimensions_specifications(
        self,
        session: RefinementSession,
    ) -> Optional[Dict[str, Optional[str]]]:
        if not session.steps:
            return None

        dimensions_specifications: Dict[str, Optional[str]] = {}
        for step in session.steps:
            if step.was_skipped:
                dimensions_specifications[step.refinement_aspect.id] = None
                continue

            dimensions_specifications[step.refinement_aspect.id] = self._serialize_dimension_value(
                step.normalized_value
            )

        return dimensions_specifications

    def _collect_synthesis_source_text(self, session: RefinementSession) -> str:
        source_chunks = [session.original_query]
        for step in session.steps:
            serialized = self._serialize_dimension_value(step.normalized_value)
            if serialized:
                source_chunks.append(serialized)
        return "\n".join(chunk for chunk in source_chunks if chunk)

    @staticmethod
    def _dedupe_preserve_order(values: List[str]) -> List[str]:
        seen = set()
        output = []
        for value in values:
            if value not in seen:
                seen.add(value)
                output.append(value)
        return output

    def _extract_publication_years(self, source_text: str) -> str:
        anchor_year = datetime.now(timezone.utc).year

        range_match = re.search(
            r"\b((?:19|20)\d{2})\s*(?:-|–|to|through)\s*((?:19|20)\d{2})\b",
            source_text,
            re.IGNORECASE,
        )
        if range_match:
            return f"{range_match.group(1)}-{range_match.group(2)}"

        since_match = re.search(
            r"\b(?:since|from)\s+((?:19|20)\d{2})\b(?:\s+(?:onward|onwards|forward|to date|to present))?",
            source_text,
            re.IGNORECASE,
        )
        if since_match:
            return f"{since_match.group(1)}-{anchor_year}"

        lower_source = source_text.lower()
        if "last decade" in lower_source:
            return f"{anchor_year - 10}-{anchor_year}"

        if "recent" in lower_source:
            health_keywords = (
                "health", "medicine", "clinical", "patient", "disease", "public health",
                "hospital", "treatment", "diagnosis", "epidemiolog",
            )
            start_year = 2020 if any(keyword in lower_source for keyword in health_keywords) else 2021
            return f"{start_year}-{anchor_year}"

        return ""

    def _extract_publication_types(self, source_text: str) -> List[str]:
        publication_types = []
        matched_positions: set = set()
        for pattern, canonical_name in PUBLICATION_TYPE_PATTERNS:
            for m in re.finditer(pattern, source_text, re.IGNORECASE):
                span = (m.start(), m.end())
                # Skip if this span was already claimed by a more-specific earlier pattern
                if not any(
                    existing_start <= span[0] and span[1] <= existing_end
                    for existing_start, existing_end in matched_positions
                ):
                    matched_positions.add(span)
                    publication_types.append(canonical_name)
        return self._dedupe_preserve_order(publication_types)

    def _extract_authors(self, source_text: str) -> List[str]:
        authors = []
        patterns = [
            r"\bauthors?\s*:\s*([^.;\n]+)",
            r"\bauthored by\s+([^.;\n]+)",
            r"\bby\s+([A-Z][A-Za-z.'-]+(?:[ \t]+[A-Z][A-Za-z.'-]+){0,2}(?:[ \t]*(?:,|and)[ \t]*[A-Z][A-Za-z.'-]+(?:[ \t]+[A-Z][A-Za-z.'-]+){0,2})*)",
        ]
        for pattern in patterns:
            for match in re.finditer(pattern, source_text):
                raw_names = re.split(r",|\band\b", match.group(1))
                for raw_name in raw_names:
                    candidate = raw_name.strip(" .")
                    if re.match(r"^[A-Z][A-Za-z.'-]+(?:\s+[A-Z][A-Za-z.'-]+){0,2}$", candidate):
                        authors.append(candidate)
        return self._dedupe_preserve_order(authors)

    def _extract_venues(self, source_text: str) -> List[str]:
        venues = []
        patterns = [
            r"\bpublished in\s+([^.;\n]+)",
            r"\bjournal\s*:\s*([^.;\n]+)",
            r"\bconference\s*:\s*([^.;\n]+)",
            r"\bvenue\s*:\s*([^.;\n]+)",
        ]
        for pattern in patterns:
            for match in re.finditer(pattern, source_text, re.IGNORECASE):
                candidate = re.split(r"\s+by\s+", match.group(1), maxsplit=1, flags=re.IGNORECASE)[0].strip(" .")
                if candidate:
                    venues.append(candidate)
        return self._dedupe_preserve_order(venues)

    def _assemble_deterministic_search_filters(self, session: RefinementSession) -> SearchFilters:
        source_text = self._collect_synthesis_source_text(session)
        return SearchFilters(
            publication_years=self._extract_publication_years(source_text),
            venues=self._extract_venues(source_text),
            authors=self._extract_authors(source_text),
            publication_types=self._extract_publication_types(source_text),
            fields_of_study=[],
        )

    async def _execute_split_call(
        self,
        system_prompt: str,
        user_prompt: str,
        response_model: type,
        call_name: str,
        *,
        model: Optional[str] = None,
        temperature: float = 0.2,
        max_tokens: int = 512,
        use_structured_output: bool = True,
    ) -> Tuple[Optional[Any], Optional[Dict[str, Any]]]:
        """Single LLM round-trip + JSON extraction + Pydantic parse.

        Returns ``(parsed_model_or_None, metadata_dict)``.

        ``use_structured_output=False`` skips the provider's constrained-decoding
        path (tool use / JSON mode) and parses the raw text response instead.
        Use this when the model reliably emits well-formed JSON from the system
        prompt but structured-output schema constraints interfere with generation.
        """
        try:
            result = await self.llm_provider.complete_async(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                model=model,
                temperature=temperature,
                max_tokens=max_tokens,
                response_format=response_model if use_structured_output else None,
                cache_system_prompt=False,
            )
        except Exception as exc:
            logger.warning("Split call '%s' failed (provider error): %s", call_name, exc)
            self.trace_emitter.emit(
                f"split_call_{call_name}_error",
                level="warning",
                metadata={"error": str(exc)},
            )
            return None, None

        metadata = result.metadata or {}

        # Fast path: provider pre-parsed the response (Claude / vLLM constrained decoding)
        if isinstance(result.context, response_model):
            return result.context, metadata

        raw = (result.context or "").strip()

        # Strip markdown code fences if present
        if raw.startswith("```"):
            lines = raw.splitlines()
            body = lines[1:]
            if body and body[-1].startswith("```"):
                body = body[:-1]
            raw = "\n".join(body).strip()

        # Locate the JSON object
        if not raw.startswith("{"):
            start = raw.find("{")
            if start == -1:
                logger.warning(
                    "Split call '%s': no JSON object found in response | preview: %.200s",
                    call_name, raw,
                )
                return None, metadata
            raw = raw[start:]
            brace_count = 0
            for i, ch in enumerate(raw):
                if ch == "{":
                    brace_count += 1
                elif ch == "}":
                    brace_count -= 1
                    if brace_count == 0:
                        raw = raw[: i + 1]
                        break

        try:
            data = json.loads(raw)
            parsed: Any = response_model(**data)
            return parsed, metadata
        except Exception as exc:
            logger.warning(
                "Split call '%s' parse failed: %s | raw: %.200s",
                call_name, exc, raw,
            )
            self.trace_emitter.emit(
                f"split_call_{call_name}_parse_failed",
                level="warning",
                metadata={"error": str(exc), "response_preview": raw[:200]},
            )
            return None, metadata

    @staticmethod
    def _accumulate_metadata(
        base: Optional[Dict[str, Any]],
        extra: Optional[Dict[str, Any]],
    ) -> Dict[str, Any]:
        combined: Dict[str, Any] = dict(base or {})
        if not extra:
            return combined
        for key in ("prompt_tokens", "completion_tokens", "total_tokens"):
            combined[key] = combined.get(key, 0) + extra.get(key, 0)
        return combined

    async def generate_search_expansion_levels(
        self,
        *,
        search_input: SearchExpansionInput,
        model: Optional[str] = None,
        temperature: float = 0.2,
        max_tokens: int = 2048,
    ) -> tuple[SearchExpansionResponse, Dict[str, Any]]:
        """Agent D — block-aware, Cochrane-compliant search expansion.

        Level 1 is built deterministically in Python from Agent C's combined_blocks
        enriched with domain_terms from Agent B's concept_graph. The LLM is called
        to propose broadening candidates for Level 2 (and Level 3 when geography is
        present). Priority order for the block to broaden: geography → setting →
        population. When none of these blocks exist, only Level 1 is returned.
        """
        start_time = time.monotonic()
        from query_refinement_module.tracing import get_request_id, get_trace_id

        request_id = get_request_id() or "-"
        trace_id = get_trace_id() or "-"
        metadata: Dict[str, Any] = {"used_llm": False, "generated_level_count": 0}
        logger.info(
            "Starting Agent D search expansion",
            extra={
                "request_id": request_id,
                "trace_id": trace_id,
                "model": model,
                "anchor_block_count": len(search_input.anchor_blocks),
                "concept_graph_size": len(search_input.concept_graph),
            },
        )

        # ── Level 0: anchor (Agent C output, no domain_terms enrichment) ────────
        if search_input.keyword_structured:
            level0_query = search_input.keyword_structured
            _, level0_cv = build_level0_query(search_input.anchor_blocks)
        else:
            level0_query, level0_cv = build_level0_query(search_input.anchor_blocks)

        level0 = ExpansionLevel(
            level=0,
            label="Anchor query",
            search_query=level0_query,
            clarified_query=search_input.clarified_query,
            semantic_statement=search_input.semantic_statement,
            keyword_statement=search_input.keyword_statement or build_keyword_statement(search_input.anchor_blocks),
            controlled_vocabulary=level0_cv,
            blocks=list(search_input.anchor_blocks),
            rationale="Your refined query as-is — exact concepts from your refinement session, no broadening.",
            cochrane_compliant=False,
        )

        # ── Level 1: deterministic Python build ───────────────────────────────
        level1_query, level1_cv = build_level1_query(
            search_input.anchor_blocks, search_input.concept_graph
        )
        if not level1_query:
            metadata["status"] = "failed"
            metadata["warning"] = "No anchor blocks provided; cannot build Level 1."
            metadata["duration_ms"] = round((time.monotonic() - start_time) * 1000)
            logger.warning(
                "Agent D search expansion failed before LLM broadening",
                extra={
                    "request_id": request_id,
                    "trace_id": trace_id,
                    "duration_ms": metadata["duration_ms"],
                    "status": metadata["status"],
                },
            )
            return SearchExpansionResponse(), metadata

        level1_blocks = build_level1_blocks(
            search_input.anchor_blocks, search_input.concept_graph
        )

        level1 = ExpansionLevel(
            level=1,
            label="Full lexical ring",
            search_query=level1_query,
            clarified_query=search_input.clarified_query,
            semantic_statement=search_input.clarified_query,
            keyword_statement=build_keyword_statement(level1_blocks),
            controlled_vocabulary=level1_cv,
            blocks=level1_blocks,
            rationale="Searches using all the terms from your query, including synonyms, abbreviations, and related phrases. The most focused version of this search.",
            cochrane_compliant=False,
        )

        # ── Determine which block to broaden (geography → setting → population) ──
        geo_blocks = [b for b in search_input.anchor_blocks if b.role in GEOGRAPHY_ROLES]
        has_geography = bool(geo_blocks)

        if not has_geography:
            level0.cochrane_compliant = True
            level1.cochrane_compliant = True  # no geo restriction in play at any level

            setting_blocks = [b for b in search_input.anchor_blocks if b.role in SETTING_ROLES]
            pop_blocks = [b for b in search_input.anchor_blocks if b.role in POPULATION_ROLES]
            broadening_candidate = (setting_blocks or pop_blocks or [None])[0]

            if broadening_candidate is None:
                # Nothing to broaden — Level 1 is the Cochrane-sensitive search
                metadata["status"] = "completed_no_geography"
                metadata["generated_level_count"] = 1
                metadata["duration_ms"] = round((time.monotonic() - start_time) * 1000)
                logger.info(
                    "Completed Agent D search expansion",
                    extra={
                        "request_id": request_id,
                        "trace_id": trace_id,
                        "duration_ms": metadata["duration_ms"],
                        "generated_level_count": metadata["generated_level_count"],
                        "status": metadata["status"],
                        "used_llm": metadata["used_llm"],
                    },
                )
                return SearchExpansionResponse(
                    levels=[level0, level1],
                    geography_broadening_strategy="none",
                    recommended_starting_level=1,
                    recommendation_rationale="No geographic restriction detected; Level 1 is the Cochrane-sensitive search.",
                    search_filters=search_input.search_filters,
                    phrases=search_input.phrases,
                ), metadata

            broadened_role = broadening_candidate.role
        else:
            broadened_role = geo_blocks[0].role

        # ── LLM call: broadening proposals only ───────────────────────────────
        prompt_builder = SearchExpansionPromptBuilder()
        system_prompt = prompt_builder.get_system_prompt()
        user_prompt = prompt_builder.get_user_prompt(search_input, level1_query, broadened_role)

        parsed, call_meta = await self._execute_split_call(
            system_prompt,
            user_prompt,
            SearchExpansionLLMResponse,
            "search_expansion",
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            use_structured_output=False,  # model emits clean JSON from the prompt
        )
        metadata = self._accumulate_metadata(metadata, call_meta)

        if parsed is None or not isinstance(parsed, SearchExpansionLLMResponse):
            metadata["status"] = "failed"
            metadata["warning"] = "Agent D LLM call returned no parseable response."
            metadata["duration_ms"] = round((time.monotonic() - start_time) * 1000)
            logger.warning(
                "Agent D search expansion returned no parseable LLM response",
                extra={
                    "request_id": request_id,
                    "trace_id": trace_id,
                    "duration_ms": metadata["duration_ms"],
                    "status": metadata["status"],
                },
            )
            return SearchExpansionResponse(
                levels=[level0, level1],
                search_filters=search_input.search_filters,
                phrases=search_input.phrases,
            ), metadata

        metadata["used_llm"] = True

        # ── Build Level 2 (and Level 3) queries in Python ─────────────────────
        built_levels: List[ExpansionLevel] = [level1]
        for llm_level in parsed.levels:
            if has_geography:
                # Level 3 removes the geography block: LLM signals this with either
                # empty boolean_terms OR broadened_value == "(no restriction)".
                is_removal = (not llm_level.boolean_terms) or (
                    llm_level.broadened_value == "(no restriction)"
                )
            else:
                # Setting/population broadening: the block is never removed.
                if not llm_level.boolean_terms:
                    logger.warning(
                        "Agent D: LLM returned empty boolean_terms for non-geography "
                        "broadening at level %d — skipping level",
                        llm_level.level,
                    )
                    continue
                is_removal = False

            replacement_terms = [] if is_removal else llm_level.boolean_terms
            replacement_cv = llm_level.controlled_vocabulary_hints if not is_removal else None

            search_query, level_cv = build_leveln_query(
                search_input.anchor_blocks,
                search_input.concept_graph,
                broadened_role,
                replacement_terms,
            )
            if not search_query:
                continue

            level_blocks = build_leveln_blocks(
                search_input.anchor_blocks,
                search_input.concept_graph,
                broadened_role,
                replacement_terms,
                replacement_cv=replacement_cv,
            )

            built_levels.append(ExpansionLevel(
                level=llm_level.level,
                label=llm_level.label,
                search_query=search_query,
                clarified_query=llm_level.clarified_query or search_input.clarified_query,
                semantic_statement=llm_level.clarified_query or search_input.clarified_query,
                keyword_statement=build_keyword_statement(level_blocks),
                controlled_vocabulary=level_cv,
                blocks=level_blocks,
                broadened_aspect=broadened_role,
                broadened_value=llm_level.broadened_value,
                rationale=llm_level.rationale,
                cochrane_compliant=is_removal if has_geography else True,
            ))

        # ── Validate recommended_starting_level against generated levels ───────
        generated_level_numbers = {lv.level for lv in built_levels}
        rec = parsed.recommended_starting_level
        if rec not in generated_level_numbers:
            rec = min(generated_level_numbers) if generated_level_numbers else 1

        metadata["status"] = "completed"
        metadata["generated_level_count"] = len(built_levels)
        metadata["duration_ms"] = round((time.monotonic() - start_time) * 1000)
        logger.info(
            "Completed Agent D search expansion",
            extra={
                "request_id": request_id,
                "trace_id": trace_id,
                "duration_ms": metadata["duration_ms"],
                "generated_level_count": metadata["generated_level_count"],
                "status": metadata["status"],
                "used_llm": metadata["used_llm"],
            },
        )

        return SearchExpansionResponse(
            levels=[level0] + built_levels,
            geography_broadening_strategy=parsed.geography_broadening_strategy,
            recommended_starting_level=rec,
            recommendation_rationale=parsed.recommendation_rationale,
            search_filters=search_input.search_filters,
            phrases=search_input.phrases,
        ), metadata

    @staticmethod
    def _concept_graph_to_terminology(concept_graph: Dict[str, Any]) -> Terminology:
        synonyms: Dict[str, List[str]] = {}
        domain_specific: List[str] = []
        colloquial: List[str] = []
        for concept, entry in concept_graph.items():
            if hasattr(entry, "true_synonyms"):
                syns = list(entry.true_synonyms) + list(entry.abbreviations)
                if syns:
                    synonyms[concept] = syns
                domain_specific.extend(entry.domain_terms)
                colloquial.extend(entry.colloquial)
        return Terminology(
            synonyms=synonyms,
            domain_specific=list(dict.fromkeys(domain_specific)) or None,
            colloquial=list(dict.fromkeys(colloquial)),
        )

    def _parse_agent_response(self, raw: str, model_cls):
        """Strip markdown fences and parse JSON into model_cls."""
        raw = raw.strip()
        if raw.startswith("```"):
            lines = raw.splitlines()
            body = lines[1:]
            if body and body[-1].startswith("```"):
                body = body[:-1]
            raw = "\n".join(body).strip()
        start = raw.find("{")
        if start == -1:
            raise ValueError(f"{model_cls.__name__}: response contained no JSON object")
        decoder = json.JSONDecoder()
        obj, _ = decoder.raw_decode(raw, start)
        # Pre-decode any string-valued nested fields (Claude sometimes double-encodes them)
        for field in ("keyword", "search_filters"):
            v = obj.get(field)
            if isinstance(v, str):
                v = v.strip()
                s = v.find("{")
                if s != -1:
                    obj[field], _ = decoder.raw_decode(v, s)
        return model_cls(**obj)

    async def _run_normalization(
        self,
        session: "RefinementSession",
        *,
        model: Optional[str] = None,
        temperature: float = 0.2,
    ) -> Tuple[ResearchStatementResponse, Dict[str, Any]]:
        """Agent A: normalize statement from session query + dimensions."""
        aspects = [step.refinement_aspect for step in session.steps]
        assembled = self._assemble_dimensions_specifications(session) or {}
        builder = NormalizationPromptBuilder()
        completion = await self.llm_provider.complete_async(
            system_prompt=builder.get_system_prompt(),
            user_prompt=builder.get_user_prompt(
                original_input=session.original_query,
                aspectID_value_mapping=assembled,
                aspect_list=aspects,
            ),
            model=model,
            temperature=temperature,
            max_tokens=1024,
            response_format=ResearchStatementResponse,
            cache_system_prompt=False,
        )
        metadata = dict(completion.metadata or {})
        parsed = completion.context
        if isinstance(parsed, ResearchStatementResponse):
            return parsed, metadata
        return self._parse_agent_response(parsed or "", ResearchStatementResponse), metadata

    async def _run_semantic_representation(
        self,
        statement: str,
        *,
        model: Optional[str] = None,
        temperature: float = 0.2,
    ) -> Tuple[SemanticRepresentationResponse, Dict[str, Any]]:
        """Agent B: produce semantic_statement + keyword_statement + concept_graph from statement."""
        builder = SemanticRepresentationPromptBuilder()
        completion = await self.llm_provider.complete_async(
            system_prompt=builder.get_system_prompt(),
            user_prompt=builder.get_user_prompt(statement),
            model=model,
            temperature=temperature,
            max_tokens=2048,
            response_format=SemanticRepresentationResponse,
            cache_system_prompt=False,
        )
        metadata = dict(completion.metadata or {})
        parsed = completion.context
        if isinstance(parsed, SemanticRepresentationResponse):
            return parsed, metadata
        return self._parse_agent_response(parsed or "", SemanticRepresentationResponse), metadata

    async def _run_search_construction(
        self,
        statement: str,
        concept_graph: Dict[str, Any],
        *,
        model: Optional[str] = None,
        temperature: float = 0.2,
        max_tokens: Optional[int] = None,
        additional_guidance: Optional[str] = None,
    ) -> Tuple[SearchConstructionResponse, Dict[str, Any]]:
        """Agent C: build anchor keyword search + filters from statement and concept_graph."""
        builder = SearchConstructionPromptBuilder()
        concept_graph_dict = {
            k: (v.model_dump() if hasattr(v, "model_dump") else v)
            for k, v in concept_graph.items()
        }
        completion = await self.llm_provider.complete_async(
            system_prompt=builder.get_system_prompt(),
            user_prompt=builder.get_user_prompt(
                statement=statement,
                concept_graph=concept_graph_dict,
                additional_guidance=additional_guidance or "",
            ),
            model=model,
            temperature=temperature,
            max_tokens=max_tokens or 2048,
            response_format=SearchConstructionResponse,
            cache_system_prompt=False,
        )
        metadata = dict(completion.metadata or {})
        parsed = completion.context
        if isinstance(parsed, SearchConstructionResponse):
            return parsed, metadata
        return self._parse_agent_response(parsed or "", SearchConstructionResponse), metadata

    async def _run_monolithic_synthesis(
        self,
        session: "RefinementSession",
        *,
        model: Optional[str] = None,
        temperature: float = 0.2,
        max_tokens: Optional[int] = None,
        additional_guidance: Optional[str] = None,
    ) -> Tuple[QueryRefinementResponse, Dict[str, Any]]:
        """Execute the canonical single-call synthesis path."""
        resolved_model = model or getattr(self.llm_provider, "_default_model", None)

        aspects = [step.refinement_aspect for step in session.steps]
        prompt_builder = SynthesisPromptBuilder()
        assembled_dimensions = {
            aspect_id: value
            for aspect_id, value in (self._assemble_dimensions_specifications(session) or {}).items()
            if value is not None
        }
        user_prompt = prompt_builder.get_synthesis_prompt(
            original_input=session.original_query,
            aspectID_value_mapping=assembled_dimensions,
            aspect_list=aspects,
        )
        if additional_guidance:
            user_prompt = f"{user_prompt}\n\nADDITIONAL GUIDANCE:\n{additional_guidance.strip()}"

        completion = await self.llm_provider.complete_async(
            system_prompt=prompt_builder.get_system_prompt(),
            user_prompt=user_prompt,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            response_format=QueryRefinementResponse,
            cache_system_prompt=False,
        )

        metadata = dict(completion.metadata or {})
        parsed = completion.context
        if isinstance(parsed, QueryRefinementResponse):
            response = parsed
        else:
            raw = (parsed or "").strip()
            if raw.startswith("```"):
                lines = raw.splitlines()
                body = lines[1:]
                if body and body[-1].startswith("```"):
                    body = body[:-1]
                raw = "\n".join(body).strip()
            if not raw.startswith("{"):
                start = raw.find("{")
                if start == -1:
                    raise ValueError("Monolithic synthesis response did not contain a JSON object")
                raw = raw[start:]
            response = validate_synthesis_response(json.loads(raw))

        return response, metadata

    async def synthesize_refined_query(
        self,
        session: RefinementSession,
        *,
        model: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        additional_guidance: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Generate a refined query by combining the original query with clarifications.

        Args:
            session: Active refinement session containing user-provided clarifications.
            model: Optional model override for the synthesis call.
            temperature: Sampling temperature for the completion. Defaults to the
                manager-configured runtime value.
            max_tokens: Ceiling for any synthesis subcall. Defaults to the
                manager-configured runtime value.
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
        resolved_temperature = self.default_temperature if temperature is None else temperature
        resolved_max_tokens = self.default_max_tokens if max_tokens is None else max_tokens
        
        logger.info(
            "Starting query synthesis",
            extra={
                "request_id": request_id,
                "trace_id": trace_id,
                "model": model,
                "temperature": resolved_temperature,
                "max_tokens": resolved_max_tokens,
                "has_additional_guidance": additional_guidance is not None,
            },
        )

        clarifications, baseline_summaries = self._gather_refinement_details(session)
        deterministic_filters = self._assemble_deterministic_search_filters(session)

        # Build the native-value dimension map used internally by split synthesis.
        # The outward contract remains `dimensions_specifications`, which is the
        # deterministic serialized view persisted and returned elsewhere.
        canonical_dimensions = {}
        for step in session.steps:
            aspect_id = step.refinement_aspect.id
            # Check for non-empty value (None or empty string are considered "no value")
            if step.normalized_value is not None and step.normalized_value != "":
                # Use native value (dict/list/str/etc) - either extracted from original or from user dialogue
                canonical_dimensions[aspect_id] = step.normalized_value
            else:
                # No value: skipped explicitly (/skip), completed without value, or incomplete when /submit used
                # Mark as [SKIPPED] to indicate user did not consider this dimension important
                canonical_dimensions[aspect_id] = "[SKIPPED]"

        if not clarifications and not baseline_summaries:
            logger.info(
                "No refinement clarifications recorded (all dimensions skipped). "
                "Proceeding with LLM synthesis to generate semantic/keyword expansions from the original query.",
                extra={
                    "request_id": request_id,
                    "trace_id": trace_id,
                },
            )

        accepted_dimensions = {
            k: v for k, v in canonical_dimensions.items() if v != "[SKIPPED]"
        }

        self.trace_emitter.emit(
            "query_synthesis_start",
            metadata={
                "clarification_count": len(clarifications),
                "baseline_count": len(baseline_summaries),
                "model": model or "(default)",
                "model_override": model,
                "temperature": resolved_temperature,
                "max_tokens": resolved_max_tokens,
            },
        )

        try:
            agent_a_start = time.monotonic()
            logger.info(
                "Starting Agent A normalization",
                extra={"request_id": request_id, "trace_id": trace_id, "model": model},
            )
            norm, meta_a = await self._run_normalization(
                session,
                model=model,
                temperature=resolved_temperature,
            )
            logger.info(
                "Completed Agent A normalization",
                extra={
                    "request_id": request_id,
                    "trace_id": trace_id,
                    "duration_ms": round((time.monotonic() - agent_a_start) * 1000, 2),
                    "clarified_query_length": len(norm.clarified_query),
                },
            )
            agent_b_start = time.monotonic()
            logger.info(
                "Starting Agent B semantic representation",
                extra={"request_id": request_id, "trace_id": trace_id, "model": model},
            )
            sem, meta_b = await self._run_semantic_representation(
                norm.clarified_query,
                model=model,
                temperature=resolved_temperature,
            )
            logger.info(
                "Completed Agent B semantic representation",
                extra={
                    "request_id": request_id,
                    "trace_id": trace_id,
                    "duration_ms": round((time.monotonic() - agent_b_start) * 1000, 2),
                    "concept_graph_size": len(sem.concept_graph),
                    "semantic_statement_length": len(sem.semantic_statement),
                },
            )
            agent_c_start = time.monotonic()
            logger.info(
                "Starting Agent C search construction",
                extra={"request_id": request_id, "trace_id": trace_id, "model": model},
            )
            construction, meta_c = await self._run_search_construction(
                statement=norm.clarified_query,
                concept_graph=sem.concept_graph,
                model=model,
                temperature=resolved_temperature,
                max_tokens=resolved_max_tokens,
                additional_guidance=additional_guidance,
            )
            combined_blocks = getattr(construction.keyword, "combined_blocks", None) or []
            logger.info(
                "Completed Agent C search construction",
                extra={
                    "request_id": request_id,
                    "trace_id": trace_id,
                    "duration_ms": round((time.monotonic() - agent_c_start) * 1000, 2),
                    "combined_block_count": len(combined_blocks),
                    "has_search_filters": bool(construction.search_filters),
                },
            )
            aggregated_metadata = self._accumulate_metadata(
                self._accumulate_metadata(meta_a, meta_b), meta_c
            )
            synthesis_response = QueryRefinementResponse(
                clarified_query=norm.clarified_query,
                dimensions_specifications=norm.dimensions_specifications,
                search_optimized=SearchOptimized(
                    semantic=sem.semantic_statement,
                    keyword=construction.keyword,
                ),
                search_filters=construction.search_filters,
                terminology=self._concept_graph_to_terminology(sem.concept_graph),
            )
        except Exception as exc:
            logger.exception("Query synthesis failed: %s", exc)
            self.trace_emitter.emit(
                "query_synthesis_error",
                level="error",
                metadata={"error": str(exc)},
            )
            raise

        self.trace_emitter.emit(
            "query_synthesis_complete",
            metadata={
                "clarification_count": len(clarifications),
                "baseline_count": len(baseline_summaries),
                "response_length": len(synthesis_response.clarified_query),
                "structured_response": True,
                "duration_ms": aggregated_metadata.get("duration_ms", 0),
                "prompt_tokens": aggregated_metadata.get("prompt_tokens", 0),
                "completion_tokens": aggregated_metadata.get("completion_tokens", 0),
                "total_tokens": aggregated_metadata.get("total_tokens", 0),
                "prompt_char_count": aggregated_metadata.get("prompt_char_count", 0),
                "estimated_prompt_tokens": aggregated_metadata.get("estimated_prompt_tokens", 0),
                "call_timings": aggregated_metadata.get("call_timings", {}),
                "parallel_timing": aggregated_metadata.get("parallel_timing", {}),
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
                "response_length": len(synthesis_response.clarified_query),
                "structured_response": True,
                "synthesis_duration_ms": aggregated_metadata.get("duration_ms", 0),
                "prompt_tokens": aggregated_metadata.get("prompt_tokens", 0),
                "completion_tokens": aggregated_metadata.get("completion_tokens", 0),
                "prompt_char_count": aggregated_metadata.get("prompt_char_count", 0),
                "estimated_prompt_tokens": aggregated_metadata.get("estimated_prompt_tokens", 0),
                "call_timings": aggregated_metadata.get("call_timings", {}),
                "parallel_timing": aggregated_metadata.get("parallel_timing", {}),
            },
        )

        result_dict = {
            "clarified_query": synthesis_response.clarified_query,
            "keyword_statement": sem.keyword_statement,
            "used_llm": True,
            "clarifications": clarifications,
            "baseline_summaries": baseline_summaries,
            "metadata": aggregated_metadata,
            "dimensions_specifications": synthesis_response.dimensions_specifications,
            "search_optimized": synthesis_response.search_optimized,
            "search_filters": synthesis_response.search_filters,
            "terminology": synthesis_response.terminology,
            "concept_graph": {
                k: (v.model_dump() if hasattr(v, "model_dump") else v)
                for k, v in sem.concept_graph.items()
            },
        }

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
                "name": step.refinement_aspect.name,
                "aspect_name": step.refinement_aspect.name,
                "description": step.refinement_aspect.description,
                "is_complete": step.is_complete,
                "was_skipped": step.was_skipped,
            }

            if step.is_complete and step.normalized_value_as_str:
                aspect_info["final_value"] = step.normalized_value_as_str
            
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