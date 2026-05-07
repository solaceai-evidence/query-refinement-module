"""
Query refinement workflow API routes with comprehensive logging and tracing.

Integrates the core refinement pipeline with API endpoints.

Key Features:
- Request ID generation for distributed tracing
- Comprehensive logging at all stages
- LLM metadata capture (tokens, cost, duration)
- Database metadata persistence
- Performance monitoring
- Error handling with detailed context
- Webhook event notifications for external integrations
"""
import asyncio
import json
import logging
import time
from fastapi import APIRouter, Depends, HTTPException, status, Request
from sqlalchemy.orm import Session
from typing import Dict, Any, Optional, Union, List

logger = logging.getLogger(__name__)

from query_refinement_module.db.session import get_db
from query_refinement_module.db.crud import (
    create_query_session,
    create_query,
    get_query,
    update_refined_query,
    create_refinement_step,
    get_query_refinement_steps,
    create_followup,
    delete_refinement_steps_by_aspects,
    reset_refinement_step,
    abandon_query_session,
    get_user_framework_names,
    user_has_framework_access,
    update_refinement_step_generated_question,
)
from query_refinement_module.api.auth import get_current_user_or_integration
from query_refinement_module.api.config import get_settings
from query_refinement_module.api.dependencies import get_refinement_manager, get_session_manager
from query_refinement_module.schema.registry import get_framework, list_frameworks
from query_refinement_module.api.session_manager import SessionManager
from query_refinement_module.audit import audit_service
from query_refinement_module.db.models.audit_log import AuditEventType
from query_refinement_module.settings import LLMSettings
from query_refinement_module.core import (
    QueryRefinementManager,
    is_user_command,
    parse_user_command,
    UserCommand,
)
from query_refinement_module.tracing import generate_request_id, get_logger, set_request_id
from query_refinement_module.services.progress_tracker import get_progress_tracker, track_progress
from query_refinement_module.models.progress import ProgressStage
from query_refinement_module.schema import DimensionEvaluationResponse

from pydantic import BaseModel, Field, field_validator, AnyHttpUrl


router = APIRouter(prefix="/refinement", tags=["Query Refinement Workflow"])


# ==========================================
# Request/Response Models
# ==========================================

class StartRefinementRequest(BaseModel):
    """Request to start a new refinement workflow."""
    original_query: str = Field(
        ..., 
        min_length=3,
        max_length=5000,
        description="The query to refine"
    )
    framework_name: str = Field(
        ..., 
        min_length=1,
        max_length=128,
        description="Name of the refinement framework to use"
    )
    source: str = Field(
        default="gui",
        description="Request origin channel: gui or api_integration",
    )
    skip_refinement: bool = Field(
        default=False,
        description="When True, skip all refinement dimensions and go straight to synthesis. "
                    "No per-dimension LLM calls are made; only the synthesis LLM call is used."
    )

    @field_validator('original_query')
    @classmethod
    def query_not_empty(cls, v: str) -> str:
        """Validate that query is not just whitespace."""
        if not v or not v.strip():
            raise ValueError("Query cannot be empty or just whitespace")
        if len(v.strip()) < 3:
            raise ValueError("Query must be at least 3 characters long")
        return v.strip()
    
    @field_validator('framework_name')
    @classmethod
    def framework_not_empty(cls, v: str) -> str:
        """Validate that framework name is not just whitespace."""
        if not v or not v.strip():
            raise ValueError("Framework name cannot be empty or just whitespace")
        return v.strip()

    @field_validator('source')
    @classmethod
    def validate_source(cls, v: str) -> str:
        """Validate supported request sources."""
        normalized = (v or '').strip().lower()
        if normalized not in {"gui", "api_integration"}:
            raise ValueError("source must be one of: gui, api_integration")
        return normalized


class StartRefinementResponse(BaseModel):
    """Response with session details and initialization summary."""
    session_id: int = Field(..., description="Database session ID")
    query_id: int = Field(..., description="Database query ID")
    summary: Dict[str, Any] = Field(..., description="Initialization analysis summary")
    next_prompt: Optional[Dict[str, Any]] = Field(None, description="Next question for the user")
    ready_for_synthesis: bool = Field(False, description="True if all aspects are complete and ready for synthesis")
    source: str = Field(..., description="Request origin channel")
    synthesis: Optional["SynthesizeQueryResponse"] = Field(
        None,
        description="Populated when skip_refinement=True: full synthesis result embedded "
                    "in the start response so no follow-up /synthesize call is needed."
    )


class SubmitAnswerRequest(BaseModel):
    """Request to submit an answer to a refinement question."""
    answer: str = Field(
        ..., 
        min_length=1,
        max_length=2000,
        description="User's answer to the current question or a command (e.g., /status, /back)"
    )
    force: Optional[bool] = Field(
        False,
        description="Force navigation commands that invalidate dependent aspects"
    )
    
    @field_validator('answer')
    @classmethod
    def answer_not_empty(cls, v: str) -> str:
        """Validate that answer is not just whitespace."""
        if not v or not v.strip():
            raise ValueError("Answer cannot be empty or just whitespace")
        return v.strip()


class SubmitAnswerResponse(BaseModel):
    """Response after processing user's answer."""
    refinement_step_id: int = Field(..., description="ID of the refinement step")
    followup_id: int = Field(..., description="ID of the follow-up entry")
    is_complete: bool = Field(..., description="Whether the aspect is complete")
    next_prompt: Optional[Dict[str, Any]] = Field(None, description="Next question if follow-up needed")
    ready_for_synthesis: bool = Field(False, description="True if all aspects are complete and ready for synthesis")


class CommandResponse(BaseModel):
    """Response when user issues a command instead of answering."""
    command_type: str = Field(..., description="Type of command executed (status, back, skip, etc.)")
    success: bool = Field(..., description="Whether command executed successfully")
    message: str = Field(..., description="Human-readable feedback message")
    next_prompt: Optional[Dict[str, Any]] = Field(None, description="Next question after command execution")
    
    # Optional fields for specific commands
    invalidated_aspects: Optional[List[str]] = Field(None, description="Aspects marked for review (/back, /restart)")
    synthesis_ready: bool = Field(False, description="True if session ready for synthesis (/submit)")
    step_summary: Optional[Dict[str, Any]] = Field(None, description="Step statistics (/status)")
    step_list: Optional[List[Dict[str, Any]]] = Field(None, description="All steps with status (/steps)")
    force_required: Optional[bool] = Field(None, description="True if command requires force=true flag")


class GetRefinementStatusResponse(BaseModel):
    """Current status of a refinement workflow."""
    query_id: int
    original_query: str
    refined_query: Optional[str]
    is_complete: bool
    current_aspect: Optional[str]
    aspects_summary: Dict[str, Any]
    next_prompt: Optional[Dict[str, Any]] = Field(None, description="Next question for the user")
    ready_for_synthesis: bool = Field(False, description="True if all aspects are complete and ready for synthesis")
    aspects: List[Dict[str, Any]] = Field(default_factory=list, description="List of aspect summaries")
    conversation_history: List[Dict[str, Any]] = Field(default_factory=list, description="Full conversation history for UI restoration")


class SynthesizeQueryRequest(BaseModel):
    """Request to synthesize the refined query."""
    query_id: int = Field(..., gt=0, description="ID of the query to synthesize")


class SynthesizeQueryResponse(BaseModel):
    """Response with synthesized refined query."""
    query_id: int
    integrated_statement: str
    used_llm: bool
    structured_output: Optional[Dict[str, Any]] = None


class ForwardToQARequest(BaseModel):
    """Request to forward refined query to external QA system."""
    qa_system_url: AnyHttpUrl = Field(
        ...,
        description="URL of the external question-answering system"
    )
    qa_system_auth: Optional[Dict[str, str]] = Field(
        None,
        description="Authentication headers for the QA system (e.g., {'Authorization': 'Bearer token'})"
    )
    timeout_seconds: int = Field(
        default=30,
        ge=5,
        le=120,
        description="Request timeout in seconds"
    )
    include_refinement_metadata: bool = Field(
        default=True,
        description="Include refinement metadata in the request to QA system"
    )
    forward_original_query: bool = Field(
        default=False,
        description="Also include the original query alongside the refined query"
    )


class ForwardToQAResponse(BaseModel):
    """Response from forwarding to external QA system."""
    query_id: int
    refined_query: str
    original_query: Optional[str] = None
    qa_system_url: str
    qa_system_response: Dict[str, Any]
    qa_system_status_code: int
    response_time_ms: int
    refinement_metadata: Optional[Dict[str, Any]] = None


# ==========================================
# Utility Functions
# ==========================================

async def _generate_question_with_retry(
    manager,
    session,
    aspect_id: str,
    mode: str = 'initial',
    max_retries: int = 1
):
    """
    Generate question with retry logic and exponential backoff.
    
    Args:
        manager: QueryRefinementManager instance
        session: QueryRefinementSession instance
        aspect_id: ID of the aspect to generate question for
        mode: 'initial' or 'followup'
        max_retries: Maximum number of retry attempts (default: 1)
    
    Returns:
        DimensionEvaluationResponse from LLM
    
    Raises:
        Exception: If all retry attempts fail
    """
    last_error = None
    
    for attempt in range(max_retries + 1):
        try:
            if attempt > 0:
                # Exponential backoff: 2^attempt seconds
                delay = 2 ** attempt
                logger.info(f"Retry attempt {attempt}/{max_retries} after {delay}s delay for aspect {aspect_id}")
                await asyncio.sleep(delay)
            
            result = await manager.get_analysis_prompts(
                session=session,
                aspect_id=aspect_id,
                mode=mode
            )
            return result
            
        except Exception as e:
            last_error = e
            logger.warning(f"LLM call failed (attempt {attempt + 1}/{max_retries + 1}): {e}")
            
            if attempt >= max_retries:
                raise last_error
    
    # Should never reach here, but for type safety
    raise last_error if last_error else Exception("Question generation failed")


def _deserialize_refinement_value(value: Optional[str]) -> Optional[Any]:
    """Deserialize persisted final_value into a native python value when possible."""
    if value is None:
        return None

    if not isinstance(value, str):
        return value

    stripped = value.strip()
    if not stripped:
        return value

    if stripped[0] in ["{", "["]:
        try:
            return json.loads(stripped)
        except Exception:
            return value

    return value


def _restore_session_from_db_state(session, db_steps: List[Any]) -> None:
    """Restore in-memory session state from persisted DB refinement step rows."""
    for db_step in db_steps:
        session_step = next(
            (s for s in session.steps if s.refinement_aspect.name == db_step.aspect_name),
            None
        )
        if not session_step:
            continue

        # Restore follow-up history
        for followup in db_step.followup_history:
            session_step.conversation_history.append({
                'question': followup.question,
                'response': followup.answer or ''
            })

        # Restore the persisted question regardless of whether there is conversation
        # history.  A question may have been generated by the LLM but not yet
        # answered (no followup_history row), so we must restore it from
        # db_step.generated_question to avoid requiring another costly LLM call.
        if db_step.generated_question:
            session_step.follow_up_question = db_step.generated_question
        elif session_step.conversation_history:
            # Fallback: derive from the last answered exchange
            last_followup = db_step.followup_history[-1]
            session_step.follow_up_question = last_followup.question

        # Restore persisted final value (supports /done with partial value and no follow-up rows)
        has_final_value = db_step.final_value is not None and str(db_step.final_value).strip() != ""
        if has_final_value:
            session_step.normalized_value = _deserialize_refinement_value(db_step.final_value)

        # Restore completion semantics from DB truth
        session_step.was_skipped = bool(db_step.was_skipped)
        session_step.is_complete = bool(
            db_step.is_complete
            or db_step.was_skipped
            or db_step.user_ended_early
            or has_final_value
            or session_step.conversation_history
        )

        # Explicit skip with no value should remain value-less
        if session_step.was_skipped and not has_final_value:
            session_step.normalized_value = None


