"""
Query and refinement API routes with audit logging.
"""
from fastapi import APIRouter, Depends, HTTPException, status, Request
from sqlalchemy.orm import Session
from typing import List

from query_refinement_module.db.session import get_db
from query_refinement_module.db.crud import (
    create_query_session,
    get_query_session,
    get_user_sessions,
    end_query_session,
    create_query,
    get_query,
    update_refined_query,
    get_session_queries,
    create_refinement_step,
    get_query_refinement_steps,
    create_followup,
    update_followup_answer,
    get_step_followups,
    verify_step_ownership,
    verify_followup_ownership,
)
from query_refinement_module.api.schemas import (
    QuerySessionResponse,
    QueryCreate,
    QueryResponse,
    QueryUpdate,
    RefinementStepCreate,
    RefinementStepResponse,
    FollowUpCreate,
    FollowUpUpdate,
    FollowUpResponse,
)
from query_refinement_module.api.auth import get_current_user
from query_refinement_module.audit import audit_service
from query_refinement_module.db.models.audit_log import AuditEventType

router = APIRouter(prefix="/queries", tags=["Query Refinement"])


# ==========================================
# Query Session Endpoints
# ==========================================

@router.post("/sessions", response_model=QuerySessionResponse, status_code=status.HTTP_201_CREATED)
def create_session(
    request: Request,
    current_user = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Create a new query refinement session for the authenticated user.
    """
    session = create_query_session(db, user_id=current_user.id)
    
    # Audit session creation
    audit_service.log_from_request(
        db=db,
        request=request,
        event_type=AuditEventType.SESSION_CREATE,
        user=current_user,
        resource_type="session",
        resource_id=str(session.id),
        action="Created new query session",
        status="success"
    )
    
    return session


@router.get("/sessions", response_model=List[QuerySessionResponse])
def list_user_sessions(
    current_user = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    List all query sessions for the authenticated user.
    """
    sessions = get_user_sessions(db, user_id=current_user.id)
    return sessions


@router.get("/sessions/{session_id}", response_model=QuerySessionResponse)
def get_session(
    request: Request,
    session_id: int,
    current_user = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Get details of a specific query session.
    """
    session = get_query_session(db, session_id=session_id)
    if not session:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")
    
    # Verify session belongs to user
    if session.user_id != current_user.id:
        # Audit unauthorized access attempt
        audit_service.log_from_request(
            db=db,
            request=request,
            event_type=AuditEventType.SESSION_ACCESS,
            user=current_user,
            severity="warning",
            resource_type="session",
            resource_id=str(session_id),
            action="Attempted unauthorized session access",
            status="failure",
            details={"reason": "forbidden", "owner_id": session.user_id}
        )
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")
    
    # Audit data access (compliance)
    audit_service.log_data_access(
        db=db,
        user_id=current_user.id,
        username=current_user.username,
        resource_type="session",
        resource_id=str(session.id),
        action="Viewed session details"
    )
    
    return session


@router.post("/sessions/{session_id}/end", response_model=QuerySessionResponse)
def end_session(
    request: Request,
    session_id: int,
    current_user = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Mark a query session as ended.
    """
    session = get_query_session(db, session_id=session_id)
    if not session:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")
    
    # Verify session belongs to user
    if session.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")
    
    session = end_query_session(db, session_id=session_id)
    
    # Audit session end
    audit_service.log_from_request(
        db=db,
        request=request,
        event_type=AuditEventType.SESSION_END,
        user=current_user,
        resource_type="session",
        resource_id=str(session.id),
        action="Ended query session",
        status="success",
        details={"ended_at": session.ended_at.isoformat() if session.ended_at else None}
    )
    
    return session


# ==========================================
# Query Endpoints
# ==========================================

@router.post("/", response_model=QueryResponse, status_code=status.HTTP_201_CREATED)
def create_new_query(
    query_data: QueryCreate,
    current_user = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Create a new query in a session.
    """
    # Verify session exists and belongs to user
    session = get_query_session(db, session_id=query_data.session_id)
    if not session:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")
    if session.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")
    
    query = create_query(db, session_id=query_data.session_id, original_query=query_data.original_query)
    return query


@router.get("/{query_id}", response_model=QueryResponse)
def get_query_details(
    query_id: int,
    current_user = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Get details of a specific query.
    """
    query = get_query(db, query_id=query_id)
    if not query:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Query not found")
    
    # Verify query belongs to user's session
    session = get_query_session(db, session_id=query.session_id)
    if session.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")
    
    return query


@router.put("/{query_id}", response_model=QueryResponse)
def update_query(
    query_id: int,
    query_update: QueryUpdate,
    current_user = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Update the refined query text.
    """
    query = get_query(db, query_id=query_id)
    if not query:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Query not found")
    
    # Verify query belongs to user's session
    session = get_query_session(db, session_id=query.session_id)
    if session.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")
    
    query = update_refined_query(db, query_id=query_id, refined_query=query_update.refined_query)
    return query


@router.get("/sessions/{session_id}/queries", response_model=List[QueryResponse])
def list_session_queries(
    session_id: int,
    current_user = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    List all queries in a session.
    """
    session = get_query_session(db, session_id=session_id)
    if not session:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")
    if session.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")
    
    queries = get_session_queries(db, session_id=session_id)
    return queries


# ==========================================
# Refinement Step Endpoints
# ==========================================

@router.post("/refinement-steps", response_model=RefinementStepResponse, status_code=status.HTTP_201_CREATED)
def create_step(
    step_data: RefinementStepCreate,
    current_user = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Create a new refinement step for a query.
    """
    query = get_query(db, query_id=step_data.query_id)
    if not query:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Query not found")
    
    # Verify query belongs to user's session
    session = get_query_session(db, session_id=query.session_id)
    if session.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")
    
    step = create_refinement_step(
        db,
        query_id=step_data.query_id,
        aspect_name=step_data.aspect_name,
        aspect_id=step_data.aspect_id,
    )
    return step


@router.get("/{query_id}/refinement-steps", response_model=List[RefinementStepResponse])
def list_query_steps(
    query_id: int,
    current_user = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    List all refinement steps for a query.
    """
    query = get_query(db, query_id=query_id)
    if not query:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Query not found")
    
    # Verify query belongs to user's session
    session = get_query_session(db, session_id=query.session_id)
    if session.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")
    
    steps = get_query_refinement_steps(db, query_id=query_id)
    return steps


# ==========================================
# Follow-up History Endpoints
# ==========================================

@router.post("/followups", response_model=FollowUpResponse, status_code=status.HTTP_201_CREATED)
def create_followup_entry(
    followup_data: FollowUpCreate,
    current_user = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Create a new follow-up entry for a refinement step.
    """
    # Verify ownership: step → query → session → user
    step = verify_step_ownership(db, followup_data.refinement_step_id, current_user.id)
    if not step:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, 
            detail="Refinement step not found or access denied"
        )
    
    followup = create_followup(
        db,
        refinement_step_id=followup_data.refinement_step_id,
        question=followup_data.question,
        answer=followup_data.answer
    )
    return followup


@router.put("/followups/{followup_id}", response_model=FollowUpResponse)
def update_followup(
    followup_id: int,
    followup_update: FollowUpUpdate,
    current_user = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Update a follow-up answer.
    """
    # Verify ownership: followup → step → query → session → user
    existing = verify_followup_ownership(db, followup_id, current_user.id)
    if not existing:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, 
            detail="Follow-up not found or access denied"
        )
    
    followup = update_followup_answer(db, followup_id=followup_id, answer=followup_update.answer)
    return followup


@router.get("/refinement-steps/{step_id}/followups", response_model=List[FollowUpResponse])
def list_step_followups(
    step_id: int,
    current_user = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    List all follow-up entries for a refinement step.
    """
    # Verify ownership: step → query → session → user
    step = verify_step_ownership(db, step_id, current_user.id)
    if not step:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, 
            detail="Refinement step not found or access denied"
        )
    
    followups = get_step_followups(db, refinement_step_id=step_id)
    return followups
