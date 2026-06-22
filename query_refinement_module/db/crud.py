"""
CRUD utility functions for database operations.

This module provides comprehensive database access functions with integrated
logging and tracing support. All functions follow consistent patterns:
- Logging at entry and exit points
- Error handling with detailed logging
- Request ID propagation for distributed tracing
- Performance metrics capture
"""
import logging
from sqlalchemy.orm import Session
from typing import Optional, List, Dict, Any
from query_refinement_module.db.models.user import User
from query_refinement_module.db.models.query_session import QuerySession
from query_refinement_module.db.models.query import Query
from query_refinement_module.db.models.refinement_step import RefinementStep
from query_refinement_module.db.models.refinement_step_metadata import RefinementStepMetadata
from query_refinement_module.db.models.followup_history import FollowUpHistory
from query_refinement_module.db.models.feedback import Feedback
from query_refinement_module.db.models.user_framework_access import UserFrameworkAccess
from query_refinement_module.tracing import get_logger
from passlib.context import CryptContext

# Logger for CRUD operations - will use request context when available
logger = get_logger(__name__)

# Password hashing context
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


# ==========================================
# User CRUD Operations
# ==========================================

def create_user(db: Session, username: str, password: str, email: Optional[str] = None, name: Optional[str] = None) -> User:
    """Create a new user with hashed password.
    
    Args:
        db: Database session
        username: Unique username (required)
        password: Plain text password to hash
        email: Optional email address
        name: Optional display name
    
    Returns:
        Created User instance
    """
    # Truncate password to 72 characters for bcrypt compatibility
    truncated_password = password[:72]
    password_hash = pwd_context.hash(truncated_password)
    user = User(username=username, email=email, name=name, password_hash=password_hash)
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def get_user_by_username(db: Session, username: str) -> Optional[User]:
    """Retrieve a user by username."""
    return db.query(User).filter(User.username == username).first()


def get_user_by_email(db: Session, email: str) -> Optional[User]:
    """Retrieve a user by email."""
    return db.query(User).filter(User.email == email).first()


def get_user_by_username_or_email(db: Session, identifier: str) -> Optional[User]:
    """Retrieve a user by username or email.
    
    Checks if identifier contains '@' to determine if it's an email,
    otherwise treats it as username.
    
    Args:
        db: Database session
        identifier: Username or email address
        
    Returns:
        User instance if found, None otherwise
    """
    if '@' in identifier:
        return get_user_by_email(db, identifier)
    else:
        return get_user_by_username(db, identifier)


def get_user_by_id(db: Session, user_id: int) -> Optional[User]:
    """Retrieve a user by ID."""
    return db.query(User).filter(User.id == user_id).first()


def verify_user_password(db: Session, identifier: str, password: str) -> Optional[User]:
    """Verify user credentials and return user if valid.
    
    Args:
        db: Database session
        identifier: Username or email address
        password: Plain text password to verify
        
    Returns:
        User instance if credentials valid, None otherwise
    """
    user = get_user_by_username_or_email(db, identifier)
    if user:
        # Truncate password to 72 characters for bcrypt compatibility
        truncated_password = password[:72]
        if pwd_context.verify(truncated_password, user.password_hash):
            return user
    return None


def assign_user_framework_access(db: Session, user_id: int, framework_name: str) -> UserFrameworkAccess:
    """Assign a framework to a user (idempotent)."""
    existing = db.query(UserFrameworkAccess).filter(
        UserFrameworkAccess.user_id == user_id,
        UserFrameworkAccess.framework_name == framework_name,
    ).first()
    if existing:
        return existing

    mapping = UserFrameworkAccess(user_id=user_id, framework_name=framework_name)
    db.add(mapping)
    db.commit()
    db.refresh(mapping)
    return mapping


def revoke_user_framework_access(db: Session, user_id: int, framework_name: str) -> bool:
    """Revoke a framework assignment from a user."""
    deleted = db.query(UserFrameworkAccess).filter(
        UserFrameworkAccess.user_id == user_id,
        UserFrameworkAccess.framework_name == framework_name,
    ).delete(synchronize_session=False)
    db.commit()
    return deleted > 0


