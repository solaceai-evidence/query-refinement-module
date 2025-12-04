"""
Query refinement workflow API routes.

Integrates the core refinement pipeline with API endpoints.
"""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import Dict, Any, Optional

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
from query_refinement_module.api.dependencies import get_refinement_manager, get_parallel_config
from query_refinement_module.schema.registry import get_framework, list_frameworks
from query_refinement_module.core import QueryRefinementManager

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
        description="User's answer to the current question"
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
    if not step:
        return None
    
    return {
        "aspect_id": step.refinement_aspect.id,
        "aspect_name": step.refinement_aspect.name,
        "question": step.analysis_suggested_question or step.refinement_aspect.description,
        "description": step.refinement_aspect.description,
    }


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
    parallel_config = Depends(get_parallel_config)
):
    """
    Start a new query refinement workflow.
    
    This initializes a refinement session by:
    1. Loading the specified framework
    2. Analyzing the query to determine what needs refinement
    3. Creating database records for session, query, and steps
    4. Returning the initialization summary and first question
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
        import logging
        logging.error(f"Error initializing refinement session: {str(e)}", exc_info=True)
        
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
            aspect_name=step.refinement_aspect.name
        )
    
    # Get initialization summary
    summary = manager.get_initialization_summary(session)
    next_prompt = _build_next_prompt(session)
    
    # Store session in user's context (you may want to use Redis or similar)
    # For now, we'll rely on the database to reconstruct state
    
    return StartRefinementResponse(
        session_id=db_session.id,
        query_id=db_query.id,
        summary=summary,
        next_prompt=next_prompt
    )


@router.post("/queries/{query_id}/answer", response_model=SubmitAnswerResponse)
def submit_answer(
    query_id: int,
    request: SubmitAnswerRequest,
    manager: QueryRefinementManager = Depends(get_refinement_manager),
    current_user = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Submit an answer to the current refinement question.
    
    This processes the user's answer and:
    1. Stores it in the follow-up history
    2. Runs the follow-up loop to check if more clarification is needed
    3. Marks the aspect as complete if satisfied
    4. Returns the next question if follow-up is needed, or moves to next aspect
    """
    # Get query and verify ownership
    db_query = get_query(db, query_id)
    if not db_query:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Query not found")
    
    if db_query.session.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")
    
    # Reconstruct the refinement session from database
    # This is a simplified version - you may want to cache sessions
    framework_name = "custom_schemas"  # TODO: Store framework name in session
    framework = get_framework(framework_name)
    session = manager.initialize(db_query.original_query, framework)
    
    # Get the active step
    active_step = session.get_active_step()
    if not active_step:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No active refinement step"
        )
    
    # Add user's answer to follow-up history
    active_step.follow_up_history.append({
        'question': active_step.analysis_suggested_question or active_step.refinement_aspect.name,
        'response': request.answer
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
        import logging
        logging.error(f"Error in follow-up loop: {str(e)}", exc_info=True)
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
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Database refinement step not found"
        )
    
    # Store the follow-up in database
    db_followup = create_followup(
        db,
        refinement_step_id=db_step.id,
        question=active_step.analysis_suggested_question or active_step.refinement_aspect.name,
        answer=request.answer
    )
    
    # Check if aspect is complete
    is_complete = result.get('is_complete', False)
    
    # Get next prompt
    next_prompt = None
    if not is_complete:
        # Still need follow-up on same aspect
        next_prompt = {
            "aspect_id": active_step.refinement_aspect.id,
            "aspect_name": active_step.refinement_aspect.name,
            "question": result.get('followup_question', ''),
            "description": active_step.refinement_aspect.description,
        }
    else:
        # Move to next aspect
        next_prompt = _build_next_prompt(session)
    
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
    db: Session = Depends(get_db)
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
    
    # Reconstruct session to get status
    framework = get_framework(framework_name)
    session = manager.initialize(db_query.original_query, framework)
    
    summary = manager.get_initialization_summary(session)
    active_step = session.get_active_step()
    
    return GetRefinementStatusResponse(
        query_id=query_id,
        original_query=db_query.original_query,
        refined_query=db_query.refined_query,
        is_complete=session.is_complete(),
        current_aspect=active_step.refinement_aspect.name if active_step else None,
        aspects_summary=summary
    )


@router.post("/synthesize", response_model=SynthesizeQueryResponse)
def synthesize_refined_query(
    request: SynthesizeQueryRequest,
    manager: QueryRefinementManager = Depends(get_refinement_manager),
    current_user = Depends(get_current_user),
    db: Session = Depends(get_db)
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
    
    # Reconstruct session with all follow-ups from database
    framework = get_framework(framework_name)
    session = manager.initialize(db_query.original_query, framework)
    
    # Load follow-ups from database and populate session
    db_steps = get_query_refinement_steps(db, request.query_id)
    for db_step in db_steps:
        # Find corresponding step in session
        session_step = next(
            (s for s in session.steps if s.refinement_aspect.name == db_step.aspect_name),
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
    
    return SynthesizeQueryResponse(
        query_id=request.query_id,
        refined_query=refined_query,
        used_llm=synthesis_result.get('used_llm', False),
        metadata=synthesis_result.get('metadata', {})
    )
