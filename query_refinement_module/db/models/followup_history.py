"""
FollowUpHistory model for storing follow-up questions and answers for each refinement step.
"""
from sqlalchemy import Column, Integer, Text, DateTime, ForeignKey
from sqlalchemy.orm import relationship
import datetime
from .user import Base

class FollowUpHistory(Base):
    __tablename__ = "followup_history"

    id = Column(Integer, primary_key=True, autoincrement=True)
    refinement_step_id = Column(Integer, ForeignKey("refinement_steps.id"), nullable=False)
    question = Column(Text, nullable=False)
    answer = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    refinement_step = relationship("RefinementStep", backref="followup_history")

    def __repr__(self):
        return f"<FollowUpHistory(id={self.id}, refinement_step_id={self.refinement_step_id})>"