def get_user_framework_names(db: Session, user_id: int) -> List[str]:
    """Get all framework names assigned to a user."""
    rows = db.query(UserFrameworkAccess.framework_name).filter(
        UserFrameworkAccess.user_id == user_id
    ).all()
    return [row[0] for row in rows]


def user_has_framework_access(db: Session, user_id: int, framework_name: str) -> bool:
    """Check whether a user can access a framework."""
    entry = db.query(UserFrameworkAccess.id).filter(
        UserFrameworkAccess.user_id == user_id,
        UserFrameworkAccess.framework_name == framework_name,
    ).first()
    return entry is not None


# ==========================================
# QuerySession CRUD Operations
# ==========================================

def create_query_session(db: Session, user_id: int, framework_name: str = None) -> QuerySession:
    """Create a new query session for a user."""
    session = QuerySession(user_id=user_id, status="active", framework_name=framework_name)
    db.add(session)
    db.commit()
    db.refresh(session)
    return session


def get_query_session(db: Session, session_id: int) -> Optional[QuerySession]:
    """Retrieve a query session by ID."""
    return db.query(QuerySession).filter(QuerySession.id == session_id).first()


def get_user_sessions(db: Session, user_id: int) -> List[QuerySession]:
    """Retrieve all sessions for a user."""
    return db.query(QuerySession).filter(QuerySession.user_id == user_id).all()


def end_query_session(db: Session, session_id: int) -> Optional[QuerySession]:
    """Mark a query session as ended."""
    session = get_query_session(db, session_id)
    if session:
        from datetime import datetime, timezone
        session.ended_at = datetime.now(timezone.utc)
        session.status = "completed"
        db.commit()
        db.refresh(session)
    return session


# ==========================================
# Ownership Verification Helpers
# ==========================================

def verify_step_ownership(db: Session, step_id: int, user_id: int) -> Optional[RefinementStep]:
    """
    Verify that a refinement step belongs to a user via the chain:
    RefinementStep → Query → QuerySession → User
    
    Returns the step if ownership is verified, None otherwise.
    """
    step = db.query(RefinementStep).filter(RefinementStep.id == step_id).first()
    if not step:
        return None
    
    query = db.query(Query).filter(Query.id == step.query_id).first()
    if not query:
        return None
    
    session = db.query(QuerySession).filter(QuerySession.id == query.session_id).first()
    if not session or session.user_id != user_id:
        return None
    
    return step


def verify_followup_ownership(db: Session, followup_id: int, user_id: int) -> Optional[FollowUpHistory]:
    """
    Verify that a followup belongs to a user via the chain:
    FollowUpHistory → RefinementStep → Query → QuerySession → User
    
    Returns the followup if ownership is verified, None otherwise.
    """
    followup = db.query(FollowUpHistory).filter(FollowUpHistory.id == followup_id).first()
    if not followup:
        return None
    
    step = verify_step_ownership(db, followup.refinement_step_id, user_id)
    if not step:
        return None
    
    return followup


# ==========================================
# Query CRUD Operations
# ==========================================

def create_query(db: Session, session_id: int, original_query: str) -> Query:
    """Create a new query in a session."""
    query = Query(session_id=session_id, original_query=original_query)
    db.add(query)
    db.commit()
    db.refresh(query)
    return query


def get_query(db: Session, query_id: int) -> Optional[Query]:
    """Retrieve a query by ID."""
    return db.query(Query).filter(Query.id == query_id).first()


def update_refined_query(db: Session, query_id: int, refined_query: str) -> Optional[Query]:
    """Update the refined query text."""
    query = get_query(db, query_id)
    if query:
        query.refined_query = refined_query
        db.commit()
        db.refresh(query)
    return query


def get_session_queries(db: Session, session_id: int) -> List[Query]:
    """Retrieve all queries for a session."""
    return db.query(Query).filter(Query.session_id == session_id).all()