async def _build_next_prompt(manager, session) -> Optional[Dict[str, Any]]:
    """
    Build the next prompt from the next unrefined aspect in dependency order.
    
    Analyzes dimensions with LLM to determine if they're already clear, auto-completing
    when possible and only asking questions when clarification is truly needed.
    
    Uses get_next_unrefined_aspect() for sequential on-demand refinement.
    """
    max_attempts = 10  # Prevent infinite loop
    attempts = 0
    
    while attempts < max_attempts:
        attempts += 1
        step = session.get_next_unrefined_aspect()
        
        logger.info(f"_build_next_prompt attempt {attempts}: next_unrefined_aspect={'exists' if step else 'None'}")
        if not step:
            logger.info("  -> No unrefined aspects remaining, returning None")
            return None
        
        # If question already exists (from previous analysis), use it
        if step.follow_up_question:
            result = {
                "aspect_id": step.refinement_aspect.id,
                "name": step.refinement_aspect.name,
                "question": step.follow_up_question,
                "description": step.refinement_aspect.description or "",
            }
            logger.info(f"  -> Using existing question for '{result['name']}', question: '{result['question'][:100]}...")
            return result
        
        # No question exists - analyze with LLM to determine if dimension is already clear
        try:
            import time
            llm_start = time.time()
            logger.info(f"  -> Generating question via LLM analysis for aspect '{step.refinement_aspect.name}'")
            logger.info(f"  -> Aspect ID: {step.refinement_aspect.id}, mode: initial")
            
            # Call LLM to analyze dimension with full context
            analysis_result = await _generate_question_with_retry(
                manager=manager,
                session=session,
                aspect_id=step.refinement_aspect.id,
                mode='initial'
            )
            
            llm_duration = (time.time() - llm_start) * 1000
            logger.info(f"  -> LLM call completed in {llm_duration:.2f}ms for aspect '{step.refinement_aspect.name}'")
            
            # Process the analysis
            status = manager.process_analysis_result(
                session=session,
                aspect_id=step.refinement_aspect.id,
                result=analysis_result
            )
            
            if status['complete']:
                # Dimension is already clear - auto-completed, loop to next
                logger.info(f"  -> Dimension '{step.refinement_aspect.name}' auto-completed with value: {str(status.get('current', ''))[:100]}")
                continue
            else:
                # Dimension needs clarification - return the question
                result = {
                    "aspect_id": step.refinement_aspect.id,
                    "name": step.refinement_aspect.name,
                    "question": status['next_question'],
                    "description": step.refinement_aspect.description or "",
                }
                logger.info(f"  -> Generated question for '{result['name']}', question: '{result['question'][:100]}...")
                return result
                
        except Exception as e:
            # LLM failed - use simple fallback
            logger.error(f"  -> LLM analysis failed for aspect '{step.refinement_aspect.name}': {e}")
            fallback_question = f"Please provide details about {step.refinement_aspect.name}"
            step.follow_up_question = fallback_question
            
            result = {
                "aspect_id": step.refinement_aspect.id,
                "name": step.refinement_aspect.name,
                "question": fallback_question,
                "description": step.refinement_aspect.description or "",
            }
            logger.info(f"  -> Using fallback question for '{result['name']}'")
            return result
    
    # Max attempts reached without finding a dimension that needs clarification
    logger.warning(f"_build_next_prompt: Max attempts ({max_attempts}) reached")
    return None


def _persist_generated_question(
    db,
    db_steps: List,
    next_prompt: Optional[Dict[str, Any]],
) -> None:
    """Persist a generated question to DB so it survives server restarts."""
    if not next_prompt or not db:
        return
    aspect_name = next_prompt.get("name")
    question = next_prompt.get("question")
    if not aspect_name or not question:
        return
    db_step = next((s for s in db_steps if s.aspect_name == aspect_name), None)
    if db_step:
        try:
            update_refinement_step_generated_question(db, db_step.id, question)
        except Exception as e:
            logger.warning(f"Could not persist generated_question for '{aspect_name}': {e}")


def _get_active_prompt(session) -> Optional[Dict[str, Any]]:
    """Return the currently active question if it already exists in session state."""
    active_step = session.get_active_step()
    if not active_step:
        return None

    if active_step.follow_up_question:
        return {
            "aspect_id": active_step.refinement_aspect.id,
            "name": active_step.refinement_aspect.name,
            "question": active_step.follow_up_question,
            "description": active_step.refinement_aspect.description or "",
        }

    return None


def _is_session_ready_for_synthesis(session) -> bool:
    """Return True when synthesis can be safely executed for a session."""
    if not session:
        return False
    return bool(session.synthesis_requested or session.is_complete())


async def _build_command_response(
    manager,
    command_type: str,
    payload: Dict[str, Any],
    session,
    force_confirmation_needed: bool = False,
    db=None,
    query_id: Optional[int] = None,
    db_steps: Optional[List] = None,
) -> CommandResponse:
    """Build CommandResponse based on command type and execution payload.
    
    Args:
        command_type: The command type (status, back, restart, etc.)
        payload: Result from session.handle_command()
        session: QueryRefinementSession instance
        force_confirmation_needed: Whether force flag is required
    
    Returns:
        CommandResponse with appropriate fields populated
    """
    logger.info(f"[_build_command_response] Building response for command: {command_type}")
    
    success = payload.get("success", False)
    message = payload.get("message", "")
    
    logger.info(f"[_build_command_response] Command success: {success}, message: {message[:100]}")
    
    # Build base response
    response = CommandResponse(
        command_type=command_type,
        success=success,
        message=message,
        next_prompt=None,
        invalidated_aspects=None,
        synthesis_ready=False,
        step_summary=None,
        step_list=None,
        force_required=None
    )
    
    # If command failed or needs force confirmation, preserve current prompt
    if not success or force_confirmation_needed:
        logger.info(f"[_build_command_response] Command failed or needs confirmation, preserving current prompt")
        response.next_prompt = _get_active_prompt(session) or await _build_next_prompt(manager, session)
        _persist_generated_question(db, db_steps or [], response.next_prompt)
        if force_confirmation_needed:
            response.force_required = True
            response.invalidated_aspects = payload.get("invalidated", [])
        return response
    
    # Command-specific response fields
    if command_type in ["status"]:
        logger.info(f"[_build_command_response] STATUS command - adding step summary")
        response.step_summary = payload.get("summary")
        # Read-only command: never trigger an LLM call, use cached prompt only
        response.next_prompt = _get_active_prompt(session)
        response.synthesis_ready = _is_session_ready_for_synthesis(session)
    
    elif command_type in ["steps"]:
        logger.info(f"[_build_command_response] STEPS command - building step list")
        # Serialize steps to JSON-compatible format
        steps = payload.get("steps", [])
        active_step = session.get_active_step()
        if steps:
            response.step_list = [
                {
                    "name": step.refinement_aspect.name,
                    "aspect_id": step.refinement_aspect.id,
                    "is_complete": step.is_complete,
                    "needs_review": step.needs_review,
                    "was_skipped": step.was_skipped,
                    "follow_up_count": step.follow_up_count,
                    "status": (
                        "completed" if step.is_complete and not step.needs_review else
                        "needs review" if step.needs_review else
                        "active" if step == active_step else
                        "not started"
                    ),
                    "is_active": step == active_step
                }
                for step in steps
            ]
            logger.info(f"[_build_command_response] Built step list with {len(response.step_list)} steps")
        # Read-only command: never trigger an LLM call, use cached prompt only
        response.next_prompt = _get_active_prompt(session)
    
    elif command_type in ["help"]:
        logger.info(f"[_build_command_response] HELP command - showing help text")
        # Read-only command: never trigger an LLM call, use cached prompt only
        response.next_prompt = _get_active_prompt(session)
    
    elif command_type in ["submit", "end"]:
        logger.info(f"[_build_command_response] SUBMIT/END command - marking synthesis ready")
        response.synthesis_ready = True
        response.next_prompt = None
    
    elif command_type in ["clear"]:
        logger.info(f"[_build_command_response] CLEAR command - regenerating question for current aspect")
        # Clear command - regenerate question for current aspect
        response.next_prompt = await _build_next_prompt(manager, session)
        _persist_generated_question(db, db_steps or [], response.next_prompt)
        logger.info(f"[_build_command_response] Next prompt: {'exists' if response.next_prompt else 'None'}")
        if response.next_prompt:
            logger.info(f"[_build_command_response]   -> Aspect: {response.next_prompt.get('name')}")
    
    elif command_type in ["back", "prev", "previous", "restart"]:
        logger.info(f"[_build_command_response] NAVIGATION command ({command_type}) - building next prompt")
        # Navigation commands - show new active step
        response.invalidated_aspects = payload.get("invalidated", [])
        
        # For back/restart, explicitly generate question for reopened step
        # Don't allow LLM to auto-complete it again
        if command_type in ["back", "restart"]:
            reopened_step = session.get_active_step()
            if reopened_step and not reopened_step.follow_up_question:
                # Force generate a question (don't auto-complete)
                from query_refinement_module.schema.prompt_builder import PromptBuilder
                prompt_builder = PromptBuilder()
                aspect = reopened_step.refinement_aspect
                
                logger.info(f"[NAVIGATION] Generating fresh question for reopened dimension: {aspect.name}")
                logger.info(f"[NAVIGATION] Conversation history length: {len(reopened_step.conversation_history)}")
                logger.info(f"[NAVIGATION] Has normalized_value: {reopened_step.normalized_value is not None}")
                
                try:
                    # Build messages for initial question generation
                    messages = prompt_builder.build_refinement_messages(
                        dimension=aspect,
                        query=session.original_query,
                        conversation_history=[],  # Force empty to ensure fresh question
                        dependency_context=session.get_dependency_context(aspect.id),
                        completed_context=session.get_completed_context(aspect.id),
                        terminal_reinforcement_threshold=getattr(manager, "terminal_reinforcement_threshold", 3),
                    )
                    
                    # Add explicit instruction to ALWAYS ask a clarifying question
                    if messages and messages[-1].get("role") == "user":
                        messages[-1]["content"] += "\n\nCRITICAL: The user has navigated back to review this dimension from scratch. The dimension has been completely reset with no previous values. You MUST ask a clarifying question as if this is the very first time asking about this dimension. Do NOT assume anything is already clear - treat this as a fresh initial question."
                    
                    logger.info(f"[NAVIGATION] Calling LLM to generate fresh question...")
                    llm_result = await manager.llm_provider.complete_async(
                        messages=messages,
                        temperature=0.0,
                        response_format=DimensionEvaluationResponse,
                        cache_system_prompt=True,
                    )

                    logger.info(f"[NAVIGATION] LLM response received, parsing...")
                    llm_context = llm_result.context
                    generated_question = None

                    if isinstance(llm_context, DimensionEvaluationResponse):
                        generated_question = llm_context.question
                    elif isinstance(llm_context, dict):
                        generated_question = llm_context.get("question") or llm_context.get("next_question")
                    elif isinstance(llm_context, str):
                        cleaned = llm_context.strip()
                        if cleaned.startswith("```"):
                            lines = cleaned.splitlines()
                            body = lines[1:]
                            if body and body[-1].startswith("```"):
                                body = body[:-1]
                            cleaned = "\n".join(body).strip()
                        try:
                            parsed = json.loads(cleaned)
                            generated_question = parsed.get("question") or parsed.get("next_question")
                        except Exception:
                            generated_question = None

                    if generated_question and isinstance(generated_question, str) and generated_question.strip():
                        reopened_step.follow_up_question = generated_question.strip()
                        logger.info(f"[NAVIGATION] ✓ Using LLM-generated question: {reopened_step.follow_up_question[:100]}...")
                    else:
                        # Fallback if LLM didn't generate a usable question
                        logger.warning(f"[NAVIGATION] LLM did not generate proper question, using fallback")
                        reopened_step.follow_up_question = f"Let's review {aspect.name} for your research query. What would you like to specify for this dimension?"
                except Exception as e:
                    logger.error(f"[NAVIGATION] Error generating question for reopened step: {e}")
                    logger.exception(e)  # Full stack trace
                    # Fallback question - neutral wording since we cleared previous values
                    reopened_step.follow_up_question = f"Let's review {aspect.name} for your research query. What would you like to specify for this dimension?"
        
        response.next_prompt = await _build_next_prompt(manager, session)
        _persist_generated_question(db, db_steps or [], response.next_prompt)
        logger.info(f"[_build_command_response] Next prompt: {'exists' if response.next_prompt else 'None'}")
        if response.next_prompt:
            logger.info(f"[_build_command_response]   -> Aspect: {response.next_prompt.get('name')}")
    
    elif command_type in ["skip", "done"]:
        logger.info(f"[_build_command_response] CONTROL command ({command_type}) - advancing to next step")
        # Control commands - advance to next step with LLM analysis and auto-completion
        response.next_prompt = await _build_next_prompt(manager, session)
        _persist_generated_question(db, db_steps or [], response.next_prompt)
        logger.info(f"[_build_command_response] Next prompt: {'exists' if response.next_prompt else 'None'}")
        if response.next_prompt:
            has_question = bool(response.next_prompt.get('question'))
            logger.info(f"[_build_command_response]   -> Aspect: {response.next_prompt.get('name')}, has question: {has_question}")
            if has_question:
                logger.info(f"[_build_command_response]   -> Question preview: {response.next_prompt.get('question')[:100]}")
        else:
            # No more dimensions - check if ready for synthesis
            logger.info(f"[_build_command_response]   -> No next prompt, checking if session is complete")
            if session.is_complete():
                logger.info(f"[_build_command_response]   -> ✓ All dimensions complete - setting synthesis_ready=True")
                response.synthesis_ready = True
            else:
                logger.warning(f"[_build_command_response]   -> ⚠️ No next prompt but session not complete - unexpected state")

    # Ensure response contract stays explicit for integrations
    if not response.synthesis_ready:
        response.synthesis_ready = _is_session_ready_for_synthesis(session)
    
    logger.info(f"[_build_command_response] Response built successfully - next_prompt: {'yes' if response.next_prompt else 'no'}, synthesis_ready: {response.synthesis_ready}")
    return response


