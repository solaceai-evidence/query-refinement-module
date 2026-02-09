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
)
from query_refinement_module.api.auth import get_current_user
from query_refinement_module.api.dependencies import get_refinement_manager, get_session_manager
from query_refinement_module.schema.registry import get_framework, list_frameworks
from query_refinement_module.api.session_manager import SessionManager
from query_refinement_module.audit import audit_service
from query_refinement_module.db.models.audit_log import AuditEventType
from query_refinement_module.core import (
    QueryRefinementManager,
    is_user_command,
    parse_user_command,
    UserCommand,
)
from query_refinement_module.tracing import generate_request_id, get_logger, set_request_id

from pydantic import BaseModel, Field, field_validator


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


class StartRefinementResponse(BaseModel):
    """Response with session details and initialization summary."""
    session_id: int = Field(..., description="Database session ID")
    query_id: int = Field(..., description="Database query ID")
    summary: Dict[str, Any] = Field(..., description="Initialization analysis summary")
    next_prompt: Optional[Dict[str, Any]] = Field(None, description="Next question for the user")
    ready_for_synthesis: bool = Field(False, description="True if all aspects are complete and ready for synthesis")


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
    invalidated_aspects: Optional[List[str]] = Field(None, description="Aspects marked for review (/back, /goto)")
    synthesis_ready: Optional[bool] = Field(None, description="True if session ready for synthesis (/submit)")
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
    refined_query: str
    used_llm: bool
    structured_output: Optional[Dict[str, Any]] = None


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
                "aspect_name": step.refinement_aspect.aspect_name,
                "question": step.follow_up_question,
                "description": step.refinement_aspect.aspect_description or "",
            }
            logger.info(f"  -> Using existing question for '{result['aspect_name']}', question: '{result['question'][:100]}...")
            return result
        
        # No question exists - analyze with LLM to determine if dimension is already clear
        try:
            import time
            llm_start = time.time()
            logger.info(f"  -> Generating question via LLM analysis for aspect '{step.refinement_aspect.aspect_name}'")
            logger.info(f"  -> Aspect ID: {step.refinement_aspect.id}, mode: initial")
            
            # Call LLM to analyze dimension with full context
            analysis_result = await _generate_question_with_retry(
                manager=manager,
                session=session,
                aspect_id=step.refinement_aspect.id,
                mode='initial'
            )
            
            llm_duration = (time.time() - llm_start) * 1000
            logger.info(f"  -> LLM call completed in {llm_duration:.2f}ms for aspect '{step.refinement_aspect.aspect_name}'")
            
            # Process the analysis
            status = manager.process_analysis_result(
                session=session,
                aspect_id=step.refinement_aspect.id,
                result=analysis_result
            )
            
            if status['complete']:
                # Dimension is already clear - auto-completed, loop to next
                logger.info(f"  -> Dimension '{step.refinement_aspect.aspect_name}' auto-completed with value: {str(status.get('current', ''))[:100]}")
                continue
            else:
                # Dimension needs clarification - return the question
                result = {
                    "aspect_id": step.refinement_aspect.id,
                    "aspect_name": step.refinement_aspect.aspect_name,
                    "question": status['next_question'],
                    "description": step.refinement_aspect.aspect_description or "",
                }
                logger.info(f"  -> Generated question for '{result['aspect_name']}', question: '{result['question'][:100]}...")
                return result
                
        except Exception as e:
            # LLM failed - use simple fallback
            logger.error(f"  -> LLM analysis failed for aspect '{step.refinement_aspect.aspect_name}': {e}")
            fallback_question = f"Please provide details about {step.refinement_aspect.aspect_name}"
            step.follow_up_question = fallback_question
            
            result = {
                "aspect_id": step.refinement_aspect.id,
                "aspect_name": step.refinement_aspect.aspect_name,
                "question": fallback_question,
                "description": step.refinement_aspect.aspect_description or "",
            }
            logger.info(f"  -> Using fallback question for '{result['aspect_name']}'")
            return result
    
    # Max attempts reached without finding a dimension that needs clarification
    logger.warning(f"_build_next_prompt: Max attempts ({max_attempts}) reached")
    return None