def save_query_refinement_response(
    db: Session,
    query_id: int,
    response: Dict[str, Any],
) -> Optional[Query]:
    """
    Save the complete QueryRefinementResponse to the Query table.
    
    Called when session is complete to persist all response fields
    for evaluation purposes.
    
    Persists canonical QueryRefinementResponse fields.
    
    Args:
        db: Database session
        query_id: ID of the query
        response: Dict containing QueryRefinementResponse fields from core.synthesize_refined_query()
        
    Returns:
        Updated Query or None if not found
    """
    from datetime import datetime, timezone
    
    query = get_query(db, query_id)
    if query:
        # Set completion timestamp
        query.completed_at = datetime.now(timezone.utc)
        
        integrated_statement = response.get('integrated_statement')
        dimensions_specifications = response.get('dimensions_specifications')
        metadata_payload = response.get('metadata')

        processing_log = response.get('processing_log')

        # Store canonical synthesis fields.
        if integrated_statement is not None:
            query.integrated_statement = integrated_statement
            # Also update legacy refined_query field
            query.refined_query = integrated_statement
        
        if dimensions_specifications is not None:
            query.dimensions_specifications = dimensions_specifications
        
        # Store search optimization
        if 'search_optimized' in response:
            query.search_optimized = response['search_optimized']
        
        # Store search filters
        if 'search_filters' in response:
            query.search_filters = response['search_filters']
        
        # Store terminology
        if 'terminology' in response:
            query.terminology = response['terminology']

        # Store optional post-synthesis search expansion levels.
        if 'search_expansion_levels' in response:
            query.search_expansion_levels = response['search_expansion_levels']

        # Store optional metadata and processing logs when present.
        if metadata_payload is not None:
            query.synthesis_metadata = metadata_payload

        if processing_log is not None:
            query.processing_log = processing_log
        
        db.commit()
        db.refresh(query)
    return query


# ==========================================
# RefinementStep CRUD Operations
# ==========================================

def create_refinement_step(
    db: Session,
    query_id: int,
    aspect_name: str,
    aspect_id: Optional[str] = None,
) -> RefinementStep:
    """Create a new refinement step for a query."""
    step = RefinementStep(
        query_id=query_id,
        aspect_id=aspect_id or aspect_name,
        aspect_name=aspect_name,
    )
    db.add(step)
    db.commit()
    db.refresh(step)
    return step


def get_refinement_step(db: Session, step_id: int) -> Optional[RefinementStep]:
    """Retrieve a refinement step by ID."""
    return db.query(RefinementStep).filter(RefinementStep.id == step_id).first()


def get_refinement_step_by_aspect(
    db: Session,
    query_id: int,
    aspect_name: Optional[str] = None,
    aspect_id: Optional[str] = None,
) -> Optional[RefinementStep]:
    """Retrieve a refinement step by query ID and stable aspect identifier."""
    query = db.query(RefinementStep).filter(RefinementStep.query_id == query_id)

    if aspect_id:
        step = query.filter(RefinementStep.aspect_id == aspect_id).first()
        if step is not None:
            return step

    if aspect_name:
        return query.filter(RefinementStep.aspect_name == aspect_name).first()

    raise ValueError("Either aspect_id or aspect_name must be provided")


def get_query_refinement_steps(db: Session, query_id: int) -> List[RefinementStep]:
    """Retrieve all refinement steps for a query."""
    return db.query(RefinementStep).filter(RefinementStep.query_id == query_id).all()


def update_refinement_step_final_value(
    db: Session,
    step_id: int,
    final_value: str,
    is_complete: bool = True,
    was_skipped: bool = False,
    user_ended_early: bool = False,
) -> Optional[RefinementStep]:
    """
    Update the final refined value for a refinement step.
    
    This is the ONLY value persisted for each dimension - no conversation history.
    
    Args:
        db: Database session
        step_id: ID of the refinement step
        final_value: The final refined value to store
        is_complete: Whether refinement is complete (default: True)
        was_skipped: Whether user skipped this aspect (default: False)
        user_ended_early: Whether user used /done before LLM marked complete (evaluation)
        
    Returns:
        Updated RefinementStep or None if not found
    """
    step = get_refinement_step(db, step_id)
    if step:
        step.final_value = final_value
        step.is_complete = is_complete
        step.was_skipped = was_skipped
        step.user_ended_early = user_ended_early
        db.commit()
        db.refresh(step)
    return step