# ==========================================
# Refinement Workflow Endpoints
# ==========================================

@router.get("/frameworks")
def get_available_frameworks(
    current_user = Depends(get_current_user_or_integration),
    db: Session = Depends(get_db),
):
    """
    List all available refinement frameworks.
    """
    frameworks = list_frameworks()
    if not current_user.is_superuser:
        allowed = set(get_user_framework_names(db, current_user.id))
        frameworks = [name for name in frameworks if name in allowed]

    return {
        "frameworks": frameworks,
        "count": len(frameworks)
    }


@router.post("/start", response_model=StartRefinementResponse, status_code=status.HTTP_201_CREATED)
async def start_refinement(
    request: StartRefinementRequest,
    manager: QueryRefinementManager = Depends(get_refinement_manager),
    current_user = Depends(get_current_user_or_integration),
    db: Session = Depends(get_db),
    session_manager: SessionManager = Depends(get_session_manager)
):
    """
    Start a new query refinement workflow using sequential on-demand mode.
    
    This initializes a refinement session by:
    1. Loading the specified framework
    2. Creating session WITHOUT upfront LLM analysis
    3. Creating database records for session, query, and steps
    4. Generating first question on-demand and returning it
    
    Aspects are refined sequentially in dependency order, one at a time.
    """
    import time
    from query_refinement_module.tracing import generate_request_id, set_request_id, get_request_id
    
    # Generate and set request ID for tracing
    request_id = generate_request_id()
    set_request_id(request_id)
    
    start_time = time.time()
    settings = get_settings()
    
    # Check if user can start new workflow
    if settings.enforce_workflow_limit and not current_user.is_superuser and current_user.has_completed_workflow:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You have already completed one refinement workflow. "
                   "For evaluation purposes, only one workflow per participant is allowed. "
                   "Thank you for your participation!"
        )

    if (
        not current_user.is_superuser
        and not user_has_framework_access(db, current_user.id, request.framework_name)
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"You are not authorized to use framework '{request.framework_name}'"
        )
    
    logger.info(
        "API: Starting refinement workflow",
        extra={
            "request_id": request_id,
            "user_id": current_user.id,
            "framework_name": request.framework_name,
            "query_length": len(request.original_query),
            "source": request.source,
        },
    )
    
    # Get the refinement framework
    try:
        framework = get_framework(request.framework_name)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Framework '{request.framework_name}' not found: {str(e)}"
        )
    
    # Initialize the refinement session using sequential mode (no upfront analysis)
    try:
        session = await asyncio.to_thread(
            manager.initialize_sequential,
            request.original_query,
            framework,
        )
    except ConnectionError as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Unable to connect to LLM service: {str(e)}"
        )
    except TimeoutError as e:
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail=f"LLM service request timed out: {str(e)}"
        )
    except Exception as e:
        logger.error(f"Error initializing refinement session: {str(e)}", exc_info=True)
        
        # Check for specific LLM errors
        error_str = str(e).lower()
        if "credit balance" in error_str or "insufficient" in error_str:
            raise HTTPException(
                status_code=status.HTTP_402_PAYMENT_REQUIRED,
                detail="LLM service credits exhausted. Please configure valid API credentials."
            )
        elif "api key" in error_str or "authentication" in error_str:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="LLM service authentication error. Please check API configuration."
            )
        elif "rate limit" in error_str:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="LLM service rate limit exceeded. Please try again later."
            )
        else:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to initialize refinement. LLM service may be unavailable."
            )
    
    # Create database records
    db_session = create_query_session(db, user_id=current_user.id, framework_name=request.framework_name)
    db_query = create_query(db, session_id=db_session.id, original_query=request.original_query)
    
    # Initialize progress tracking
    tracker = get_progress_tracker()
    try:
        await tracker.create(
            query_id=str(db_query.id),
            initial_stage=ProgressStage.EXTRACTING_ASPECTS,
            initial_message=f"Analyzing query structure with {request.framework_name} framework..."
        )
    except Exception as progress_err:
        # Log but don't fail if progress tracking fails
        logger.error(f"Failed to create progress tracking: {progress_err}", exc_info=True)
    
    # Create refinement steps in database
    for step in session.steps:
        create_refinement_step(
            db,
            query_id=db_query.id,
            aspect_name=step.refinement_aspect.name
        )

    # ── Fast path: skip all refinements, go straight to synthesis ──────────
    if request.skip_refinement:
        from query_refinement_module.db.crud import mark_refinement_step_skipped

        # Mark every in-memory step as skipped so is_complete() returns True
        for step in session.steps:
            step.is_complete = True
            step.was_skipped = True
        session.synthesis_requested = True

        # Persist the skip in the database for audit / session reconstruction
        db_steps = get_query_refinement_steps(db, db_query.id)
        for db_step in db_steps:
            mark_refinement_step_skipped(db, db_step.id)

        # Save session to Redis so _run_synthesis can load it
        session_manager.save_session(db_query.id, session)

        await track_progress(
            query_id=str(db_query.id),
            stage=ProgressStage.SUGGESTIONS_READY,
            message="All refinements skipped, proceeding to synthesis"
        )

        logger.info(
            "API: Refinement workflow started (skip_refinement=True) – running synthesis inline",
            extra={
                "request_id": request_id,
                "user_id": current_user.id,
                "session_id": db_session.id,
                "query_id": db_query.id,
                "total_aspects": len(session.steps),
            },
        )

        synthesis_response = await _run_synthesis(
            manager=manager,
            session=session,
            db=db,
            db_query=db_query,
            current_user=current_user,
            session_manager=session_manager,
            query_id=db_query.id,
            request_id=request_id,
        )

        return StartRefinementResponse(
            session_id=db_session.id,
            query_id=db_query.id,
            summary={
                "total_aspects": len(session.steps),
                "aspects_needing_refinement": 0,
                "aspects_clear": len(session.steps),
                "is_complete": True,
            },
            next_prompt=None,
            ready_for_synthesis=True,
            source=request.source,
            synthesis=synthesis_response,
        )
    # ── End fast path ───────────────────────────────────────────────────────

    # Update progress: aspects extracted
    await track_progress(
        query_id=str(db_query.id),
        stage=ProgressStage.ASPECTS_EXTRACTED,
        message=f"Identified {len(session.steps)} aspects to refine",
        aspects_count=len(session.steps),
        details={"framework": request.framework_name}
    )

    # Update progress: Generating suggestions
    await track_progress(
        query_id=str(db_query.id),
        stage=ProgressStage.GENERATING_SUGGESTIONS,
        message="Generating refinement suggestions...",
        turn_number=1,
        total_turns=len(session.steps)
    )
    
    # Generate question on-demand, looping until we find an aspect that needs refinement
    # This auto-cascade continues through aspects that are immediately complete
    max_attempts = len(session.steps)  # Prevent infinite loop
    attempts = 0
    current_step = session.get_next_unrefined_aspect()
    
    while current_step and attempts < max_attempts:
        attempts += 1
        try:
            # Increment LLM call counter before generating question
            await tracker.increment_llm_calls(str(db_query.id))
            
            # Generate question with retry logic
            result = await _generate_question_with_retry(
                manager=manager,
                session=session,
                aspect_id=current_step.refinement_aspect.id,
                mode='initial'
            )
            
            # Process the result
            analysis_status = manager.process_analysis_result(
                session=session,
                aspect_id=current_step.refinement_aspect.id,
                result=result
            )
            
            # If not complete, we have a question to ask - break
            if not analysis_status['complete']:
                logger.info(f"Aspect '{current_step.refinement_aspect.name}' needs refinement - stopping auto-cascade")
                break
            
            # Aspect is complete - log and save to database
            logger.info(f"Aspect '{current_step.refinement_aspect.name}' marked complete immediately - auto-advancing")
            
            # Save final value to database
            if current_step.normalized_value:
                from query_refinement_module.db.crud import update_refinement_step_final_value
                db_steps = get_query_refinement_steps(db, db_query.id)
                db_step = next(
                    (s for s in db_steps if s.aspect_name == current_step.refinement_aspect.name),
                    None
                )
                if db_step:
                    update_refinement_step_final_value(
                        db,
                        step_id=db_step.id,
                        final_value=current_step.normalized_value_as_str,
                        is_complete=True,
                        was_skipped=False,
                        user_ended_early=False
                    )
                
            # If complete, move to next aspect and continue loop
            current_step = session.get_next_unrefined_aspect()
            
        except Exception as e:
            logger.error(f"Error generating question for aspect {current_step.refinement_aspect.name}: {e}", exc_info=True)
            # Surface provider-side failures explicitly instead of masking with generic fallback
            error_str = str(e).lower()
            if "credit balance" in error_str or "insufficient" in error_str:
                raise HTTPException(
                    status_code=status.HTTP_402_PAYMENT_REQUIRED,
                    detail="LLM service credits exhausted. Please configure valid API credentials."
                )
            if "api key" in error_str or "authentication" in error_str:
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail="LLM service authentication error. Please check API configuration."
                )
            if "rate limit" in error_str:
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail="LLM service rate limit exceeded. Please try again later."
                )

            # Preserve fallback only for non-provider/transient parsing errors
            current_step.follow_up_question = f"Please provide details about {current_step.refinement_aspect.name}."
            break
    
    # Get summary (will show all aspects as not yet analyzed)
    summary = {
        "total_aspects": len(session.steps),
        "aspects_needing_refinement": len([s for s in session.steps if not s.is_complete]),
        "aspects_clear": len([s for s in session.steps if s.is_complete]),
        "is_complete": session.is_complete(),
    }
    
    next_prompt = await _build_next_prompt(manager, session)
    db_steps = get_query_refinement_steps(db, db_query.id)
    _persist_generated_question(db, db_steps, next_prompt)
    
    # Check if all aspects are complete (ready for synthesis)
    ready_for_synthesis = next_prompt is None and session.is_complete()
    
    # Update progress: Suggestions ready or waiting for user
    if next_prompt:
        suggestions_count = len([s for s in session.steps if not s.is_complete])
        await track_progress(
            query_id=str(db_query.id),
            stage=ProgressStage.SUGGESTIONS_READY,
            message="Refinement suggestions ready",
            suggestions_count=suggestions_count
        )
        await track_progress(
            query_id=str(db_query.id),
            stage=ProgressStage.WAITING_FOR_USER,
            message=f"Waiting for your input on '{next_prompt.get('name', 'aspect')}'",
            details={"current_aspect": next_prompt.get('name')}
        )
    elif ready_for_synthesis:
        # All aspects complete, ready for synthesis
        await track_progress(
            query_id=str(db_query.id),
            stage=ProgressStage.SUGGESTIONS_READY,
            message="All aspects refined, ready for synthesis"
        )
    
    # Save session to Redis for subsequent requests
    session_manager.save_session(db_query.id, session)
    
    duration_ms = (time.time() - start_time) * 1000
    logger.info(
        "API: Refinement workflow started successfully",
        extra={
            "request_id": request_id,
            "user_id": current_user.id,
            "session_id": db_session.id,
            "query_id": db_query.id,
            "total_aspects": summary["total_aspects"],
            "ready_for_synthesis": ready_for_synthesis,
            "duration_ms": round(duration_ms, 2),
        },
    )
    
    # Trigger webhook: refinement.started
    try:
        from query_refinement_module.services.webhook_service import (
            trigger_webhook_event,
            build_refinement_started_payload
        )
        payload = build_refinement_started_payload(
            query_id=db_query.id,
            user_id=current_user.id,
            framework=request.framework_name
        )
        trigger_webhook_event(db, "refinement.started", payload, user_id=current_user.id)
    except Exception as e:
        logger.error(f"Failed to trigger refinement.started webhook: {e}", exc_info=True)
    
    return StartRefinementResponse(
        session_id=db_session.id,
        query_id=db_query.id,
        summary=summary,
        next_prompt=next_prompt,
        ready_for_synthesis=ready_for_synthesis,
        source=request.source,
    )


