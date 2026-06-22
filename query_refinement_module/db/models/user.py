"""
User model for query refinement web app.
Follows SQLAlchemy ORM standards.
"""
from sqlalchemy import Column, Integer, String, DateTime, Boolean
from sqlalchemy.orm import declarative_base, relationship
from datetime import datetime, timezone

Base = declarative_base()


def _utcnow():
    """Return current UTC time (timezone-aware)."""
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, autoincrement=True)
    username = Column(String(50), unique=True, nullable=False, index=True)
    email = Column(String(255), unique=True, nullable=True)
    name = Column(String(128), nullable=True)
    password_hash = Column(String(255), nullable=False)
    created_at = Column(DateTime, default=_utcnow)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow)
    
    # Evaluation constraints
    is_superuser = Column(Boolean, default=False, nullable=False)
    has_completed_workflow = Column(Boolean, default=False, nullable=False)
    
    framework_access = relationship(
        "UserFrameworkAccess",
        back_populates="user",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    def __repr__(self):
        return f"<User(id={self.id}, username='{self.username}', superuser={self.is_superuser}')>"