def mark_refinement_step_skipped(db: Session, step_id: int) -> Optional[RefinementStep]:
    """Mark a refinement step as skipped by user."""
    return update_refinement_step_final_value(
        db, step_id, final_value=None, is_complete=False, was_skipped=True
    )


def mark_refinement_step_user_ended_early(
    db: Session,
    step_id: int,
    final_value: Optional[str] = None,
) -> Optional[RefinementStep]:
    """
    Mark a refinement step as completed early by user (/done command).
    
    This is for evaluation: tracks when user was satisfied before LLM.
    
    Args:
        db: Database session
        step_id: ID of the refinement step
        final_value: The value captured so far (may be partial)
        
    Returns:
        Updated RefinementStep or None if not found
    """
    return update_refinement_step_final_value(
        db, step_id, final_value=final_value, is_complete=True, 
        was_skipped=False, user_ended_early=True
    )


def update_refinement_step_generated_question(
    db: Session,
    step_id: int,
    question: str,
) -> Optional[RefinementStep]:
    """
    Persist the LLM-generated question for a refinement step.

    Allows the question to survive server restarts and session TTL expiry so
    that read-only commands (/steps, /status, /help) can return the current
    question without triggering a new LLM call.
    """
    step = get_refinement_step(db, step_id)
    if step:
        step.generated_question = question
        db.commit()
        db.refresh(step)
    return step


def update_refinement_step_generated_examples(
    db: Session,
    step_id: int,
    examples: list,
) -> Optional[RefinementStep]:
    """
    Persist the LLM-generated quick-reply examples for a refinement step.

    Allows the structured button options to survive server restarts alongside
    the generated_question, so sessions can be fully restored without a new LLM call.
    """
    step = get_refinement_step(db, step_id)
    if step:
        step.generated_examples = examples
        db.commit()
        db.refresh(step)
    return step


def delete_refinement_steps_by_aspects(
    db: Session,
    query_id: int,
    aspect_names: Optional[List[str]] = None,
    aspect_ids: Optional[List[str]] = None,
) -> int:
    """
    Delete refinement steps by aspect names (cascade delete for session truncation).
    
    Used when /back or /restart commands truncate the session - maintains referential
    integrity between Redis session state and database records.
    
    Uses ORM-level delete to trigger cascade relationships (e.g., followup_history).
    
    Args:
        db: Database session
        query_id: Query ID to scope the deletion
        aspect_names: List of aspect display names to delete
        aspect_ids: List of stable aspect identifiers to delete
        
    Returns:
        Number of records deleted
    """
    if not aspect_names and not aspect_ids:
        return 0

    query = db.query(RefinementStep).filter(RefinementStep.query_id == query_id)
    if aspect_ids:
        query = query.filter(RefinementStep.aspect_id.in_(aspect_ids))
    elif aspect_names:
        query = query.filter(RefinementStep.aspect_name.in_(aspect_names))

    # Use ORM-level delete to trigger cascade relationships
    steps_to_delete = query.all()
    
    deleted_count = len(steps_to_delete)
    
    try:
        for step in steps_to_delete:
            db.delete(step)
        db.commit()
    except Exception:
        db.rollback()
        raise
    return deleted_count


def reset_refinement_step(
    db: Session,
    step_id: int,
    clear_followup_history: bool = True
) -> Optional[RefinementStep]:
    """
    Reset a refinement step to incomplete state (for /clear command).
    
    Maintains database consistency when user clears a dimension in Redis session.
    Resets completion status and optionally clears follow-up history.
    
    Args:
        db: Database session
        step_id: ID of the refinement step to reset
        clear_followup_history: Whether to delete follow-up history (default: True)
        
    Returns:
        Reset RefinementStep or None if not found
    """
    step = get_refinement_step(db, step_id)
    if step:
        step.final_value = None
        step.is_complete = False
        step.was_skipped = False
        step.user_ended_early = False
        
        # Optionally clear follow-up history to fully reset dimension
        if clear_followup_history:
            db.query(FollowUpHistory).filter(
                FollowUpHistory.refinement_step_id == step_id
            ).delete(synchronize_session=False)
        
        db.commit()
        db.refresh(step)
    return step


