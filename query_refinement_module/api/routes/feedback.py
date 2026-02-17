"""
Feedback API routes.
"""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List
from datetime import datetime, timezone

from query_refinement_module.db.session import get_db
from query_refinement_module.db.crud import (
    create_feedback,
    get_user_feedback,
    get_query_feedback,
    get_query,
    get_query_session,
)
from query_refinement_module.api.schemas import FeedbackCreate, FeedbackResponse
from query_refinement_module.api.auth import get_current_user
from query_refinement_module.api.config import get_settings

router = APIRouter(prefix="/feedback", tags=["Feedback"])


@router.post("/", response_model=FeedbackResponse, status_code=status.HTTP_201_CREATED)
def submit_feedback(
    feedback_data: FeedbackCreate,
    current_user = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Submit feedback and mark workflow complete (grants data consent).
    
    - **query_id**: Optional ID of the query being reviewed
    - **rating**: Optional rating (1-5)
    - **comments**: Optional text feedback
        Notes:
        - Workflow completion (one-workflow limit) is triggered when feedback is submitted for a query.
        - Data consent is explicit via `consent_to_use_data`.
            If consent is false, the query remains unconsented and may be removed by retention policies.
        """
    # If query_id provided, verify it belongs to user
    if feedback_data.query_id:
        query = get_query(db, query_id=feedback_data.query_id)
        if not query:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Query not found")
        
        session = get_query_session(db, session_id=query.session_id)
        if session.user_id != current_user.id:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")
        
        # Mark user workflow complete (unless superuser)
        settings = get_settings()
        if settings.enforce_workflow_limit and not current_user.is_superuser:
            current_user.has_completed_workflow = True

        # Mark query as consented only if explicit consent was provided
        if feedback_data.consent_to_use_data:
            query.consent_given = True
            query.consent_given_at = datetime.now(timezone.utc)
        
        db.commit()
    
    feedback = create_feedback(
        db,
        user_id=current_user.id,
        query_id=feedback_data.query_id,
        rating=feedback_data.rating,
        comments=feedback_data.comments,
        additional_metadata=feedback_data.additional_metadata,
    )
    return feedback


@router.get("/my-feedback", response_model=List[FeedbackResponse])
def get_my_feedback(
    current_user = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Get all feedback submitted by the authenticated user.
    """
    feedback_list = get_user_feedback(db, user_id=current_user.id)
    return feedback_list


@router.get("/query/{query_id}", response_model=List[FeedbackResponse])
def get_feedback_for_query(
    query_id: int,
    current_user = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Get all feedback for a specific query.
    """
    query = get_query(db, query_id=query_id)
    if not query:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Query not found")
    
    # Verify query belongs to user
    session = get_query_session(db, session_id=query.session_id)
    if session.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")
    
    feedback_list = get_query_feedback(db, query_id=query_id)
    return feedback_list
