"""
RefinementStep model for storing each step in the query refinement pipeline.

Stores only the final refined value for each dimension - NOT the full conversation.
Conversation history is kept in-memory during session and discarded after completion.
"""
from sqlalchemy import Column, Integer, Text, DateTime, ForeignKey, Boolean
from sqlalchemy.orm import relationship
from .user import Base, _utcnow


class RefinementStep(Base):
    """
    Represents a single refinement dimension/aspect for a query.
    
    Fields from LLM response (DimensionEvaluationResponse):
    - final_value: Maps to refinement_aspect_value (the extracted/assembled value)
    - is_complete: Whether LLM determined this dimension is sufficiently refined
    
    Evaluation-only fields (NOT from LLM - for tracking user behavior):
    - was_skipped: User used /skip command to bypass this dimension
    - user_ended_early: User used /done before LLM returned is_complete=True
    
    Does NOT store:
    - Individual Q&A exchanges (kept in memory only)
    - LLM reasoning (transient)
    - next_question (transient)
    """
    __tablename__ = "refinement_steps"

    id = Column(Integer, primary_key=True, autoincrement=True)
    query_id = Column(Integer, ForeignKey("queries.id"), nullable=False)
    aspect_name = Column(Text, nullable=False)
    
    # From LLM: refinement_aspect_value - the final refined value
    final_value = Column(Text, nullable=True)
    
    # From LLM: is_complete - whether dimension is sufficiently refined
    is_complete = Column(Boolean, default=False, nullable=False)
    
    # Evaluation-only: User used /skip command
    was_skipped = Column(Boolean, default=False, nullable=False)
    
    # Evaluation-only: User used /done before LLM said is_complete=True
    user_ended_early = Column(Boolean, default=False, nullable=False)
    
    # Timestamp
    created_at = Column(DateTime, default=_utcnow)

    # Relationships
    query = relationship("Query", backref="refinement_steps")
    
    # Keep followup_history relationship for backward compatibility during migration
    # but we won't write to it going forward
    followup_history = relationship("FollowUpHistory", back_populates="refinement_step", cascade="all, delete-orphan")

    def __repr__(self):
        status = "complete" if self.is_complete else ("skipped" if self.was_skipped else "pending")
        return f"<RefinementStep(id={self.id}, aspect='{self.aspect_name}', status={status})>"