# ==========================================
# FollowUpHistory CRUD Operations (Audit Trail)
# ==========================================
# Note: These functions persist the conversation history for audit/research purposes.
# The session state doesn't keep conversation history (only final values), but we
# record each Q&A exchange in the database for traceability and evaluation.

def create_followup(
    db: Session, refinement_step_id: int, question: str, answer: Optional[str] = None
) -> FollowUpHistory:
    """
    Create a new follow-up history entry for audit trail.
    
    Records each question-answer exchange for research evaluation purposes.
    Session state stores only final values; this provides full conversation log.
    """
    followup = FollowUpHistory(
        refinement_step_id=refinement_step_id, question=question, answer=answer
    )
    db.add(followup)
    db.commit()
    db.refresh(followup)
    return followup


def update_followup_answer(db: Session, followup_id: int, answer: str) -> Optional[FollowUpHistory]:
    """
    Update the answer for a follow-up question (audit trail).
    """
    followup = db.query(FollowUpHistory).filter(FollowUpHistory.id == followup_id).first()
    if followup:
        followup.answer = answer
        db.commit()
        db.refresh(followup)
    return followup


def get_step_followups(db: Session, refinement_step_id: int) -> List[FollowUpHistory]:
    """
    Retrieve all follow-up history for a refinement step (audit trail).
    
    Used for reviewing conversation history and research analysis.
    """
    return (
        db.query(FollowUpHistory)
        .filter(FollowUpHistory.refinement_step_id == refinement_step_id)
        .all()
    )


# ==========================================
# Feedback CRUD Operations
# ==========================================

def create_feedback(
    db: Session,
    user_id: int,
    query_id: Optional[int] = None,
    rating: Optional[int] = None,
    comments: Optional[str] = None,
    additional_metadata: Optional[Dict[str, Any]] = None,
) -> Feedback:
    """Create a new feedback entry."""
    feedback = Feedback(
        user_id=user_id,
        query_id=query_id,
        rating=rating,
        comments=comments,
        additional_metadata=additional_metadata,
    )
    db.add(feedback)
    db.commit()
    db.refresh(feedback)
    return feedback


def get_user_feedback(db: Session, user_id: int) -> List[Feedback]:
    """Retrieve all feedback for a user."""
    return db.query(Feedback).filter(Feedback.user_id == user_id).all()


def get_query_feedback(db: Session, query_id: int) -> List[Feedback]:
    """Retrieve all feedback for a query."""
    return db.query(Feedback).filter(Feedback.query_id == query_id).all()


# ==========================================
# Refinement Step Metadata CRUD Operations
# ==========================================

