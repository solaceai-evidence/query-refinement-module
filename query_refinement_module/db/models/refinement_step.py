"""
RefinementStep model for storing each step in the query refinement pipeline.
"""
from sqlalchemy import Column, Integer, Text, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from .user import Base, _utcnow


class RefinementStep(Base):
    __tablename__ = "refinement_steps"

    id = Column(Integer, primary_key=True, autoincrement=True)
    query_id = Column(Integer, ForeignKey("queries.id"), nullable=False)
    aspect_name = Column(Text, nullable=False)
    created_at = Column(DateTime, default=_utcnow)

    query = relationship("Query", backref="refinement_steps")
    followup_history = relationship("FollowUpHistory", back_populates="refinement_step", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<RefinementStep(id={self.id}, query_id={self.query_id}, aspect='{self.aspect_name}')>"
