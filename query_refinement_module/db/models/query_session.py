"""
QuerySession model for tracking user sessions.
"""
from sqlalchemy import Column, Integer, String, DateTime, ForeignKey
from sqlalchemy.orm import relationship
import datetime
from .user import Base

class QuerySession(Base):
    __tablename__ = "query_sessions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    started_at = Column(DateTime, default=datetime.datetime.utcnow)
    ended_at = Column(DateTime, nullable=True)
    status = Column(String(32), default="active")
    framework_name = Column(String(128), nullable=True)

    user = relationship("User", backref="sessions")

    def __repr__(self):
        return f"<QuerySession(id={self.id}, user_id={self.user_id})>"