def create_refinement_step_metadata(
    db: Session,
    refinement_step_id: int,
    analysis_result: Optional[str] = None,
    followup_question: Optional[str] = None,
    llm_provider: Optional[str] = None,
    llm_model: Optional[str] = None,
    prompt_tokens: Optional[int] = None,
    completion_tokens: Optional[int] = None,
    total_tokens: Optional[int] = None,
    estimated_cost_usd: Optional[float] = None,
    llm_duration_seconds: Optional[float] = None,
    processing_duration_seconds: Optional[float] = None,
    status: Optional[str] = None,
    error_message: Optional[str] = None,
    retry_count: int = 0,
    additional_metadata: Optional[Dict[str, Any]] = None,
    request_id: Optional[str] = None,
) -> RefinementStepMetadata:
    """
    Create metadata record for a refinement step with comprehensive tracking.
    
    This function captures all relevant metadata about a refinement step execution,
    including LLM usage metrics, timing information, and status tracking.
    
    Args:
        db: Database session
        refinement_step_id: ID of the associated refinement step
        analysis_result: The analysis text generated by the LLM
        followup_question: The follow-up question generated for the user
        llm_provider: LLM provider used (e.g., 'openai', 'anthropic')
        llm_model: Model identifier (e.g., 'gpt-4', 'claude-3-opus')
        prompt_tokens: Number of tokens in the prompt
        completion_tokens: Number of tokens in the completion
        total_tokens: Total tokens used (prompt + completion)
        estimated_cost_usd: Estimated cost in USD
        llm_duration_seconds: Time taken for LLM API call
        processing_duration_seconds: Total processing time
        status: Status of the step (e.g., 'completed', 'failed')
        error_message: Error details if the step failed
        retry_count: Number of retry attempts
        additional_metadata: Flexible JSON data for custom metrics
        request_id: Request ID for distributed tracing
        
    Returns:
        Created RefinementStepMetadata instance
    """
    log = get_logger(__name__, request_id=request_id)
    log.info(
        f"Creating metadata for refinement_step_id={refinement_step_id}, "
        f"provider={llm_provider}, model={llm_model}, tokens={total_tokens}"
    )
    
    metadata = RefinementStepMetadata(
        refinement_step_id=refinement_step_id,
        analysis_result=analysis_result,
        followup_question=followup_question,
        llm_provider=llm_provider,
        llm_model=llm_model,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        total_tokens=total_tokens,
        estimated_cost_usd=estimated_cost_usd,
        llm_duration_seconds=llm_duration_seconds,
        processing_duration_seconds=processing_duration_seconds,
        status=status or 'pending',
        error_message=error_message,
        retry_count=retry_count,
        additional_metadata=additional_metadata,
    )
    
    try:
        db.add(metadata)
        db.commit()
        db.refresh(metadata)
        log.info(f"Successfully created metadata id={metadata.id}")
        return metadata
    except Exception as e:
        log.error(f"Failed to create metadata: {str(e)}", exc_info=True)
        db.rollback()
        raise


def update_refinement_step_metadata(
    db: Session,
    metadata_id: int,
    analysis_result: Optional[str] = None,
    followup_question: Optional[str] = None,
    llm_provider: Optional[str] = None,
    llm_model: Optional[str] = None,
    prompt_tokens: Optional[int] = None,
    completion_tokens: Optional[int] = None,
    total_tokens: Optional[int] = None,
    estimated_cost_usd: Optional[float] = None,
    llm_duration_seconds: Optional[float] = None,
    processing_duration_seconds: Optional[float] = None,
    status: Optional[str] = None,
    error_message: Optional[str] = None,
    retry_count: Optional[int] = None,
    additional_metadata: Optional[Dict[str, Any]] = None,
    request_id: Optional[str] = None,
) -> Optional[RefinementStepMetadata]:
    """
    Update existing refinement step metadata with new information.
    
    This function allows partial updates - only provided fields are updated.
    Useful for incremental metadata capture during step execution.
    
    Args:
        db: Database session
        metadata_id: ID of the metadata record to update
        (other args same as create_refinement_step_metadata)
        
    Returns:
        Updated RefinementStepMetadata instance, or None if not found
    """
    log = get_logger(__name__, request_id=request_id)
    log.info(f"Updating metadata id={metadata_id}")
    
    metadata = db.query(RefinementStepMetadata).filter(
        RefinementStepMetadata.id == metadata_id
    ).first()
    
    if not metadata:
        log.warning(f"Metadata id={metadata_id} not found")
        return None
    
    # Update only provided fields
    if analysis_result is not None:
        metadata.analysis_result = analysis_result
    if followup_question is not None:
        metadata.followup_question = followup_question
    if llm_provider is not None:
        metadata.llm_provider = llm_provider
    if llm_model is not None:
        metadata.llm_model = llm_model
    if prompt_tokens is not None:
        metadata.prompt_tokens = prompt_tokens
    if completion_tokens is not None:
        metadata.completion_tokens = completion_tokens
    if total_tokens is not None:
        metadata.total_tokens = total_tokens
    if estimated_cost_usd is not None:
        metadata.estimated_cost_usd = estimated_cost_usd
    if llm_duration_seconds is not None:
        metadata.llm_duration_seconds = llm_duration_seconds
    if processing_duration_seconds is not None:
        metadata.processing_duration_seconds = processing_duration_seconds
    if status is not None:
        metadata.status = status
    if error_message is not None:
        metadata.error_message = error_message
    if retry_count is not None:
        metadata.retry_count = retry_count
    if additional_metadata is not None:
        # Merge with existing metadata if present
        if metadata.additional_metadata:
            metadata.additional_metadata.update(additional_metadata)
        else:
            metadata.additional_metadata = additional_metadata
    
    try:
        db.commit()
        db.refresh(metadata)
        log.info(f"Successfully updated metadata id={metadata_id}")
        return metadata
    except Exception as e:
        log.error(f"Failed to update metadata id={metadata_id}: {str(e)}", exc_info=True)
        db.rollback()
        raise


