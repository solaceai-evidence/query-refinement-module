"""
Feedback model for collecting user feedback on queries and results.
"""
from sqlalchemy import Column, Integer, Text, DateTime, ForeignKey
from sqlalchemy.orm import relationship
import datetime
from .user import Base

class Feedback(Base):
    __tablename__ = "feedback"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    query_id = Column(Integer, ForeignKey("queries.id"), nullable=True)
    rating = Column(Integer, nullable=True)
    comments = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    user = relationship("User", backref="feedback")
    query = relationship("Query", backref="feedback")

    def __repr__(self):
        return f"<Feedback(id={self.id}, user_id={self.user_id}, query_id={self.query_id})>"
