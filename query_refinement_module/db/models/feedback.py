"""query_refinement_module.db.models.feedback

Feedback model for collecting user feedback on queries and results.

Supports both:
- free-text comments (qualitative research feedback)
- optional structured metadata (quantitative/structured survey responses)
"""

from sqlalchemy import Column, Integer, Text, DateTime, ForeignKey, JSON
from sqlalchemy.orm import relationship
from .user import Base, _utcnow


class Feedback(Base):
    __tablename__ = "feedback"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    query_id = Column(Integer, ForeignKey("queries.id"), nullable=True)
    rating = Column(Integer, nullable=True)
    comments = Column(Text, nullable=True)
    additional_metadata = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=_utcnow)

    user = relationship("User", backref="feedback")
    query = relationship("Query", backref="feedback")

    def __repr__(self):
        return f"<Feedback(id={self.id}, user_id={self.user_id}, query_id={self.query_id})>"