def get_refinement_step_metadata(
    db: Session,
    refinement_step_id: int,
    request_id: Optional[str] = None,
) -> Optional[RefinementStepMetadata]:
    """
    Retrieve metadata for a specific refinement step.
    
    Args:
        db: Database session
        refinement_step_id: ID of the refinement step
        request_id: Request ID for tracing
        
    Returns:
        RefinementStepMetadata instance if found, None otherwise
    """
    log = get_logger(__name__, request_id=request_id)
    log.debug(f"Retrieving metadata for refinement_step_id={refinement_step_id}")
    
    metadata = db.query(RefinementStepMetadata).filter(
        RefinementStepMetadata.refinement_step_id == refinement_step_id
    ).first()
    
    if metadata:
        log.debug(f"Found metadata id={metadata.id}")
    else:
        log.debug(f"No metadata found for refinement_step_id={refinement_step_id}")
    
    return metadata


def get_query_metadata_summary(
    db: Session,
    query_id: int,
    request_id: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Get aggregated metadata summary for all steps in a query.
    
    This provides a comprehensive overview of LLM usage, costs, and performance
    for an entire query refinement session.
    
    Args:
        db: Database session
        query_id: ID of the query
        request_id: Request ID for tracing
        
    Returns:
        Dictionary containing aggregated metrics:
        - total_tokens: Sum of all tokens used
        - total_cost_usd: Sum of all estimated costs
        - avg_duration_seconds: Average LLM call duration
        - step_count: Number of steps with metadata
        - status_counts: Breakdown by status
        - providers_used: List of unique providers
    """
    log = get_logger(__name__, request_id=request_id)
    log.info(f"Generating metadata summary for query_id={query_id}")
    
    # Get all refinement steps for this query
    steps = db.query(RefinementStep).filter(
        RefinementStep.query_id == query_id
    ).all()
    
    if not steps:
        log.warning(f"No refinement steps found for query_id={query_id}")
        return {
            'query_id': query_id,
            'step_count': 0,
            'total_tokens': 0,
            'total_cost_usd': 0.0,
            'avg_duration_seconds': 0.0,
        }
    
    # Collect all metadata
    all_metadata = []
    for step in steps:
        if hasattr(step, 'metadata') and step.metadata:
            all_metadata.append(step.metadata)
    
    if not all_metadata:
        log.info(f"No metadata found for query_id={query_id} steps")
        return {
            'query_id': query_id,
            'step_count': len(steps),
            'metadata_count': 0,
            'total_tokens': 0,
            'total_cost_usd': 0.0,
        }
    
    # Aggregate metrics
    summary = {
        'query_id': query_id,
        'step_count': len(steps),
        'metadata_count': len(all_metadata),
        'total_tokens': sum(m.total_tokens or 0 for m in all_metadata),
        'total_cost_usd': sum(m.estimated_cost_usd or 0.0 for m in all_metadata),
        'avg_duration_seconds': sum(m.llm_duration_seconds or 0.0 for m in all_metadata) / len(all_metadata),
        'status_counts': {},
        'providers_used': list(set(m.llm_provider for m in all_metadata if m.llm_provider)),
        'models_used': list(set(m.llm_model for m in all_metadata if m.llm_model)),
    }
    
    # Count statuses
    for metadata in all_metadata:
        status = metadata.status or 'unknown'
        summary['status_counts'][status] = summary['status_counts'].get(status, 0) + 1
    
    log.info(
        f"Summary for query_id={query_id}: {summary['total_tokens']} tokens, "
        f"${summary['total_cost_usd']:.4f} cost, {summary['metadata_count']} steps"
    )
    
    return summary


# ==========================================
# Session Abandonment / Cleanup
# ==========================================

def abandon_query_session(db: Session, session_id: int, user_id: int) -> Dict[str, Any]:
    """
    Abandon/delete a query session and all its associated data.
    
    This is used when a user clicks "Start Over" to clean up incomplete
    sessions so they don't count toward workflow limits.
    
    Deletes (in order to respect foreign key constraints):
    1. FollowUpHistory entries (linked to RefinementSteps)
    2. RefinementStepMetadata entries
    3. RefinementSteps (linked to Queries)
    4. Feedback (linked to Queries)
    5. Queries (linked to QuerySession)
    6. QuerySession itself
    
    Note: AuditLog and FrontendLog entries are preserved for research purposes
    but marked with session status 'abandoned'.
    
    Args:
        db: Database session
        session_id: ID of the QuerySession to abandon
        user_id: ID of the user (for authorization check)
        
    Returns:
        Dictionary with deletion counts and status
        
    Raises:
        ValueError: If session doesn't exist or doesn't belong to user
    """
    log = get_logger(__name__)
    
    # Verify session exists and belongs to user
    query_session = db.query(QuerySession).filter(
        QuerySession.id == session_id,
        QuerySession.user_id == user_id
    ).first()
    
    if not query_session:
        raise ValueError(f"Session {session_id} not found or doesn't belong to user {user_id}")
    
    log.info(
        f"Abandoning query session",
        extra={
            "session_id": session_id,
            "user_id": user_id,
            "framework": query_session.framework_name,
        }
    )
    
    # Track deletion counts
    deletion_counts = {
        "followups": 0,
        "step_metadata": 0,
        "refinement_steps": 0,
        "feedback": 0,
        "queries": 0,
        "session": 0
    }
    
    # Get all queries for this session
    queries = db.query(Query).filter(Query.session_id == session_id).all()
    query_ids = [q.id for q in queries]
    
    log.info(f"Found {len(queries)} queries to delete for session {session_id}")
    
    if query_ids:
        # Delete FollowUpHistory (linked to RefinementSteps)
        from query_refinement_module.db.models.followup_history import FollowUpHistory
        followups_deleted = db.query(FollowUpHistory).filter(
            FollowUpHistory.refinement_step_id.in_(
                db.query(RefinementStep.id).filter(RefinementStep.query_id.in_(query_ids))
            )
        ).delete(synchronize_session=False)
        deletion_counts["followups"] = followups_deleted
        
        # Delete RefinementStepMetadata
        metadata_deleted = db.query(RefinementStepMetadata).filter(
            RefinementStepMetadata.refinement_step_id.in_(
                db.query(RefinementStep.id).filter(RefinementStep.query_id.in_(query_ids))
            )
        ).delete(synchronize_session=False)
        deletion_counts["step_metadata"] = metadata_deleted
        
        # Delete RefinementSteps
        steps_deleted = db.query(RefinementStep).filter(
            RefinementStep.query_id.in_(query_ids)
        ).delete(synchronize_session=False)
        deletion_counts["refinement_steps"] = steps_deleted
        
        # Delete Feedback
        feedback_deleted = db.query(Feedback).filter(
            Feedback.query_id.in_(query_ids)
        ).delete(synchronize_session=False)
        deletion_counts["feedback"] = feedback_deleted
        
        # Delete Queries
        queries_deleted = db.query(Query).filter(
            Query.id.in_(query_ids)
        ).delete(synchronize_session=False)
        deletion_counts["queries"] = queries_deleted
    
    # Mark session as abandoned and delete
    query_session.status = "abandoned"
    db.delete(query_session)
    deletion_counts["session"] = 1
    
    # Commit all deletions
    db.commit()
    
    log.info(
        f"Abandoned session {session_id}",
        extra={
            "session_id": session_id,
            "user_id": user_id,
            "deletion_counts": deletion_counts,
        }
    )
    
    return {
        "status": "abandoned",
        "session_id": session_id,
        "deletion_counts": deletion_counts
    }
