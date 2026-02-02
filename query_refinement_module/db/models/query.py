"""
Query model for storing user queries in a session.

Stores the original query and, upon completion, the full QueryRefinementResponse
for evaluation purposes (synthesized statement, search variants, terminology, etc.).
"""
from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey, JSON, Boolean
from sqlalchemy.orm import relationship
from .user import Base, _utcnow


class Query(Base):
    """
    Stores queries and their final refinement output.
    
    Core fields:
    - original_query: User's initial input
    - refined_query: Legacy field (deprecated, use synthesized_statement)
    
    Final Response Fields (QueryRefinementResponse):
    - synthesized_statement: Integrated research specification
    - refined_dimensions: Dict of dimension_id -> final value
    - search_optimized: Search variants (semantic, keyword, grey_literature)
    - search_filters: Publication years, venues, authors, etc.
    - terminology: Primary terms, synonyms, domain-specific terms
    - response_metadata: Temporal, geographic, source types
    - processing_log: Preserved, normalized, integrated, expanded
    """
    __tablename__ = "queries"

    id = Column(Integer, primary_key=True, autoincrement=True)
    session_id = Column(Integer, ForeignKey("query_sessions.id"), nullable=False)
    original_query = Column(Text, nullable=False)
    refined_query = Column(Text, nullable=True)  # Deprecated - use synthesized_statement
    created_at = Column(DateTime, default=_utcnow)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow)
    completed_at = Column(DateTime, nullable=True)  # When refinement finished
    
    # Data consent (only persist if user submits feedback)
    consent_given = Column(Boolean, default=False, nullable=False)
    consent_given_at = Column(DateTime, nullable=True)
    
    # =========================================================================
    # Final Response Fields (QueryRefinementResponse Pydantic model)
    # Stored as JSON for evaluation purposes
    # =========================================================================
    
    # Synthesized research statement preserving user's voice
    synthesized_statement = Column(Text, nullable=True)
    
    # Normalized value for each dimension {dimension_id: value}
    refined_dimensions = Column(JSON, nullable=True)
    
    # Search optimization variants (semantic, keyword, grey_literature)
    search_optimized = Column(JSON, nullable=True)
    
    # Metadata filters (publication_years, venues, authors, etc.)
    search_filters = Column(JSON, nullable=True)
    
    # Terminology mapping (primary_terms, synonyms, domain_specific, colloquial)
    terminology = Column(JSON, nullable=True)
    
    # Additional context (temporal, geographic, source_types, other)
    response_metadata = Column(JSON, nullable=True)
    
    # Processing log (preserved, normalized, integrated, expanded)
    processing_log = Column(JSON, nullable=True)

    session = relationship("QuerySession", backref="queries")

    def __repr__(self):
        return f"<Query(id={self.id}, session_id={self.session_id})>"
