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
"""
import asyncio
import logging
import time
from fastapi import APIRouter, Depends, HTTPException, status
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
)
from query_refinement_module.api.auth import get_current_user
from query_refinement_module.api.dependencies import get_refinement_manager, get_session_manager
from query_refinement_module.schema.registry import get_framework, list_frameworks
from query_refinement_module.api.session_manager import SessionManager
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


class SynthesizeQueryRequest(BaseModel):
    """Request to synthesize the refined query."""
    query_id: int = Field(..., gt=0, description="ID of the query to synthesize")


class SynthesizeQueryResponse(BaseModel):
    """Response with synthesized refined query."""
    query_id: int
    refined_query: str
    used_llm: bool
    structured_output: Optional[Dict[str, Any]] = None
    metadata: Dict[str, Any]


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
                logger.info(f"  -> Dimension '{step.refinement_aspect.aspect_name}' auto-completed with value: {str(status.get('refinement_aspect_value', ''))[:100]}")
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
        
        # Save session state for state-mutating commands
        if command_payload.get("success", False) and not force_confirmation_needed:
            if command_type in ["back", "prev", "previous", "goto", "restart", "skip", "done", "submit", "end"]:
                logger.info(f"[Query {query_id}] Saving session state after command: {command_type}")
                
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
    
    duration_ms = (time.time() - start_time) * 1000
    logger.info(
        "API: Refinement status retrieved",
        extra={
            "request_id": request_id,
            "user_id": current_user.id,
            "query_id": query_id,
            "is_complete": session.is_complete(),
            "current_aspect": active_step.refinement_aspect.aspect_name if active_step else None,
            "duration_ms": round(duration_ms, 2),
        },
    )
    
    return GetRefinementStatusResponse(
        query_id=query_id,
        original_query=db_query.original_query,
        refined_query=db_query.refined_query,
        is_complete=session.is_complete(),
        current_aspect=active_step.refinement_aspect.aspect_name if active_step else None,
        aspects_summary=summary
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
            
            # Parse JSON
            parsed_data = json.loads(json_str)
            
            # Extract structured fields
            structured_output = {
                'detail_values': parsed_data.get('detail_values'),
                'search_optimized': parsed_data.get('search_optimized'),
                'search_filters': parsed_data.get('search_filters'),
                'terminology': parsed_data.get('terminology'),
                'synthesized_statement': parsed_data.get('synthesized_statement'),
            }
            
            # Use synthesized_statement as refined_query if available
            if parsed_data.get('synthesized_statement'):
                refined_query = parsed_data['synthesized_statement']
                
            logger.info("Successfully parsed JSON from refined_query string")
            
        except (json.JSONDecodeError, ValueError) as e:
            logger.warning(f"Failed to parse JSON from refined_query: {e}")
            # Keep refined_query as-is, structured_output remains None
    
    # Update database
    update_refined_query(db, request.query_id, refined_query)
    
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
        structured_output=structured_output,
        metadata=synthesis_result.get('metadata', {})
    )
