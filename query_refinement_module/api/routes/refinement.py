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
    create_refinement_step_metadata,
    update_refinement_step_metadata,
    get_refinement_step_metadata,
    get_query_metadata_summary,
)
from query_refinement_module.api.auth import get_current_user
from query_refinement_module.api.dependencies import get_refinement_manager, get_parallel_config, get_session_manager
from query_refinement_module.schema.registry import get_framework, list_frameworks
from query_refinement_module.api.session_manager import SessionManager
from query_refinement_module.core import (
    QueryRefinementManager,
    is_user_command,
    parse_user_command,
    UserCommand,
)
from query_refinement_module.tracing import generate_request_id, get_logger, OperationTimer, set_request_id, clear_request_id

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
    metadata: Dict[str, Any]


# ==========================================
# Utility Functions
# ==========================================

def _build_next_prompt(session) -> Optional[Dict[str, Any]]:
    """Build the next prompt from the active step."""
    step = session.get_active_step()
    logger.info(f"_build_next_prompt called: active_step={'exists' if step else 'None'}")
    if not step:
        logger.info("  -> No active step, returning None")
        return None
    
    result = {
        "aspect_id": step.refinement_aspect.id,
        "aspect_name": step.refinement_aspect.aspect_name,
        "question": step.refinement_question,
        "description": step.refinement_aspect.aspect_description,
    }
    logger.info(f"  -> Built prompt for '{result['aspect_name']}', question: '{result['question'][:100] if result['question'] else 'None'}...'")
    return result