@router.post("/queries/{query_id}/answer", response_model=Union[SubmitAnswerResponse, CommandResponse])
async def submit_answer(
    query_id: int,
    request: SubmitAnswerRequest,
    http_request: Request,
    manager: QueryRefinementManager = Depends(get_refinement_manager),
    current_user = Depends(get_current_user_or_integration),
    db: Session = Depends(get_db),
    session_manager: SessionManager = Depends(get_session_manager)
):
    """
    Submit an answer to the current refinement question, or execute a command.
    
    Regular answer processing:
    1. Stores answer in the follow-up history
    2. Runs the follow-up loop to check if more clarification is needed
    3. Marks the aspect as complete if satisfied
    4. Returns the next question if follow-up is needed, or moves to next aspect
    
    Command processing (input starts with /):
    - Information commands (/status, /steps, /help): Return session state
    - Navigation commands (/back, /restart): Modify session state and return new active step
    - Control commands (/skip, /done): Mark current step complete and advance
    - Synthesis command (/submit, /end): Flag session ready for synthesis
    """
    import time
    from query_refinement_module.tracing import generate_request_id, set_request_id, get_request_id
    
    # Generate and set request ID for tracing
    request_id = generate_request_id()
    set_request_id(request_id)
    
    start_time = time.time()
    is_command = request.answer.strip().startswith('/')
    
    logger.info(
        "API: Submitting answer",
        extra={
            "request_id": request_id,
            "user_id": current_user.id,
            "query_id": query_id,
            "is_command": is_command,
            "answer_length": len(request.answer),
        },
    )
    
    # Get query and verify ownership
    db_query = get_query(db, query_id)
    if not db_query:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Query not found")
    
    if db_query.session.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")
    
    # Load refinement framework
    framework_name = db_query.session.framework_name
    if not framework_name:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Framework name not found for session"
        )
    framework = get_framework(framework_name)
    
    # Acquire a per-session lock for the entire load→mutate→save cycle so that
    # concurrent requests for the same query_id cannot overwrite each other's state.
    async with session_manager.session_lock(query_id):
        return await _submit_answer_locked(
            query_id=query_id,
            request=request,
            http_request=http_request,
            manager=manager,
            current_user=current_user,
            db=db,
            session_manager=session_manager,
            db_query=db_query,
            framework=framework,
            request_id=request_id,
            start_time=start_time,
            is_command=is_command,
        )