async def _build_command_response(
    manager,
    command_type: str,
    payload: Dict[str, Any],
    session,
    force_confirmation_needed: bool = False
) -> CommandResponse:
    """Build CommandResponse based on command type and execution payload.
    
    Args:
        command_type: The command type (status, back, goto, etc.)
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
        synthesis_ready=None,
        step_summary=None,
        step_list=None,
        force_required=None
    )
    
    # If command failed or needs force confirmation, preserve current prompt
    if not success or force_confirmation_needed:
        logger.info(f"[_build_command_response] Command failed or needs confirmation, preserving current prompt")
        response.next_prompt = await _build_next_prompt(manager, session)
        if force_confirmation_needed:
            response.force_required = True
            response.invalidated_aspects = payload.get("invalidated", [])
        return response
    
    # Command-specific response fields
    if command_type in ["status"]:
        logger.info(f"[_build_command_response] STATUS command - adding step summary")
        response.step_summary = payload.get("summary")
        response.next_prompt = await _build_next_prompt(manager, session)
    
    elif command_type in ["steps"]:
        logger.info(f"[_build_command_response] STEPS command - building step list")
        # Serialize steps to JSON-compatible format
        steps = payload.get("steps", [])
        active_step = session.get_active_step()
        if steps:
            response.step_list = [
                {
                    "aspect_name": step.refinement_aspect.aspect_name,
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
        response.next_prompt = await _build_next_prompt(manager, session)
    
    elif command_type in ["help"]:
        logger.info(f"[_build_command_response] HELP command - showing help text")
        # Help message is in 'message' field, show current prompt
        response.next_prompt = await _build_next_prompt(manager, session)
    
    elif command_type in ["submit", "end"]:
        logger.info(f"[_build_command_response] SUBMIT/END command - marking synthesis ready")
        response.synthesis_ready = True
        response.next_prompt = None
    
    elif command_type in ["clear"]:
        logger.info(f"[_build_command_response] CLEAR command - regenerating question for current aspect")
        # Clear command - regenerate question for current aspect
        response.next_prompt = await _build_next_prompt(manager, session)
        logger.info(f"[_build_command_response] Next prompt: {'exists' if response.next_prompt else 'None'}")
        if response.next_prompt:
            logger.info(f"[_build_command_response]   -> Aspect: {response.next_prompt.get('aspect_name')}")
    
    elif command_type in ["back", "prev", "previous", "goto", "restart"]:
        logger.info(f"[_build_command_response] NAVIGATION command ({command_type}) - building next prompt")
        # Navigation commands - show new active step
        response.invalidated_aspects = payload.get("invalidated", [])
        response.next_prompt = await _build_next_prompt(manager, session)
        logger.info(f"[_build_command_response] Next prompt: {'exists' if response.next_prompt else 'None'}")
        if response.next_prompt:
            logger.info(f"[_build_command_response]   -> Aspect: {response.next_prompt.get('aspect_name')}")
    
    elif command_type in ["skip", "done"]:
        logger.info(f"[_build_command_response] CONTROL command ({command_type}) - advancing to next step")
        # Control commands - advance to next step with LLM analysis and auto-completion
        response.next_prompt = await _build_next_prompt(manager, session)
        logger.info(f"[_build_command_response] Next prompt: {'exists' if response.next_prompt else 'None'}")
        if response.next_prompt:
            has_question = bool(response.next_prompt.get('question'))
            logger.info(f"[_build_command_response]   -> Aspect: {response.next_prompt.get('aspect_name')}, has question: {has_question}")
            if has_question:
                logger.info(f"[_build_command_response]   -> Question preview: {response.next_prompt.get('question')[:100]}")
        else:
            logger.info(f"[_build_command_response]   -> No next prompt (refinement may be complete)")
    
    logger.info(f"[_build_command_response] Response built successfully - next_prompt: {'yes' if response.next_prompt else 'no'}")
    return response


# ==========================================
# Refinement Workflow Endpoints
# ==========================================

@router.get("/frameworks")
def get_available_frameworks():
    """
    List all available refinement frameworks.
    """
    frameworks = list_frameworks()
    return {
        "frameworks": frameworks,
        "count": len(frameworks)
    }


@router.post("/start", response_model=StartRefinementResponse, status_code=status.HTTP_201_CREATED)
async def start_refinement(
    request: StartRefinementRequest,
    manager: QueryRefinementManager = Depends(get_refinement_manager),
    current_user = Depends(get_current_user),
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
    
    # Check if user can start new workflow
    if not current_user.is_superuser and current_user.has_completed_workflow:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You have already completed one refinement workflow. "
                   "For evaluation purposes, only one workflow per participant is allowed. "
                   "Thank you for your participation!"
        )
    
    logger.info(
        "API: Starting refinement workflow",
        extra={
            "request_id": request_id,
            "user_id": current_user.id,
            "framework_name": request.framework_name,
            "query_length": len(request.original_query),
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
    
    # Create refinement steps in database
    for step in session.steps:
        create_refinement_step(
            db,
            query_id=db_query.id,
            aspect_name=step.refinement_aspect.aspect_name
        )
    
    # Generate question on-demand, looping until we find an aspect that needs refinement
    # This auto-cascade continues through aspects that are immediately complete
    max_attempts = len(session.steps)  # Prevent infinite loop
    attempts = 0
    current_step = session.get_next_unrefined_aspect()
    
    while current_step and attempts < max_attempts:
        attempts += 1
        try:
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
                logger.info(f"Aspect '{current_step.refinement_aspect.aspect_name}' needs refinement - stopping auto-cascade")
                break
            
            # Aspect is complete - log and save to database
            logger.info(f"Aspect '{current_step.refinement_aspect.aspect_name}' marked complete immediately - auto-advancing")
            
            # Save final value to database
            if current_step.normalized_value:
                from query_refinement_module.db.crud import update_refinement_step_final_value
                db_steps = get_query_refinement_steps(db, db_query.id)
                db_step = next(
                    (s for s in db_steps if s.aspect_name == current_step.refinement_aspect.aspect_name),
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
            logger.error(f"Error generating question for aspect {current_step.refinement_aspect.aspect_name}: {e}", exc_info=True)
            # Generate fallback question
            current_step.follow_up_question = f"Please provide details about {current_step.refinement_aspect.aspect_name}."
            break
    
    # Get summary (will show all aspects as not yet analyzed)
    summary = {
        "total_aspects": len(session.steps),
        "aspects_needing_refinement": len([s for s in session.steps if not s.is_complete]),
        "aspects_clear": len([s for s in session.steps if s.is_complete]),
        "is_complete": session.is_complete(),
    }
    
    next_prompt = await _build_next_prompt(manager, session)
    
    # Check if all aspects are complete (ready for synthesis)
    ready_for_synthesis = next_prompt is None and session.is_complete()
    
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
        ready_for_synthesis=ready_for_synthesis
    )


@router.post("/queries/{query_id}/answer", response_model=Union[SubmitAnswerResponse, CommandResponse])
async def submit_answer(
    query_id: int,
    request: SubmitAnswerRequest,
    http_request: Request,
    manager: QueryRefinementManager = Depends(get_refinement_manager),
    current_user = Depends(get_current_user),
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
    - Navigation commands (/back, /goto, /restart): Modify session state and return new active step
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
        
        # Restore follow-up history from database
        db_steps = get_query_refinement_steps(db, query_id)
        for db_step in db_steps:
            session_step = next(
                (s for s in session.steps if s.refinement_aspect.aspect_name == db_step.aspect_name),
                None
            )
            if session_step:
                for followup in db_step.followup_history:
                    session_step.conversation_history.append({
                        'question': followup.question,
                        'response': followup.answer or ''
                    })
                if session_step.conversation_history:
                    session_step.is_complete = True
                    # Restore the last question asked (needed for proper state)
                    last_followup = db_step.followup_history[-1]
                    session_step.follow_up_question = last_followup.question
        
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
                force_confirmation_needed=False
            )
        
        # Execute the command
        logger.info(f"[Query {query_id}] Executing command: {cmd_result.command.value}")
        command_payload = session.handle_command(cmd_result)
        command_type = cmd_result.command.value
        
        logger.info(f"[Query {query_id}] Command result - success: {command_payload.get('success')}, message: {command_payload.get('message', '')[:100]}")
        
        # Check if force confirmation is needed for navigation commands
        force_confirmation_needed = False
        if not request.force and command_type in ["back", "prev", "previous", "goto", "restart"]:
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
        active_dimension = active_step.refinement_aspect.aspect_name if active_step else None
        
        # Map command type to specific audit event type
        command_audit_map = {
            "back": AuditEventType.COMMAND_BACK,
            "prev": AuditEventType.COMMAND_BACK,
            "previous": AuditEventType.COMMAND_BACK,
            "restart": AuditEventType.COMMAND_RESTART,
            "clear": AuditEventType.COMMAND_CLEAR,
            "skip": AuditEventType.COMMAND_SKIP,
            "done": AuditEventType.COMMAND_DONE,
            "goto": AuditEventType.COMMAND_GOTO,
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
        
        # Log command execution
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
        
        # Save session state for state-mutating commands
        if command_payload.get("success", False) and not force_confirmation_needed:
            if command_type in ["back", "prev", "previous", "goto", "restart", "skip", "done", "submit", "end"]:
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
                
                # Reset DB record when dimension is cleared (maintain consistency)
                if command_type == "clear":
                    active_step = session.get_active_step()
                    if active_step:
                        db_steps = get_query_refinement_steps(db, query_id)
                        db_step = next(
                            (s for s in db_steps if s.aspect_name == active_step.refinement_aspect.aspect_name),
                            None
                        )
                        if db_step:
                            reset_refinement_step(db, step_id=db_step.id, clear_followup_history=True)
                            logger.info(
                                f"[Query {query_id}] Reset DB record for cleared dimension: '{active_step.refinement_aspect.aspect_name}'",
                                extra={"query_id": query_id, "dimension": active_step.refinement_aspect.aspect_name}
                            )
                
                # Save dimension final values to DB when skip or done commands are used
                if command_type in ["skip", "done"]:
                    from query_refinement_module.db.crud import (
                        mark_refinement_step_skipped,
                        mark_refinement_step_user_ended_early
                    )
                    
                    active_step = session.get_active_step()
                    if active_step and active_step.is_complete:
                        db_steps = get_query_refinement_steps(db, query_id)
                        db_step = next(
                            (s for s in db_steps if s.aspect_name == active_step.refinement_aspect.aspect_name),
                            None
                        )
                        
                        if db_step:
                            if command_type == "skip":
                                mark_refinement_step_skipped(db, db_step.id)
                                logger.info(
                                    f"Marked dimension as skipped in DB: '{active_step.refinement_aspect.aspect_name}'",
                                    extra={"query_id": query_id, "dimension": active_step.refinement_aspect.aspect_name}
                                )
                            elif command_type == "done":
                                mark_refinement_step_user_ended_early(
                                    db,
                                    step_id=db_step.id,
                                    final_value=active_step.normalized_value_as_str if active_step.normalized_value else None
                                )
                                logger.info(
                                    f"Marked dimension as user-completed in DB: '{active_step.refinement_aspect.aspect_name}'",
                                    extra={"query_id": query_id, "dimension": active_step.refinement_aspect.aspect_name}
                                )
                
                session_manager.save_session(query_id, session)
        
        # Build and return command response
        return await _build_command_response(
            manager=manager,
            command_type=command_type,
            payload=command_payload,
            session=session,
            force_confirmation_needed=force_confirmation_needed
        )
    
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
        'question': active_step.follow_up_question or active_step.refinement_aspect.aspect_name,
        'response': user_input
    })
    
    # Analyze the user's answer with LLM (single call, not a loop)
    try:
        # Call LLM once to analyze if dimension is complete or needs more clarification
        analysis_result = await manager.get_analysis_prompts(
            session=session,
            aspect_id=active_step.refinement_aspect.id,
            mode='followup'
        )
        
        # Process the result
        status = manager.process_analysis_result(
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
        (s for s in db_steps if s.aspect_name == active_step.refinement_aspect.aspect_name),
        None
    )
    
    if not db_step:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Database refinement step not found"
        )
    
    # Store the follow-up in database
    db_followup = create_followup(
        db,
        refinement_step_id=db_step.id,
        question=active_step.follow_up_question or active_step.refinement_aspect.aspect_name,
        answer=user_input
    )
    
    # Check if aspect is complete
    is_complete = status.get('complete', False)
    
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
            f"Saved final value to DB for dimension '{active_step.refinement_aspect.aspect_name}'",
            extra={"query_id": query_id, "dimension": active_step.refinement_aspect.aspect_name}
        )
        
        # Trigger webhook: refinement.step_completed
        try:
            from query_refinement_module.services.webhook_service import (
                trigger_webhook_event,
                build_refinement_step_completed_payload
            )
            payload = build_refinement_step_completed_payload(
                query_id=query_id,
                dimension=active_step.refinement_aspect.aspect_name,
                aspect=active_step.refinement_aspect.aspect_name,
                answer=active_step.normalized_value_as_str
            )
            trigger_webhook_event(db, "refinement.step_completed", payload, user_id=current_user.id)
        except Exception as e:
            logger.error(f"Failed to trigger refinement.step_completed webhook: {e}", exc_info=True)
    
    # Get next prompt
    next_prompt = None
    if not is_complete:
        # Still need follow-up on same aspect
        fallback_question = f"Please provide more details about {active_step.refinement_aspect.aspect_name}."
        next_prompt = {
            "aspect_id": active_step.refinement_aspect.id,
            "aspect_name": active_step.refinement_aspect.aspect_name,
            "question": active_step.follow_up_question or fallback_question,
            "description": active_step.refinement_aspect.aspect_description or "",
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
                    logger.info(f"Aspect '{next_step.refinement_aspect.aspect_name}' needs refinement - stopping auto-cascade")
                    break
                
                # Aspect is complete - log and save to database
                logger.info(f"Aspect '{next_step.refinement_aspect.aspect_name}' marked complete immediately - auto-advancing")
                
                # Save final value to database
                if next_step.normalized_value:
                    from query_refinement_module.db.crud import update_refinement_step_final_value
                    db_steps = get_query_refinement_steps(db, query_id)
                    db_step = next(
                        (s for s in db_steps if s.aspect_name == next_step.refinement_aspect.aspect_name),
                        None
                    )
                    if db_step:
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
                # Stop cascading on error, use fallback
                break
        
        # Build prompt after cascade completes
        next_prompt = await _build_next_prompt(manager, session)
    
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
        followup_id=db_followup.id,
        is_complete=is_complete,
        next_prompt=next_prompt,
        ready_for_synthesis=ready_for_synthesis
    )


@router.get("/queries/{query_id}/status", response_model=GetRefinementStatusResponse)
async def get_refinement_status(
    query_id: int,
    manager: QueryRefinementManager = Depends(get_refinement_manager),
    current_user = Depends(get_current_user),
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
        
        # Restore follow-up history from database
        db_steps = get_query_refinement_steps(db, query_id)
        for db_step in db_steps:
            session_step = next(
                (s for s in session.steps if s.refinement_aspect.aspect_name == db_step.aspect_name),
                None
            )
            if session_step:
                for followup in db_step.followup_history:
                    session_step.conversation_history.append({
                        'question': followup.question,
                        'response': followup.answer or ''
                    })
                if session_step.conversation_history:
                    session_step.is_complete = True
                    # Restore the last question asked (needed for proper state)
                    last_followup = db_step.followup_history[-1]
                    session_step.follow_up_question = last_followup.question
        
        # Re-cache the reconstructed session
        session_manager.save_session(query_id, session)
    
    summary = manager.get_initialization_summary(session)
    active_step = session.get_active_step()
    
    # Build next prompt and check if ready for synthesis
    next_prompt = await _build_next_prompt(manager, session)
    ready_for_synthesis = next_prompt is None and session.is_complete()
    
    # Build aspects list for frontend
    aspects = [
        {
            "aspect_id": step.refinement_aspect.id,
            "aspect_name": step.refinement_aspect.aspect_name,
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
                "aspectName": step.refinement_aspect.aspect_name
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
            "current_aspect": active_step.refinement_aspect.aspect_name if active_step else None,
            "ready_for_synthesis": ready_for_synthesis,
            "duration_ms": round(duration_ms, 2),
        },
    )
    
    return GetRefinementStatusResponse(
        query_id=query_id,
        original_query=db_query.original_query,
        refined_query=db_query.refined_query,
        is_complete=session.is_complete(),
        current_aspect=active_step.refinement_aspect.aspect_name if active_step else None,
        aspects_summary=summary,
        next_prompt=next_prompt,
        ready_for_synthesis=ready_for_synthesis,
        aspects=aspects,
        conversation_history=conversation_history
    )


@router.post("/synthesize", response_model=SynthesizeQueryResponse)
async def synthesize_refined_query(
    request: SynthesizeQueryRequest,
    manager: QueryRefinementManager = Depends(get_refinement_manager),
    current_user = Depends(get_current_user),
    db: Session = Depends(get_db),
    session_manager: SessionManager = Depends(get_session_manager)
):
    """
    Synthesize the final refined query from all collected answers.
    
    This combines the original query with all refinement clarifications
    into a well-formed refined query.
    """
    import time
    from query_refinement_module.tracing import generate_request_id, set_request_id, get_request_id
    
    # Generate and set request ID for tracing
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
    
    # Get framework name from database
    framework_name = db_query.session.framework_name
    if not framework_name:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Framework name not found for session")
    
    framework = get_framework(framework_name)
    
    # Try to load session from Redis
    session = session_manager.load_session(request.query_id, framework)
    
    # If session not in Redis, reconstruct from database (fallback)
    if not session:
        logger.warning("Session not found in Redis for query_id=%d, reconstructing from database", request.query_id)
        session = await asyncio.to_thread(
            manager.initialize_sequential,
            db_query.original_query,
            framework,
        )
        
        # Load follow-ups from database and populate session
        db_steps = get_query_refinement_steps(db, request.query_id)
        for db_step in db_steps:
            # Find corresponding step in session
            session_step = next(
                (s for s in session.steps if s.refinement_aspect.aspect_name == db_step.aspect_name),
                None
            )
            if session_step:
                # Load follow-ups for this step
                for followup in db_step.followup_history:
                    session_step.conversation_history.append({
                        'question': followup.question,
                        'response': followup.answer or ''
                    })
                
                # Mark complete if has answers
                if session_step.conversation_history:
                    session_step.is_complete = True
    
    # Trigger webhook: synthesis.started
    try:
        from query_refinement_module.services.webhook_service import (
            trigger_webhook_event,
            build_synthesis_started_payload
        )
        payload = build_synthesis_started_payload(
            query_id=request.query_id,
            initial_query=db_query.original_query
        )
        trigger_webhook_event(db, "synthesis.started", payload, user_id=current_user.id)
    except Exception as e:
        logger.error(f"Failed to trigger synthesis.started webhook: {e}", exc_info=True)
    
    # Synthesize refined query
    try:
        synthesis_result = await manager.synthesize_refined_query(session)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to synthesize query: {str(e)}"
        )
    
    refined_query = synthesis_result.get('refined_query', '')
    
    # Build structured output from synthesis result
    structured_output = None
    if synthesis_result.get('detail_values'):
        # Already parsed by core.py
        structured_output = {
            'detail_values': synthesis_result.get('detail_values'),
            'search_optimized': synthesis_result.get('search_optimized'),
            'search_filters': synthesis_result.get('search_filters'),
            'terminology': synthesis_result.get('terminology'),
            'synthesized_statement': synthesis_result.get('synthesized_statement'),
        }
    elif refined_query and (refined_query.startswith('{') or refined_query.startswith('```')):
        # Try to parse JSON from refined_query string (fallback if core.py parsing failed)
        try:
            import json
            import re
            
            # Strip markdown code fences if present
            json_str = refined_query
            if json_str.startswith('```'):
                # Remove opening fence (```json or ```)
                lines = json_str.split('\n')
                if lines[0].startswith('```'):
                    lines = lines[1:]
                # Remove closing fence
                if lines and lines[-1].strip().startswith('```'):
                    lines = lines[:-1]
                json_str = '\n'.join(lines)
            
            # Check if JSON might be truncated
            if not json_str.rstrip().endswith('}'):
                logger.error(
                    "JSON response appears truncated (doesn't end with '}'), likely hit max_tokens limit",
                    extra={
                        "json_length": len(json_str),
                        "json_preview_end": json_str[-100:] if len(json_str) > 100 else json_str
                    }
                )
                # Attempt to extract synthesized_statement even from partial JSON
                import re
                statement_match = re.search(r'"synthesized_statement"\s*:\s*"([^"]+)"', json_str)
                if statement_match:
                    refined_query = statement_match.group(1)
                    logger.info(f"Extracted synthesized_statement from truncated JSON: {refined_query[:100]}...")
                else:
                    logger.warning("Could not extract synthesized_statement from truncated JSON")
                # Keep structured_output as None for truncated response
                raise ValueError("JSON response was truncated, increase max_tokens")
            
            # Parse JSON
            parsed_data = json.loads(json_str)
            
            # Extract structured fields
            structured_output = {
                'detail_values': parsed_data.get('detail_values'),
                'search_optimized': parsed_data.get('search_optimized'),
                'search_filters': parsed_data.get('search_filters'),
                'terminology': parsed_data.get('terminology'),
                'synthesized_statement': parsed_data.get('synthesized_statement'),
                'dimensions': parsed_data.get('dimensions'),
            }
            
            # Use synthesized_statement as refined_query if available
            if parsed_data.get('synthesized_statement'):
                refined_query = parsed_data['synthesized_statement']
                
            logger.info(
                "Successfully parsed JSON from refined_query string",
                extra={"has_dimensions": 'dimensions' in parsed_data}
            )
            
        except (json.JSONDecodeError, ValueError) as e:
            logger.error(
                f"Failed to parse JSON from refined_query: {e}",
                extra={
                    "error_type": type(e).__name__,
                    "json_preview": json_str[:200] if 'json_str' in locals() else None
                }
            )
            # Keep refined_query as-is, structured_output remains None
    
    # Update database
    update_refined_query(db, request.query_id, refined_query)
    
    # Trigger webhook: synthesis.complete
    try:
        from query_refinement_module.services.webhook_service import (
            trigger_webhook_event,
            build_synthesis_complete_payload
        )
        payload = build_synthesis_complete_payload(
            query_id=request.query_id,
            refined_query=refined_query,
            initial_query=db_query.original_query
        )
        trigger_webhook_event(db, "synthesis.complete", payload, user_id=current_user.id)
    except Exception as e:
        logger.error(f"Failed to trigger synthesis.complete webhook: {e}", exc_info=True)
    
    # Delete session from Redis (workflow complete)
    session_manager.delete_session(request.query_id)
    
    duration_ms = (time.time() - start_time) * 1000
    logger.info(
        "API: Query synthesis completed",
        extra={
            "request_id": request_id_val,
            "user_id": current_user.id,
            "query_id": request.query_id,
            "used_llm": synthesis_result.get('used_llm', False),
            "refined_query_length": len(refined_query),
            "has_structured_output": structured_output is not None,
            "duration_ms": round(duration_ms, 2),
        },
    )
    
    return SynthesizeQueryResponse(
        query_id=request.query_id,
        refined_query=refined_query,
        used_llm=synthesis_result.get('used_llm', False),
        structured_output=structured_output
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
    current_user = Depends(get_current_user),
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
    if not query or query.user_id != current_user.id:
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
        AuditEventType.COMMAND_GOTO,
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
    current_user = Depends(get_current_user),
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
    dependency_context = session.get_dependency_context(active_step.refinement_aspect.id)
    messages = active_step.get_messages(
        query=session.original_query,
        dependency_context=dependency_context
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