def _build_command_response(
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
        response.next_prompt = _build_next_prompt(session)
        if force_confirmation_needed:
            response.force_required = True
            response.invalidated_aspects = payload.get("invalidated", [])
        return response
    
    # Command-specific response fields
    if command_type in ["status"]:
        logger.info(f"[_build_command_response] STATUS command - adding step summary")
        response.step_summary = payload.get("summary")
        response.next_prompt = _build_next_prompt(session)
    
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
        response.next_prompt = _build_next_prompt(session)
    
    elif command_type in ["help"]:
        logger.info(f"[_build_command_response] HELP command - showing help text")
        # Help message is in 'message' field, show current prompt
        response.next_prompt = _build_next_prompt(session)
    
    elif command_type in ["submit", "end"]:
        logger.info(f"[_build_command_response] SUBMIT/END command - marking synthesis ready")
        response.synthesis_ready = True
        response.next_prompt = None
    
    elif command_type in ["back", "prev", "previous", "goto", "restart"]:
        logger.info(f"[_build_command_response] NAVIGATION command ({command_type}) - building next prompt")
        # Navigation commands - show new active step
        response.invalidated_aspects = payload.get("invalidated", [])
        response.next_prompt = _build_next_prompt(session)
        logger.info(f"[_build_command_response] Next prompt: {'exists' if response.next_prompt else 'None'}")
        if response.next_prompt:
            logger.info(f"[_build_command_response]   -> Aspect: {response.next_prompt.get('aspect_name')}")
    
    elif command_type in ["skip", "done"]:
        logger.info(f"[_build_command_response] CONTROL command ({command_type}) - advancing to next step")
        # Control commands - advance to next step
        response.next_prompt = _build_next_prompt(session)
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
def start_refinement(
    request: StartRefinementRequest,
    manager: QueryRefinementManager = Depends(get_refinement_manager),
    current_user = Depends(get_current_user),
    db: Session = Depends(get_db),
    parallel_config = Depends(get_parallel_config),
    session_manager: SessionManager = Depends(get_session_manager)
):
    """
    Start a new query refinement workflow.
    
    This initializes a refinement session by:
    1. Loading the specified framework
    2. Analyzing the query to determine what needs refinement
    3. Creating database records for session, query, and steps
    4. Returning the initialization summary and first question(s)
    """
    # Get the refinement framework
    try:
        framework = get_framework(request.framework_name)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Framework '{request.framework_name}' not found: {str(e)}"
        )
    
    # Initialize the refinement session (core logic)
    try:
        session = manager.initialize(
            original_query=request.original_query,
            refinement_framework=framework,
            parallel_config=parallel_config
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
    
    # Get initialization summary
    summary = manager.get_initialization_summary(session)
    next_prompt = _build_next_prompt(session)
    
    # Save session to Redis for subsequent requests
    session_manager.save_session(db_query.id, session)
    
    return StartRefinementResponse(
        session_id=db_session.id,
        query_id=db_query.id,
        summary=summary,
        next_prompt=next_prompt
    )


@router.post("/queries/{query_id}/answer", response_model=Union[SubmitAnswerResponse, CommandResponse])
def submit_answer(
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
        session = manager.initialize(db_query.original_query, framework)
        
        # Restore follow-up history from database
        db_steps = get_query_refinement_steps(db, query_id)
        for db_step in db_steps:
            session_step = next(
                (s for s in session.steps if s.refinement_aspect.aspect_name == db_step.aspect_name),
                None
            )
            if session_step:
                for followup in db_step.followup_history:
                    session_step.follow_up_history.append({
                        'question': followup.question,
                        'response': followup.answer or ''
                    })
                if session_step.follow_up_history:
                    session_step.is_complete = True
                    # Restore the last question asked (needed for proper state)
                    last_followup = db_step.followup_history[-1]
                    session_step.refinement_question = last_followup.question
        
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
            return _build_command_response(
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
                session_manager.save_session(query_id, session)
        
        # Build and return command response
        return _build_command_response(
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
    active_step.follow_up_history.append({
        'question': active_step.refinement_question or active_step.refinement_aspect.aspect_name,
        'response': user_input
    })
    
    # Run follow-up loop to check if aspect is complete
    try:
        result = manager.run_followup_until_clear(session, aspect_id=active_step.refinement_aspect.id)
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
        question=active_step.refinement_question or active_step.refinement_aspect.aspect_name,
        answer=user_input
    )
    
    # Check if aspect is complete
    is_complete = result.get('is_complete', False)
    
    # Get next prompt
    next_prompt = None
    if not is_complete:
        # Still need follow-up on same aspect
        # Read the question from the step object, NOT from result dict
        next_prompt = {
            "aspect_id": active_step.refinement_aspect.id,
            "aspect_name": active_step.refinement_aspect.aspect_name,
            "question": active_step.refinement_question or "",
            "description": active_step.refinement_aspect.aspect_description,
        }
    else:
        # Move to next aspect
        next_prompt = _build_next_prompt(session)
    
    # Save updated session back to Redis
    session_manager.save_session(query_id, session)
    
    return SubmitAnswerResponse(
        refinement_step_id=db_step.id,
        followup_id=db_followup.id,
        is_complete=is_complete,
        next_prompt=next_prompt
    )


@router.get("/queries/{query_id}/status", response_model=GetRefinementStatusResponse)
def get_refinement_status(
    query_id: int,
    manager: QueryRefinementManager = Depends(get_refinement_manager),
    current_user = Depends(get_current_user),
    db: Session = Depends(get_db),
    session_manager: SessionManager = Depends(get_session_manager)
):
    """
    Get the current status of a refinement workflow.
    """
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
        session = manager.initialize(db_query.original_query, framework)
        
        # Restore follow-up history from database
        db_steps = get_query_refinement_steps(db, query_id)
        for db_step in db_steps:
            session_step = next(
                (s for s in session.steps if s.refinement_aspect.aspect_name == db_step.aspect_name),
                None
            )
            if session_step:
                for followup in db_step.followup_history:
                    session_step.follow_up_history.append({
                        'question': followup.question,
                        'response': followup.answer or ''
                    })
                if session_step.follow_up_history:
                    session_step.is_complete = True
                    # Restore the last question asked (needed for proper state)
                    last_followup = db_step.followup_history[-1]
                    session_step.refinement_question = last_followup.question
        
        # Re-cache the reconstructed session
        session_manager.save_session(query_id, session)
    
    summary = manager.get_initialization_summary(session)
    active_step = session.get_active_step()
    
    return GetRefinementStatusResponse(
        query_id=query_id,
        original_query=db_query.original_query,
        refined_query=db_query.refined_query,
        is_complete=session.is_complete(),
        current_aspect=active_step.refinement_aspect.aspect_name if active_step else None,
        aspects_summary=summary
    )


@router.post("/synthesize", response_model=SynthesizeQueryResponse)
def synthesize_refined_query(
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
        session = manager.initialize(db_query.original_query, framework)
        
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
                    session_step.follow_up_history.append({
                        'question': followup.question,
                        'response': followup.answer or ''
                    })
                
                # Mark complete if has answers
                if session_step.follow_up_history:
                    session_step.is_complete = True
    
    # Synthesize refined query
    try:
        synthesis_result = manager.synthesize_refined_query(session)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to synthesize query: {str(e)}"
        )
    
    refined_query = synthesis_result.get('refined_query', '')
    
    # Update database
    update_refined_query(db, request.query_id, refined_query)
    
    # Delete session from Redis (workflow complete)
    session_manager.delete_session(request.query_id)
    
    return SynthesizeQueryResponse(
        query_id=request.query_id,
        refined_query=refined_query,
        used_llm=synthesis_result.get('used_llm', False),
        metadata=synthesis_result.get('metadata', {})
    )