async def _submit_answer_locked(
    *,
    query_id,
    request,
    http_request,
    manager,
    current_user,
    db,
    session_manager,
    db_query,
    framework,
    request_id,
    start_time,
    is_command,
):
    """Inner implementation of ``submit_answer``; runs under the per-session lock."""
    # Try to load session from Redis
    session = session_manager.load_session(query_id, framework)
    
    # If session not in Redis, reconstruct from database (fallback)
    if not session:
        logger.warning("Session not found in Redis for query_id=%d, reconstructing from database", query_id)
        session = await asyncio.to_thread(
            manager.initialize_sequential,
            db_query.original_query,
            framework,
        )
        
        # Restore persisted DB state (follow-ups + final values + completion flags)
        db_steps = get_query_refinement_steps(db, query_id)
        _restore_session_from_db_state(session, db_steps)
        
        # Re-cache the reconstructed session
        session_manager.save_session(query_id, session)
    
    # ============================================================
    # COMMAND DETECTION: Check if input is a command (starts with /)
    # ============================================================
    user_input = request.answer.strip()
    
    logger.info(f"[Query {query_id}] Processing answer/command: {user_input[:100]}...")
    logger.info(f"[Query {query_id}] Is command: {is_user_command(user_input)}")
    
    if is_user_command(user_input):
        logger.info(f"[Query {query_id}] COMMAND DETECTED: {user_input}")
        
        # Parse the command
        cmd_result = parse_user_command(user_input)
        logger.info(f"[Query {query_id}] Command parsed - valid: {cmd_result.is_valid}, command: {cmd_result.command}, arg: {cmd_result.argument}")
        
        # Handle invalid command
        if not cmd_result.is_valid:
            logger.warning(f"[Query {query_id}] Invalid command: {cmd_result.error_message}")
            return await _build_command_response(
                manager=manager,
                command_type=cmd_result.command.value,
                payload={"success": False, "message": cmd_result.error_message or "Invalid command"},
                session=session,
                force_confirmation_needed=False,
                db=db,
                query_id=query_id,
                db_steps=get_query_refinement_steps(db, query_id),
            )
        
        # Execute the command
        logger.info(f"[Query {query_id}] Executing command: {cmd_result.command.value}")
        pre_command_active_step = session.get_active_step()
        command_payload = session.handle_command(cmd_result)
        command_type = cmd_result.command.value
        
        logger.info(f"[Query {query_id}] Command result - success: {command_payload.get('success')}, message: {command_payload.get('message', '')[:100]}")
        
        # Check if force confirmation is needed for navigation commands
        force_confirmation_needed = False
        if not request.force and command_type in ["back", "prev", "previous", "restart"]:
            invalidated = command_payload.get("invalidated", [])
            if invalidated and command_payload.get("success", False):
                # Navigation would invalidate dependent aspects - require confirmation
                force_confirmation_needed = True
                logger.info(f"[Query {query_id}] Force confirmation needed - would invalidate: {invalidated}")
                # Mark as NOT successful since confirmation is needed
                command_payload["success"] = False
                command_payload["message"] = (
                    f"⚠️ Warning: This action will invalidate {len(invalidated)} dependent aspect(s): "
                    f"{', '.join(invalidated)}. This means you'll need to re-answer those aspects. "
                    f"Click 'Confirm' to proceed."
                )
        
        # ============================================================
        # AUDIT LOGGING: Track command execution for debugging & compliance
        # ============================================================
        
        # Get active dimension at time of command
        active_step = session.get_active_step()
        active_dimension = active_step.refinement_aspect.name if active_step else None
        
        # Map command type to specific audit event type
        command_audit_map = {
            "back": AuditEventType.COMMAND_BACK,
            "prev": AuditEventType.COMMAND_BACK,
            "previous": AuditEventType.COMMAND_BACK,
            "restart": AuditEventType.COMMAND_RESTART,
            "clear": AuditEventType.COMMAND_CLEAR,
            "skip": AuditEventType.COMMAND_SKIP,
            "done": AuditEventType.COMMAND_DONE,
            "status": AuditEventType.COMMAND_STATUS,
            "help": AuditEventType.COMMAND_HELP,
            "steps": AuditEventType.COMMAND_STEPS,
        }
        
        audit_event_type = command_audit_map.get(command_type, AuditEventType.COMMAND_EXECUTE)
        
        # Build detailed audit context
        audit_details = {
            "command": command_type,
            "command_input": user_input,
            "argument": cmd_result.argument,
            "active_dimension": active_dimension,
            "force_requested": request.force,
            "force_confirmation_needed": force_confirmation_needed,
            "success": command_payload.get("success", False),
        }
        
        # Add command-specific context
        if "cleared_aspects" in command_payload:
            audit_details["cleared_aspects"] = command_payload["cleared_aspects"]
        if "invalidated" in command_payload:
            audit_details["invalidated_aspects"] = command_payload["invalidated"]
        if "target_aspect" in command_payload:
            audit_details["target_aspect"] = command_payload["target_aspect"]
        if "deleted_count" in command_payload:
            audit_details["deleted_db_records"] = command_payload["deleted_count"]
        
        # Save session state for state-mutating commands BEFORE audit logging so
        # the audit record only exists once the state change is durable.
        if command_payload.get("success", False) and not force_confirmation_needed:
            if command_type in ["back", "prev", "previous", "restart", "skip", "done", "submit", "end"]:
                logger.info(f"[Query {query_id}] Saving session state after command: {command_type}")
                
                # Cascade delete DB records when session is truncated (referential integrity)
                if command_type in ["back", "prev", "previous", "restart"]:
                    cleared_aspects = command_payload.get("cleared_aspects", [])
                    if cleared_aspects:
                        deleted_count = delete_refinement_steps_by_aspects(
                            db, query_id=query_id, aspect_names=cleared_aspects
                        )
                        logger.info(
                            f"[Query {query_id}] Cascade deleted {deleted_count} DB records for truncated dimensions: {cleared_aspects}",
                            extra={"query_id": query_id, "command": command_type, "deleted_count": deleted_count}
                        )
                    
                    # For /back command, also reset the DB record for the reopened aspect
                    if command_type in ["back", "prev", "previous"]:
                        reopened_step = session.get_active_step()
                        if reopened_step:
                            db_steps = get_query_refinement_steps(db, query_id)
                            db_step = next(
                                (s for s in db_steps if s.aspect_name == reopened_step.refinement_aspect.name),
                                None
                            )
                            if db_step:
                                reset_refinement_step(db, step_id=db_step.id, clear_followup_history=True)
                                logger.info(
                                    f"[Query {query_id}] Reset DB record for reopened dimension: '{reopened_step.refinement_aspect.name}'",
                                    extra={"query_id": query_id, "dimension": reopened_step.refinement_aspect.name}
                                )
                
                # Reset DB record when dimension is cleared (maintain consistency)
                if command_type == "clear":
                    active_step = session.get_active_step()
                    if active_step:
                        db_steps = get_query_refinement_steps(db, query_id)
                        db_step = next(
                            (s for s in db_steps if s.aspect_name == active_step.refinement_aspect.name),
                            None
                        )
                        if db_step:
                            reset_refinement_step(db, step_id=db_step.id, clear_followup_history=True)
                            logger.info(
                                f"[Query {query_id}] Reset DB record for cleared dimension: '{active_step.refinement_aspect.name}'",
                                extra={"query_id": query_id, "dimension": active_step.refinement_aspect.name}
                            )
                
                # Save dimension final values to DB when skip or done commands are used
                if command_type in ["skip", "done"]:
                    from query_refinement_module.db.crud import (
                        mark_refinement_step_skipped,
                        mark_refinement_step_user_ended_early
                    )
                    
                    command_step = pre_command_active_step or command_payload.get("step")
                    if command_step and command_step.is_complete:
                        db_steps = get_query_refinement_steps(db, query_id)
                        db_step = next(
                            (s for s in db_steps if s.aspect_name == command_step.refinement_aspect.name),
                            None
                        )
                        
                        if db_step:
                            if command_type == "skip":
                                mark_refinement_step_skipped(db, db_step.id)
                                logger.info(
                                    f"Marked dimension as skipped in DB: '{command_step.refinement_aspect.name}'",
                                    extra={"query_id": query_id, "dimension": command_step.refinement_aspect.name}
                                )
                            elif command_type == "done":
                                mark_refinement_step_user_ended_early(
                                    db,
                                    step_id=db_step.id,
                                    final_value=command_step.normalized_value_as_str if command_step.normalized_value_as_str else None
                                )
                                logger.info(
                                    f"Marked dimension as user-completed in DB: '{command_step.refinement_aspect.name}'",
                                    extra={"query_id": query_id, "dimension": command_step.refinement_aspect.name}
                                )
                
                session_manager.save_session(query_id, session)

        # Log command execution — after state is persisted so the record is
        # consistent with the durable session/DB state.
        audit_service.log_from_request(
            db=db,
            request=http_request,
            event_type=audit_event_type,
            user=current_user,
            severity="info" if command_payload.get("success") else "warning",
            resource_type="query",
            resource_id=str(query_id),
            action=f"Executed /{command_type} command" + (f" with arg '{cmd_result.argument}'" if cmd_result.argument else ""),
            status="success" if command_payload.get("success") and not force_confirmation_needed else "needs_confirmation" if force_confirmation_needed else "failure",
            details=audit_details
        )
        
        # Build command response
        command_response = await _build_command_response(
            manager=manager,
            command_type=command_type,
            payload=command_payload,
            session=session,
            force_confirmation_needed=force_confirmation_needed,
            db=db,
            query_id=query_id,
            db_steps=get_query_refinement_steps(db, query_id),
        )

        # Persist active question context if a prompt is present in command response
        if command_response.next_prompt and command_response.next_prompt.get("question"):
            session_manager.save_session(query_id, session)

        return command_response
    
    # ============================================================
    # REGULAR ANSWER PROCESSING (not a command)
    # ============================================================
    
    # Get the active step
    active_step = session.get_active_step()
    if not active_step:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No active refinement step"
        )
    
    # Add user's answer to follow-up history
    active_step.conversation_history.append({
        'question': active_step.follow_up_question or active_step.refinement_aspect.name,
        'response': user_input
    })
    
    # Update progress: user refining
    await track_progress(
        query_id=str(query_id),
        stage=ProgressStage.USER_REFINING,
        message=f"Processing your input for '{active_step.refinement_aspect.name}'...",
        details={"aspect": active_step.refinement_aspect.name}
    )
    
    # Analyze the user's answer with LLM (single call, not a loop)
    try:
        # Update progress: calling LLM
        tracker = get_progress_tracker()
        await tracker.increment_llm_calls(str(query_id))
        
        # Call LLM once to analyze if dimension is complete or needs more clarification
        analysis_result = await manager.get_analysis_prompts(
            session=session,
            aspect_id=active_step.refinement_aspect.id,
            mode='followup'
        )
        
        # Process the result
        analysis_status = manager.process_analysis_result(
            session=session,
            aspect_id=active_step.refinement_aspect.id,
            result=analysis_result
        )
    except ConnectionError as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Unable to connect to LLM service: {str(e)}"
        )
    except TimeoutError as e:
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail=f"LLM service request timed out: {str(e)}"
        )
    except Exception as e:
        logger.error(f"Error in follow-up loop: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to process answer: {str(e)}"
        )
    
    # Get the corresponding database refinement step
    db_steps = get_query_refinement_steps(db, query_id)
    db_step = next(
        (s for s in db_steps if s.aspect_name == active_step.refinement_aspect.name),
        None
    )
    
    if not db_step:
        logger.warning(
            "Missing refinement_step row for active aspect; recreating",
            extra={
                "query_id": query_id,
                "aspect": active_step.refinement_aspect.name,
            },
        )
        db_step = create_refinement_step(
            db,
            query_id=query_id,
            aspect_name=active_step.refinement_aspect.name,
        )
    
    # Store the follow-up in database
    db_followup = create_followup(
        db,
        refinement_step_id=db_step.id,
        question=active_step.follow_up_question or active_step.refinement_aspect.name,
        answer=user_input
    )
    followup_id = db_followup.id
    
    # Check if aspect is complete
    is_complete = analysis_status.get('complete', False)
    
    # If dimension is complete, save final value to database for evaluation
    if is_complete and active_step.normalized_value:
        from query_refinement_module.db.crud import update_refinement_step_final_value
        update_refinement_step_final_value(
            db,
            step_id=db_step.id,
            final_value=active_step.normalized_value_as_str,
            is_complete=True,
            was_skipped=False,
            user_ended_early=False
        )
        logger.info(
            f"Saved final value to DB for dimension '{active_step.refinement_aspect.name}'",
            extra={"query_id": query_id, "dimension": active_step.refinement_aspect.name}
        )
        
        # Trigger webhook: refinement.step_completed
        try:
            from query_refinement_module.services.webhook_service import (
                trigger_webhook_event,
                build_refinement_step_completed_payload
            )
            payload = build_refinement_step_completed_payload(
                query_id=query_id,
                dimension=active_step.refinement_aspect.name,
                aspect=active_step.refinement_aspect.name,
                answer=active_step.normalized_value_as_str
            )
            trigger_webhook_event(db, "refinement.step_completed", payload, user_id=current_user.id)
        except Exception as e:
            logger.error(f"Failed to trigger refinement.step_completed webhook: {e}", exc_info=True)
            # Webhook failure is non-critical; do not rollback already-committed DB writes.
    
    # Get next prompt
    next_prompt = None
    if not is_complete:
        # Still need follow-up on same aspect
        fallback_question = f"Please provide more details about {active_step.refinement_aspect.name}."
        next_prompt = {
            "aspect_id": active_step.refinement_aspect.id,
            "name": active_step.refinement_aspect.name,
            "question": active_step.follow_up_question or fallback_question,
            "description": active_step.refinement_aspect.description or "",
        }
    else:
        # Current aspect complete - auto-cascade through any subsequent immediately-complete aspects
        max_cascade_attempts = len(session.steps)  # Prevent infinite loop
        cascade_attempts = 0
        next_step = session.get_next_unrefined_aspect()
        
        while next_step and cascade_attempts < max_cascade_attempts:
            cascade_attempts += 1
            try:
                # Generate initial question for next aspect with retry
                question_result = await _generate_question_with_retry(
                    manager=manager,
                    session=session,
                    aspect_id=next_step.refinement_aspect.id,
                    mode='initial'
                )
                
                # Process the result to update the step
                analysis_status = manager.process_analysis_result(
                    session=session,
                    aspect_id=next_step.refinement_aspect.id,
                    result=question_result
                )
                
                # If not complete, we have a question - stop cascading
                if not analysis_status['complete']:
                    logger.info(f"Aspect '{next_step.refinement_aspect.name}' needs refinement - stopping auto-cascade")
                    break
                
                # Aspect is complete - log and save to database
                logger.info(f"Aspect '{next_step.refinement_aspect.name}' marked complete immediately - auto-advancing")
                
                # Save final value to database
                if next_step.normalized_value:
                    from query_refinement_module.db.crud import update_refinement_step_final_value
                    db_steps = get_query_refinement_steps(db, query_id)
                    db_step = next(
                        (s for s in db_steps if s.aspect_name == next_step.refinement_aspect.name),
                        None
                    )
                    if not db_step:
                        logger.warning(
                            "Missing refinement_step row during auto-cascade; recreating",
                            extra={
                                "query_id": query_id,
                                "aspect": next_step.refinement_aspect.name,
                            },
                        )
                        db_step = create_refinement_step(
                            db,
                            query_id=query_id,
                            aspect_name=next_step.refinement_aspect.name,
                        )

                    update_refinement_step_final_value(
                        db,
                        step_id=db_step.id,
                        final_value=next_step.normalized_value_as_str,
                        is_complete=True,
                        was_skipped=False,
                        user_ended_early=False
                    )
                
                # Move to next aspect and continue cascading
                next_step = session.get_next_unrefined_aspect()
                
            except Exception as e:
                logger.error(f"Error generating next question: {e}", exc_info=True)
                # Stop cascading on error; do not rollback prior cascade writes.
                break
        
        # Build prompt after cascade completes
        next_prompt = await _build_next_prompt(manager, session)
        _persist_generated_question(db, db_steps, next_prompt)
    
    # Save updated session back to Redis
    session_manager.save_session(query_id, session)
    
    # Check if all aspects are complete (ready for synthesis)
    ready_for_synthesis = next_prompt is None and session.is_complete()
    
    # Trigger webhook: refinement.complete (if all dimensions done)
    if ready_for_synthesis:
        try:
            from query_refinement_module.services.webhook_service import (
                trigger_webhook_event,
                build_refinement_complete_payload
            )
            payload = build_refinement_complete_payload(
                query_id=query_id,
                total_steps=len(session.steps)
            )
            trigger_webhook_event(db, "refinement.complete", payload, user_id=current_user.id)
        except Exception as e:
            logger.error(f"Failed to trigger refinement.complete webhook: {e}", exc_info=True)
            # Webhook failure is non-critical; do not rollback already-committed DB writes.
    
    duration_ms = (time.time() - start_time) * 1000
    logger.info(
        "API: Answer submitted successfully",
        extra={
            "request_id": request_id,
            "user_id": current_user.id,
            "query_id": query_id,
            "is_command": is_command,
            "is_complete": is_complete,
            "ready_for_synthesis": ready_for_synthesis,
            "duration_ms": round(duration_ms, 2),
        },
    )
    
    return SubmitAnswerResponse(
        refinement_step_id=db_step.id,
        followup_id=followup_id,
        is_complete=is_complete,
        next_prompt=next_prompt,
        ready_for_synthesis=ready_for_synthesis
    )


