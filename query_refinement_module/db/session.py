"""
Database session management utilities.
"""
from contextlib import contextmanager
from sqlalchemy.orm import Session
from query_refinement_module.db.database import SessionLocal


@contextmanager
def get_db_session():
    """
    Context manager for database sessions.
    
    Usage:
        with get_db_session() as db:
            user = create_user(db, email="test@example.com", name="Test", password="password")
    """
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def get_db():
    """
    Dependency function for FastAPI or similar frameworks.
    
    Usage (FastAPI):
        @app.get("/users/{user_id}")
        def read_user(user_id: int, db: Session = Depends(get_db)):
            return get_user_by_id(db, user_id)
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
