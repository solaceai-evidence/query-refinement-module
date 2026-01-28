"""
Query model for storing user queries in a session.
"""
from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from .user import Base, _utcnow


class Query(Base):
    __tablename__ = "queries"

    id = Column(Integer, primary_key=True, autoincrement=True)
    session_id = Column(Integer, ForeignKey("query_sessions.id"), nullable=False)
    original_query = Column(Text, nullable=False)
    refined_query = Column(Text, nullable=True)
    created_at = Column(DateTime, default=_utcnow)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow)

    session = relationship("QuerySession", backref="queries")

    def __repr__(self):
        return f"<Query(id={self.id}, session_id={self.session_id})>"