@router.get("/queries/{query_id}/status", response_model=GetRefinementStatusResponse)
async def get_refinement_status(
    query_id: int,
    manager: QueryRefinementManager = Depends(get_refinement_manager),
    current_user = Depends(get_current_user_or_integration),
    db: Session = Depends(get_db),
    session_manager: SessionManager = Depends(get_session_manager)
):
    """
    Get the current status of a refinement workflow.
    """
    import time
    from query_refinement_module.tracing import generate_request_id, set_request_id, get_request_id
    
    # Generate and set request ID for tracing
    request_id = generate_request_id()
    set_request_id(request_id)
    
    start_time = time.time()
    logger.info(
        "API: Getting refinement status",
        extra={
            "request_id": request_id,
            "user_id": current_user.id,
            "query_id": query_id,
        },
    )
    
    db_query = get_query(db, query_id)
    if not db_query:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Query not found")
    
    if db_query.session.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")
    
    # Check if query has been synthesized (workflow complete)
    if db_query.refined_query and db_query.refined_query.strip():
        logger.info(f"Query {query_id} already synthesized, returning completion status")
        return GetRefinementStatusResponse(
            query_id=query_id,
            original_query=db_query.original_query,
            refined_query=db_query.refined_query,
            is_complete=True,
            current_aspect=None,
            aspects_summary={},
            next_prompt=None,
            ready_for_synthesis=True,
            aspects=[],
            conversation_history=[]
        )
    
    # Get framework name from database
    framework_name = db_query.session.framework_name
    if not framework_name:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Framework name not found for session")
    
    # Load session from Redis cache first (fast)
    framework = get_framework(framework_name)
    session = session_manager.load_session(query_id, framework)
    
    # Fallback: Reconstruct from database if Redis miss
    if not session:
        logger.warning(f"Session not found in Redis for query_id={query_id}, reconstructing from database")
        session = await asyncio.to_thread(
            manager.initialize_sequential,
            db_query.original_query,
            framework,
        )
        
        # Restore persisted DB state (follow-ups + final values + completion flags)
        db_steps = get_query_refinement_steps(db, query_id)
        _restore_session_from_db_state(session, db_steps)
        
        # Re-cache the reconstructed session
        session_manager.save_session(query_id, session)
    
    summary = manager.get_initialization_summary(session)
    active_step = session.get_active_step()
    
    # Build next prompt and check if ready for synthesis
    if session.synthesis_requested:
        # Keep /status semantics aligned with /submit command behavior
        next_prompt = None
        ready_for_synthesis = True
    else:
        next_prompt = _get_active_prompt(session) or await _build_next_prompt(manager, session)
        ready_for_synthesis = next_prompt is None and session.is_complete()
        db_steps_status = get_query_refinement_steps(db, query_id)
        _persist_generated_question(db, db_steps_status, next_prompt)

    # Persist in case next prompt was generated during this status request
    session_manager.save_session(query_id, session)
    
    # Build aspects list for frontend
    aspects = [
        {
            "aspect_id": step.refinement_aspect.id,
            "name": step.refinement_aspect.name,
            "is_complete": step.is_complete,
            "needs_review": step.needs_review,
            "was_skipped": step.was_skipped,
            "status": (
                "completed" if step.is_complete and not step.needs_review else
                "needs review" if step.needs_review else
                "active" if step == active_step else
                "not started"
            )
        }
        for step in session.steps
    ]
    
    # Build conversation history for frontend restoration
    conversation_history = []
    # Add initial query
    conversation_history.append({
        "type": "query",
        "content": db_query.original_query
    })
    # Add all Q&A exchanges from all steps
    for step in session.steps:
        for qa in step.conversation_history:
            conversation_history.append({
                "type": "question",
                "content": qa.get('question', ''),
                "aspectId": step.refinement_aspect.id,
                "aspectName": step.refinement_aspect.name
            })
            if qa.get('response'):
                conversation_history.append({
                    "type": "answer",
                    "content": qa['response'],
                    "aspectId": step.refinement_aspect.id
                })
    
    duration_ms = (time.time() - start_time) * 1000
    logger.info(
        "API: Refinement status retrieved",
        extra={
            "request_id": request_id,
            "user_id": current_user.id,
            "query_id": query_id,
            "is_complete": session.is_complete(),
            "current_aspect": active_step.refinement_aspect.name if active_step else None,
            "ready_for_synthesis": ready_for_synthesis,
            "duration_ms": round(duration_ms, 2),
        },
    )
    
    return GetRefinementStatusResponse(
        query_id=query_id,
        original_query=db_query.original_query,
        refined_query=db_query.refined_query,
        is_complete=session.is_complete(),
        current_aspect=active_step.refinement_aspect.name if active_step else None,
        aspects_summary=summary,
        next_prompt=next_prompt,
        ready_for_synthesis=ready_for_synthesis,
        aspects=aspects,
        conversation_history=conversation_history
    )


# ==========================================
# Synthesis helper – shared by /synthesize and skip_refinement fast-path
# ==========================================

async def _run_synthesis(
    *,
    manager: QueryRefinementManager,
    session,
    db,
    db_query,
    current_user,
    session_manager: SessionManager,
    query_id: int,
    request_id: str,
) -> SynthesizeQueryResponse:
    """
    Execute the full synthesis pipeline and return a SynthesizeQueryResponse.

    Called by both the /synthesize endpoint and the skip_refinement fast-path
    in /start so that both paths stay in sync without code duplication.
    """
    tracker = get_progress_tracker()

    await track_progress(
        query_id=str(query_id),
        stage=ProgressStage.SYNTHESIZING,
        message="Synthesizing final refined query...",
        details={"framework": db_query.session.framework_name},
    )

    # Webhook: synthesis.started
    try:
        from query_refinement_module.services.webhook_service import (
            trigger_webhook_event,
            build_synthesis_started_payload,
        )
        trigger_webhook_event(
            db,
            "synthesis.started",
            build_synthesis_started_payload(
                query_id=query_id,
                initial_query=db_query.original_query,
            ),
            user_id=current_user.id,
        )
    except Exception as _e:
        logger.error(f"Failed to trigger synthesis.started webhook: {_e}", exc_info=True)

    # LLM synthesis call
    try:
        await tracker.increment_llm_calls(str(query_id))
        synthesis_result = await manager.synthesize_refined_query(session)
    except Exception as _e:
        await track_progress(
            query_id=str(query_id),
            stage=ProgressStage.FAILED,
            message="Synthesis failed",
            error=str(_e),
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to synthesize query: {str(_e)}",
        )

    integrated_statement = synthesis_result.get("integrated_statement", "")

    # Build structured output
    structured_output = None
    if synthesis_result.get("dimensions_specifications"):
        structured_output = {
            "dimensions_specifications": synthesis_result.get("dimensions_specifications"),
            "search_optimized": synthesis_result.get("search_optimized"),
            "search_filters": synthesis_result.get("search_filters"),
            "terminology": synthesis_result.get("terminology"),
        }
    elif integrated_statement and (
        integrated_statement.startswith("{") or integrated_statement.startswith("`")
    ):
        try:
            import json as _json
            import re as _re

            json_str = integrated_statement
            if json_str.startswith("`"):
                lines = json_str.split("\n")
                if lines[0].startswith("`"):
                    lines = lines[1:]
                if lines and lines[-1].strip().startswith("`"):
                    lines = lines[:-1]
                json_str = "\n".join(lines)

            if not json_str.rstrip().endswith("}"):
                logger.error(
                    "JSON response appears truncated (doesn't end with '}'), likely hit max_tokens limit",
                    extra={"json_length": len(json_str), "request_id": request_id},
                )
                _match = _re.search(r'"integrated_statement"\s*:\s*"([^"]+)"', json_str)
                if _match:
                    integrated_statement = _match.group(1)
                raise ValueError("JSON response was truncated, increase max_tokens")

            _parsed = _json.loads(json_str)
            structured_output = {
                "dimensions_specifications": _parsed.get("dimensions_specifications"),
                "search_optimized": _parsed.get("search_optimized"),
                "search_filters": _parsed.get("search_filters"),
                "terminology": _parsed.get("terminology"),
            }
            if _parsed.get("integrated_statement"):
                integrated_statement = _parsed["integrated_statement"]
            logger.info(
                "Successfully parsed JSON from integrated_statement string",
                extra={"has_dimensions": "dimensions" in _parsed},
            )
        except (_json.JSONDecodeError, ValueError) as _e:
            logger.error(
                f"Failed to parse JSON from integrated_statement: {_e}",
                extra={"error_type": type(_e).__name__},
            )

    if not integrated_statement or not integrated_statement.strip():
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Synthesis produced empty result. Please try again.",
        )

    logger.info(
        "Integrated statement before database update",
        extra={
            "request_id": request_id,
            "integrated_statement_preview": integrated_statement[:200],
            "integrated_statement_length": len(integrated_statement),
        },
    )

    # Persist to DB — combine refined_query update and workflow-limit flag in a
    # single commit so both succeed or both fail atomically.
    db_query.refined_query = integrated_statement
    settings = get_settings()
    if settings.enforce_workflow_limit and not current_user.is_superuser:
        current_user.has_completed_workflow = True
    db.commit()
    db.refresh(db_query)
    logger.info(
        "Database updated with refined query",
        extra={
            "request_id": request_id,
            "query_id": query_id,
            "db_integrated_statement_length": len(db_query.refined_query) if db_query.refined_query else 0,
        },
    )

    await track_progress(
        query_id=str(query_id),
        stage=ProgressStage.SYNTHESIS_COMPLETE,
        message="Synthesis completed successfully",
    )

    # Webhook: synthesis.complete
    try:
        from query_refinement_module.services.webhook_service import (
            trigger_webhook_event,
            build_synthesis_complete_payload,
        )
        trigger_webhook_event(
            db,
            "synthesis.complete",
            build_synthesis_complete_payload(
                query_id=query_id,
                refined_query=integrated_statement,
                initial_query=db_query.original_query,
            ),
            user_id=current_user.id,
        )
    except Exception as _e:
        logger.error(f"Failed to trigger synthesis.complete webhook: {_e}", exc_info=True)

    # Clean up Redis session (workflow complete)
    session_manager.delete_session(query_id)

    await track_progress(
        query_id=str(query_id),
        stage=ProgressStage.COMPLETED,
        message="Refinement completed successfully",
    )

    logger.info(
        "API: Query synthesis completed",
        extra={
            "request_id": request_id,
            "query_id": query_id,
            "used_llm": synthesis_result.get("used_llm", False),
            "integrated_statement_length": len(integrated_statement),
            "has_structured_output": structured_output is not None,
        },
    )

    return SynthesizeQueryResponse(
        query_id=query_id,
        integrated_statement=integrated_statement,
        used_llm=synthesis_result.get("used_llm", False),
        structured_output=structured_output,
    )


