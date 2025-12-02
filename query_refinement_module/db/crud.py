"""
CRUD utility functions for database operations.
"""
from sqlalchemy.orm import Session
from typing import Optional, List
from query_refinement_module.db.models.user import User
from query_refinement_module.db.models.query_session import QuerySession
from query_refinement_module.db.models.query import Query
from query_refinement_module.db.models.refinement_step import RefinementStep
from query_refinement_module.db.models.followup_history import FollowUpHistory
from query_refinement_module.db.models.feedback import Feedback
from passlib.context import CryptContext

# Password hashing context
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


# ==========================================
# User CRUD Operations
# ==========================================

def create_user(db: Session, email: str, name: str, password: str) -> User:
    """Create a new user with hashed password."""
    # Truncate password to 72 characters for bcrypt compatibility
    truncated_password = password[:72]
    password_hash = pwd_context.hash(truncated_password)
    user = User(email=email, name=name, password_hash=password_hash)
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def get_user_by_email(db: Session, email: str) -> Optional[User]:
    """Retrieve a user by email."""
    return db.query(User).filter(User.email == email).first()


def get_user_by_id(db: Session, user_id: int) -> Optional[User]:
    """Retrieve a user by ID."""
    return db.query(User).filter(User.id == user_id).first()


def verify_user_password(db: Session, email: str, password: str) -> Optional[User]:
    """Verify user credentials and return user if valid."""
    user = get_user_by_email(db, email)
    if user:
        # Truncate password to 72 characters for bcrypt compatibility
        truncated_password = password[:72]
        if pwd_context.verify(truncated_password, user.password_hash):
            return user
    return None


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
        from datetime import datetime
        session.ended_at = datetime.utcnow()
        session.status = "completed"
        db.commit()
        db.refresh(session)
    return session


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


# ==========================================
# RefinementStep CRUD Operations
# ==========================================

def create_refinement_step(db: Session, query_id: int, aspect_name: str) -> RefinementStep:
    """Create a new refinement step for a query."""
    step = RefinementStep(query_id=query_id, aspect_name=aspect_name)
    db.add(step)
    db.commit()
    db.refresh(step)
    return step


def get_refinement_step(db: Session, step_id: int) -> Optional[RefinementStep]:
    """Retrieve a refinement step by ID."""
    return db.query(RefinementStep).filter(RefinementStep.id == step_id).first()


def get_query_refinement_steps(db: Session, query_id: int) -> List[RefinementStep]:
    """Retrieve all refinement steps for a query."""
    return db.query(RefinementStep).filter(RefinementStep.query_id == query_id).all()


# ==========================================
# FollowUpHistory CRUD Operations
# ==========================================

def create_followup(
    db: Session, refinement_step_id: int, question: str, answer: Optional[str] = None
) -> FollowUpHistory:
    """Create a new follow-up history entry."""
    followup = FollowUpHistory(
        refinement_step_id=refinement_step_id, question=question, answer=answer
    )
    db.add(followup)
    db.commit()
    db.refresh(followup)
    return followup


def update_followup_answer(db: Session, followup_id: int, answer: str) -> Optional[FollowUpHistory]:
    """Update the answer for a follow-up question."""
    followup = db.query(FollowUpHistory).filter(FollowUpHistory.id == followup_id).first()
    if followup:
        followup.answer = answer
        db.commit()
        db.refresh(followup)
    return followup


def get_step_followups(db: Session, refinement_step_id: int) -> List[FollowUpHistory]:
    """Retrieve all follow-up history for a refinement step."""
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
) -> Feedback:
    """Create a new feedback entry."""
    feedback = Feedback(
        user_id=user_id, query_id=query_id, rating=rating, comments=comments
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