@router.post("/synthesize", response_model=SynthesizeQueryResponse)
async def synthesize_refined_query(
    request: SynthesizeQueryRequest,
    manager: QueryRefinementManager = Depends(get_refinement_manager),
    current_user = Depends(get_current_user_or_integration),
    db: Session = Depends(get_db),
    session_manager: SessionManager = Depends(get_session_manager)
):
    """
    Synthesize the final refined query from all collected answers.

    This combines the original query with all refinement clarifications
    into a well-formed refined query.
    """
    import time
    from query_refinement_module.tracing import generate_request_id, set_request_id

    request_id_val = generate_request_id()
    set_request_id(request_id_val)
    start_time = time.time()

    logger.info(
        "API: Synthesizing refined query",
        extra={
            "request_id": request_id_val,
            "user_id": current_user.id,
            "query_id": request.query_id,
        },
    )

    db_query = get_query(db, request.query_id)
    if not db_query:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Query not found")

    if db_query.session.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")

    framework_name = db_query.session.framework_name
    if not framework_name:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Framework name not found for session")

    framework = get_framework(framework_name)
    session = session_manager.load_session(request.query_id, framework)

    if not session:
        logger.warning("Session not found in Redis for query_id=%d, reconstructing from database", request.query_id)
        session = await asyncio.to_thread(
            manager.initialize_sequential,
            db_query.original_query,
            framework,
        )
        db_steps = get_query_refinement_steps(db, request.query_id)
        _restore_session_from_db_state(session, db_steps)

    if not _is_session_ready_for_synthesis(session):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Query is not ready for synthesis. Complete all dimensions or use /submit first.",
        )

    response = await _run_synthesis(
        manager=manager,
        session=session,
        db=db,
        db_query=db_query,
        current_user=current_user,
        session_manager=session_manager,
        query_id=request.query_id,
        request_id=request_id_val,
    )

    duration_ms = (time.time() - start_time) * 1000
    logger.info(
        "Returning synthesis response",
        extra={
            "request_id": request_id_val,
            "duration_ms": round(duration_ms, 2),
            "response_query_id": response.query_id,
            "response_integrated_statement_length": len(response.integrated_statement),
            "response_has_structured_output": response.structured_output is not None,
        },
    )
    return response


# ==========================================
# QA System Forwarding Endpoint
# ==========================================

@router.post("/queries/{query_id}/forward-to-qa", response_model=ForwardToQAResponse)
async def forward_to_qa_system(
    query_id: int,
    request: ForwardToQARequest,
    current_user = Depends(get_current_user_or_integration),
    db: Session = Depends(get_db),
):
    """
    Forward a completed refined query to an external question-answering system.
    
    This endpoint enables middleware integration by forwarding the refined query
    to an external QA system AFTER the complete refinement process (with user
    clarifications for all dimensions).
    
    Requirements:
    - Query must exist and belong to the authenticated user
    - Query must have a refined_query (synthesis must be complete)
    - The refinement workflow must be finished (all dimensions clarified)
    
    The endpoint:
    1. Validates query completion
    2. Retrieves the refined query
    3. Forwards it to the specified QA system
    4. Returns both the refined query and QA system response
    5. Triggers webhook event for monitoring
    
    Security:
    - User authentication required
    - Query ownership validated
    - QA system authentication passed through
    - Request timeout enforced
    """
    request_id_val = generate_request_id()
    set_request_id(request_id_val)
    request_logger = get_logger(__name__, request_id=request_id_val)
    
    start_time = time.time()
    
    request_logger.info(
        "API: Forward to QA system request received",
        extra={
            "request_id": request_id_val,
            "user_id": current_user.id,
            "query_id": query_id,
            "qa_system_url": request.qa_system_url,
            "timeout_seconds": request.timeout_seconds,
        },
    )
    
    # Verify query exists and belongs to user
    db_query = get_query(db, query_id=query_id)
    if not db_query:
        request_logger.warning(
            "Query not found",
            extra={"request_id": request_id_val, "query_id": query_id}
        )
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Query {query_id} not found"
        )
    
    # Verify ownership
    if db_query.session.user_id != current_user.id:
        request_logger.warning(
            "Unauthorized access attempt",
            extra={
                "request_id": request_id_val,
                "query_id": query_id,
                "query_owner_id": db_query.session.user_id,
                "requesting_user_id": current_user.id,
            }
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You don't have permission to access this query"
        )
    
    # Verify refinement is complete
    if not db_query.refined_query or not db_query.refined_query.strip():
        request_logger.warning(
            "Attempted to forward incomplete refinement",
            extra={
                "request_id": request_id_val,
                "query_id": query_id,
                "has_refined_query": bool(db_query.refined_query),
            }
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Query refinement is not complete. Please complete the synthesis step first."
        )
    
    # Prepare payload for QA system
    qa_payload = {
        "query": db_query.refined_query,
    }
    
    if request.forward_original_query:
        qa_payload["original_query"] = db_query.original_query
    
    if request.include_refinement_metadata:
        # Gather refinement metadata
        refinement_steps = get_query_refinement_steps(db, query_id=query_id)
        qa_payload["refinement_metadata"] = {
            "framework": db_query.session.framework_name if hasattr(db_query.session, 'framework_name') else None,
            "total_steps": len(refinement_steps),
            "dimensions_refined": [step.aspect_id for step in refinement_steps if step.is_refined],
            "query_id": query_id,
        }
    
    request_logger.info(
        "Forwarding refined query to external QA system",
        extra={
            "request_id": request_id_val,
            "query_id": query_id,
            "refined_query_length": len(db_query.refined_query),
            "payload_keys": list(qa_payload.keys()),
        }
    )
    
    # Forward to external QA system
    import httpx
    
    qa_start_time = time.time()
    try:
        async with httpx.AsyncClient(timeout=request.timeout_seconds) as client:
            headers = request.qa_system_auth or {}
            headers["Content-Type"] = "application/json"
            headers["X-Request-ID"] = request_id_val
            
            response = await client.post(
                request.qa_system_url,
                json=qa_payload,
                headers=headers
            )
            
            qa_response_time_ms = int((time.time() - qa_start_time) * 1000)
            
            # Try to parse JSON response
            try:
                qa_response_data = response.json()
            except Exception:
                qa_response_data = {"response": response.text}
            
            request_logger.info(
                "Received response from QA system",
                extra={
                    "request_id": request_id_val,
                    "query_id": query_id,
                    "status_code": response.status_code,
                    "response_time_ms": qa_response_time_ms,
                }
            )
            
            # Trigger webhook: query.forwarded (if webhook system supports it)
            try:
                from query_refinement_module.services.webhook_service import trigger_webhook_event
                webhook_payload = {
                    "query_id": query_id,
                    "refined_query": db_query.refined_query,
                    "qa_system_url": request.qa_system_url,
                    "qa_status_code": response.status_code,
                    "response_time_ms": qa_response_time_ms,
                }
                # Note: This event type might not exist yet in WebhookEventType
                # It will be silently skipped if no webhooks are subscribed
                trigger_webhook_event(db, "query.forwarded", webhook_payload, user_id=current_user.id)
            except Exception as e:
                request_logger.warning(f"Failed to trigger webhook for QA forwarding: {e}")
            
            # Prepare response
            result = ForwardToQAResponse(
                query_id=query_id,
                refined_query=db_query.refined_query,
                original_query=db_query.original_query if request.forward_original_query else None,
                qa_system_url=request.qa_system_url,
                qa_system_response=qa_response_data,
                qa_system_status_code=response.status_code,
                response_time_ms=qa_response_time_ms,
                refinement_metadata=qa_payload.get("refinement_metadata") if request.include_refinement_metadata else None
            )
            
            total_duration_ms = int((time.time() - start_time) * 1000)
            request_logger.info(
                "API: Forward to QA system completed",
                extra={
                    "request_id": request_id_val,
                    "user_id": current_user.id,
                    "query_id": query_id,
                    "qa_status_code": response.status_code,
                    "qa_response_time_ms": qa_response_time_ms,
                    "total_duration_ms": total_duration_ms,
                },
            )
            
            return result
            
    except httpx.TimeoutException:
        request_logger.error(
            "QA system request timed out",
            extra={
                "request_id": request_id_val,
                "query_id": query_id,
                "timeout_seconds": request.timeout_seconds,
            }
        )
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail=f"QA system did not respond within {request.timeout_seconds} seconds"
        )
    except httpx.RequestError as e:
        request_logger.error(
            f"Failed to connect to QA system: {e}",
            extra={
                "request_id": request_id_val,
                "query_id": query_id,
                "qa_system_url": request.qa_system_url,
            },
            exc_info=True
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Failed to connect to QA system: {str(e)}"
        )
    except Exception as e:
        request_logger.error(
            f"Unexpected error during QA forwarding: {e}",
            extra={"request_id": request_id_val, "query_id": query_id},
            exc_info=True
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to forward query to QA system: {str(e)}"
        )


# ==========================================
# Command History Endpoint
# ==========================================

class CommandHistoryEntry(BaseModel):
    """Single command execution record."""
    timestamp: str
    event_id: int
    command: str
    command_input: str
    argument: Optional[str] = None
    active_dimension: Optional[str] = None
    success: bool
    status: str
    force_requested: bool
    force_confirmation_needed: bool
    cleared_aspects: Optional[List[str]] = None
    invalidated_aspects: Optional[List[str]] = None
    target_aspect: Optional[str] = None
    deleted_db_records: Optional[int] = None
    username: str
    request_id: Optional[str] = None


class CommandHistoryResponse(BaseModel):
    """Response containing command execution history for a query."""
    query_id: int
    total_commands: int
    commands: List[CommandHistoryEntry]


@router.get("/queries/{query_id}/command-history", response_model=CommandHistoryResponse)
def get_command_history(
    query_id: int,
    limit: int = 100,
    current_user = Depends(get_current_user_or_integration),
    db: Session = Depends(get_db),
):
    """
    Retrieve execution history of all commands for a specific query.
    
    Returns chronological list of command executions with full context:
    - Command type and arguments
    - Success/failure status
    - Affected dimensions (cleared, invalidated)
    - Active dimension at time of execution
    - User and timestamp information
    
    Useful for:
    - Debugging unexpected session states
    - Understanding user workflow patterns
    - Troubleshooting cascade delete issues
    - Compliance and audit trails
    
    Args:
        query_id: Query ID to get command history for
        limit: Maximum number of commands to return (default: 100)
    """
    from query_refinement_module.db.models.audit_log import AuditLog
    
    # Verify query ownership
    query = get_query(db, query_id)
    if not query or query.session.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Query not found"
        )
    
    # Query audit logs for command events
    command_event_types = [
        AuditEventType.COMMAND_EXECUTE,
        AuditEventType.COMMAND_BACK,
        AuditEventType.COMMAND_RESTART,
        AuditEventType.COMMAND_CLEAR,
        AuditEventType.COMMAND_SKIP,
        AuditEventType.COMMAND_DONE,
        AuditEventType.COMMAND_STATUS,
        AuditEventType.COMMAND_HELP,
        AuditEventType.COMMAND_STEPS,
    ]
    
    audit_logs = db.query(AuditLog).filter(
        AuditLog.resource_type == "query",
        AuditLog.resource_id == str(query_id),
        AuditLog.event_type.in_(command_event_types)
    ).order_by(AuditLog.timestamp.desc()).limit(limit).all()
    
    # Build command history entries
    commands = []
    for log in reversed(audit_logs):  # Reverse to get chronological order
        details = log.details or {}
        commands.append(CommandHistoryEntry(
            timestamp=log.timestamp.isoformat(),
            event_id=log.id,
            command=details.get("command", "unknown"),
            command_input=details.get("command_input", ""),
            argument=details.get("argument"),
            active_dimension=details.get("active_dimension"),
            success=details.get("success", False),
            status=log.status or "unknown",
            force_requested=details.get("force_requested", False),
            force_confirmation_needed=details.get("force_confirmation_needed", False),
            cleared_aspects=details.get("cleared_aspects"),
            invalidated_aspects=details.get("invalidated_aspects"),
            target_aspect=details.get("target_aspect"),
            deleted_db_records=details.get("deleted_db_records"),
            username=log.username or "unknown",
            request_id=log.request_id
        ))
    
    return CommandHistoryResponse(
        query_id=query_id,
        total_commands=len(commands),
        commands=commands
    )


# ==========================================
# Debug Endpoint - Inspect Messages
# ==========================================

class InspectMessagesResponse(BaseModel):
    """Response showing the actual messages sent to the LLM."""
    query_id: int
    current_dimension: Optional[str] = None
    message_count: int
    messages: List[Dict[str, Any]]
    user_context_detected: bool
    user_context_preview: Optional[str] = None


@router.get("/queries/{query_id}/inspect-messages", response_model=InspectMessagesResponse)
def inspect_messages(
    query_id: int,
    current_user = Depends(get_current_user_or_integration),
    session_manager: SessionManager = Depends(get_session_manager),
    db: Session = Depends(get_db),
):
    """
    Debug endpoint to inspect the actual messages being sent to the LLM.
    
    Shows:
    - Full message array with roles and content
    - Whether user context is included
    - Preview of user context content
    - Message count and structure
    
    Use this to verify that user context is being properly included in prompts.
    """
    # Verify query ownership
    query = get_query(db, query_id)
    if not query or query.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Query not found"
        )
    
    # Load session
    session = session_manager.load_session(query_id)
    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Session not found or expired"
        )
    
    # Get active step to inspect messages
    active_step = session.get_active_step()
    if not active_step:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No active dimension to inspect"
        )
    
    # Get messages for current dimension
    llm_settings = LLMSettings.from_env(require_model=False)
    dependency_context = session.get_dependency_context(active_step.refinement_aspect.id)
    messages = active_step.get_messages(
        query=session.original_query,
        dependency_context=dependency_context,
        terminal_reinforcement_threshold=llm_settings.terminal_reinforcement_threshold
    )
    
    # Check for user context in messages
    user_context_detected = False
    user_context_preview = None
    
    for msg in messages:
        content = msg.get("content", "")
        if "User Context" in content or "user_context" in content.lower():
            user_context_detected = True
            # Get first 200 chars of user context message
            user_context_preview = content[:200] + "..." if len(content) > 200 else content
            break
    
    return InspectMessagesResponse(
        query_id=query_id,
        current_dimension=active_step.refinement_aspect.id,
        message_count=len(messages),
        messages=messages,
        user_context_detected=user_context_detected,
        user_context_preview=user_context_preview
    )


# ==========================================
# Session Abandonment Endpoint
# ==========================================

class AbandonSessionRequest(BaseModel):
    """Request to abandon/delete a session and all its data."""
    session_id: int = Field(..., gt=0, description="ID of the session to abandon")


class AbandonSessionResponse(BaseModel):
    """Response with deletion details."""
    status: str = Field(..., description="Status of the operation")
    session_id: int = Field(..., description="ID of the abandoned session")
    deletion_counts: Dict[str, int] = Field(..., description="Count of deleted records by type")
    message: str = Field(..., description="Human-readable message")


@router.post("/sessions/abandon", response_model=AbandonSessionResponse)
async def abandon_session(
    request: AbandonSessionRequest,
    http_request: Request,
    current_user = Depends(get_current_user_or_integration),
    db: Session = Depends(get_db),
    session_manager: SessionManager = Depends(get_session_manager)
):
    """
    Abandon/delete a session and all its associated data.
    
    This endpoint is used when a user clicks "Start Over" to clean up
    incomplete sessions. It:
    
    1. Deletes all refinement data (steps, follow-ups, feedback)
    2. Deletes all queries in the session
    3. Deletes the session itself
    4. Clears the Redis cache
    
    This ensures abandoned sessions don't count toward workflow limits.
    
    Note: AuditLog and FrontendLog entries are preserved for research.
    """
    import time
    from query_refinement_module.tracing import generate_request_id, set_request_id
    
    # Generate and set request ID for tracing
    request_id = generate_request_id()
    set_request_id(request_id)
    
    start_time = time.time()
    logger.info(
        "API: Abandoning session",
        extra={
            "request_id": request_id,
            "user_id": current_user.id,
            "session_id": request.session_id,
        },
    )
    
    try:
        # Abandon the session in database (includes authorization check)
        result = abandon_query_session(db, request.session_id, current_user.id)
        
        # Clear Redis cache for all queries in this session
        # Note: We don't have query_ids anymore, but the session is gone
        # Redis will expire naturally, but we can try to clear known keys
        # For now, just log that cache should be cleared
        logger.info(
            "Session abandoned, Redis cache will expire naturally",
            extra={
                "request_id": request_id,
                "session_id": request.session_id,
            }
        )
        
        # Log audit event
        try:
            audit_service.log_from_request(
                db=db,
                request=http_request,
                event_type=AuditEventType.SESSION_ABANDONED,
                user=current_user,
                resource_type="session",
                resource_id=str(request.session_id),
                action=f"Abandoned session {request.session_id}",
                status="success",
                details={
                    "deletion_counts": result["deletion_counts"],
                    "request_id": request_id,
                }
            )
        except Exception as e:
            logger.error(f"Failed to log audit event: {e}", exc_info=True)
        
        duration_ms = (time.time() - start_time) * 1000
        logger.info(
            "API: Session abandoned successfully",
            extra={
                "request_id": request_id,
                "user_id": current_user.id,
                "session_id": request.session_id,
                "deletion_counts": result["deletion_counts"],
                "duration_ms": round(duration_ms, 2),
            },
        )
        
        return AbandonSessionResponse(
            status="success",
            session_id=request.session_id,
            deletion_counts=result["deletion_counts"],
            message=f"Session {request.session_id} abandoned successfully. "
                   f"Deleted {result['deletion_counts']['queries']} queries, "
                   f"{result['deletion_counts']['refinement_steps']} refinement steps."
        )
        
    except ValueError as e:
        # Session not found or authorization failed
        logger.warning(
            f"Failed to abandon session: {e}",
            extra={
                "request_id": request_id,
                "user_id": current_user.id,
                "session_id": request.session_id,
            }
        )
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e)
        )
    except Exception as e:
        logger.error(
            f"Error abandoning session: {e}",
            extra={
                "request_id": request_id,
                "user_id": current_user.id,
                "session_id": request.session_id,
            },
            exc_info=True
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to abandon session: {str(e)}"
        )


# ============================================================
# REAL-TIME PROGRESS TRACKING
# ============================================================

@router.get("/queries/{query_id}/progress")
async def get_query_progress(
    query_id: str,
    current_user = Depends(get_current_user_or_integration),
    db: Session = Depends(get_db)
):
    """
    Get real-time progress for a refinement query.
    
    This endpoint provides polling-based progress tracking for long-running
    refinement operations. Poll this endpoint every 1-2 seconds to get
    live status updates.
    
    Args:
        query_id: Unique query identifier
        
    Returns:
        ProgressStatus with current stage, progress percentage, and metadata
        
    Example response:
        {
            "query_id": "query_abc123",
            "stage": "generating_suggestions",
            "progress": 0.4,
            "message": "Generating refinement suggestions (turn 2 of 3)...",
            "started_at": "2026-02-11T10:30:00Z",
            "updated_at": "2026-02-11T10:30:08Z",
            "elapsed_seconds": 8.2,
            "turn_number": 2,
            "total_turns": 3,
            "llm_calls_made": 2
        }
    """
    from query_refinement_module.services.progress_tracker import get_progress_tracker
    
    request_id = generate_request_id()
    set_request_id(request_id)
    
    # Verify query exists and belongs to user
    query = get_query(db, query_id)
    if not query:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Query {query_id} not found"
        )
    
    # For queries created via API (with session), verify ownership
    if query.session_id:
        from query_refinement_module.db.crud import get_query_session
        query_session = get_query_session(db, query.session_id)
        if query_session and query_session.user_id != current_user.id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Not authorized to view this query's progress"
            )
    
    # Get progress from tracker
    tracker = get_progress_tracker()
    progress = await tracker.get(query_id)
    
    if not progress:
        # No progress tracked - query might be complete or very old
        # Return a synthetic progress based on query state
        from query_refinement_module.models.progress import ProgressStage, ProgressStatus
        from datetime import datetime
        
        # Determine stage from query state
        if query.refined_query:
            stage = ProgressStage.COMPLETED
            message = "Refinement completed"
            progress_pct = 1.0
        else:
            stage = ProgressStage.WAITING_FOR_USER
            message = "Waiting for user interaction"
            progress_pct = 0.5
        
        progress = ProgressStatus(
            query_id=query_id,
            stage=stage,
            progress=progress_pct,
            message=message,
            started_at=query.created_at,
            updated_at=query.updated_at or query.created_at,
            elapsed_seconds=(datetime.utcnow() - query.created_at).total_seconds()
        )
    
    return progress

