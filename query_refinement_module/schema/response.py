"""
Unified response schema for refinement analysis.

This module defines the unified response structure used for both initial
and follow-up analysis of refinement aspects.
"""

from pydantic import BaseModel, ConfigDict, Field, field_validator, validator
from typing import List, Optional, Literal, Dict, Any


# ============================================================================
# Dimension Evaluation Response
# ============================================================================

class DimensionEvaluationResponse(BaseModel):
    """
    Unified response structure for dimension evaluation.
    
    Used for both:
    - Initial analysis (is dimension clear in original input?)
    - Follow-up analysis (is dimension clear after user's answer?)
    """
    
    is_complete: bool = Field(
        description="Whether this dimension is sufficiently refined and clear"
    )
    
    reasoning: str = Field(
        description="Brief explanation of why the dimension is/isn't complete"
    )
    
    aspect_value: Optional[str] = Field(
        default=None,
        description="Assembled value using user's exact words (REQUIRED if is_complete=True)"
    )
    
    next_question: Optional[str] = Field(
        default=None,
        description="Focused question with 2-4 inline examples (REQUIRED if is_complete=False)"
    )
    
    # Metadata for tracking
    context: Literal['initial', 'followup'] = Field(
        default='initial',
        description="Whether this was initial analysis or follow-up"
    )
    
    round: int = Field(
        default=1,
        ge=1,
        description="Conversation round (1=initial, 2+=follow-up)"
    )
    
    model_config = ConfigDict(
        frozen=False,
        validate_assignment=True
    )
    
    @field_validator('aspect_value')
    @classmethod
    def validate_value_when_complete(cls, v, info):
        """Ensure aspect_value provided when is_complete=True."""
        data = info.data
        is_complete = data.get('is_complete', False)
        if is_complete and not v:
            raise ValueError(
                "aspect_value is required when is_complete=True. "
                "Must extract or assemble the dimension's value."
            )
        return v
    
    @field_validator('next_question')
    @classmethod
    def validate_question_when_incomplete(cls, v, info):
        """Ensure next_question provided when is_complete=False."""
        data = info.data
        is_complete = data.get('is_complete', True)
        if not is_complete and not v:
            raise ValueError(
                "next_question is required when is_complete=False. "
                "Must ask a clarifying question."
            )
        return v

# ============================================================================
# Synthesis Response Models
# ============================================================================

class SearchTerms(BaseModel):
    """Search terms categorized by requirement level."""
    required: List[str] = Field(default_factory=list)
    optional: List[str] = Field(default_factory=list)
    excluded: List[str] = Field(default_factory=list)


class KeywordSearch(BaseModel):
    """Keyword search optimization."""
    structured: str = Field(description="Boolean query with operators")
    phrases: List[str] = Field(default_factory=list, description="Exact phrases")
    terms: SearchTerms


class GreyLiteratureSearch(BaseModel):
    """Grey literature search optimization."""
    broad_concepts: List[str] = Field(default_factory=list)
    organizational_terms: List[str] = Field(default_factory=list)
    geographic_variants: List[str] = Field(default_factory=list)


class SearchOptimized(BaseModel):
    """Search variants optimized for different retrieval strategies."""
    semantic: str = Field(description="Natural language semantic search query")
    keyword: KeywordSearch
    grey_literature: GreyLiteratureSearch

class SearchFilters(BaseModel):
    """Metadata filters for search refinement."""
    publication_years: str = Field(default="")
    venues: str = Field(default="")
    authors: List[str] = Field(default_factory=list)
    publication_types: List[str] = Field(default_factory=list)
    fields_of_study: str = Field(default="")

class Terminology(BaseModel):
    """Terminology mapping and variants."""
    primary_terms: List[str] = Field(default_factory=list)
    synonyms: Dict[str, List[str]] = Field(default_factory=dict)
    domain_specific: List[str] = Field(default_factory=list)
    colloquial: List[str] = Field(default_factory=list)


class Metadata(BaseModel):
    """Additional contextual metadata."""
    temporal: Optional[str] = None
    geographic: Optional[str] = None
    source_types: List[str] = Field(default_factory=list)
    other: Dict[str, Any] = Field(default_factory=dict)


class ProcessingLog(BaseModel):
    """Log of transformations applied during synthesis."""
    preserved: List[str] = Field(default_factory=list, description="What was kept from original")
    normalized: List[str] = Field(default_factory=list, description="What was standardized")
    integrated: List[str] = Field(default_factory=list, description="How details were combined")
    expanded: List[str] = Field(default_factory=list, description="What was enriched")


class QueryRefinementResponse(BaseModel):
    """
    Complete synthesis output integrating all refined dimensions.
    
    Provides:
    - Synthesized research statement
    - Individual dimension values
    - Search-optimized variants
    - Metadata and filters
    - Processing documentation
    """
    model_config = ConfigDict(
        frozen=False,
        validate_assignment=True
    )
    synthesized_statement: str =  Field(
        description="Integrated research specification preserving user's voice"
    )
    refined_dimensions: Dict[str, str] = Field(
        description="Normalized value for each dimension (dimension_id -> value)"
    )
    search_optimized: SearchOptimized
    search_filters: SearchFilters
    terminology: Terminology
    metadata: Metadata
    processing_log: ProcessingLog


# Backward compatibility alias
QueryRefinementResponse = QueryRefinementResponse

__all__ = [
    "DimensionEvaluationResponse",
    "QueryRefinementResponse",
    "QueryRefinementResponse",  # Alias for backward compatibility
    "SearchOptimized",
    "SearchFilters",
    "Terminology",
    "Metadata",
    "ProcessingLog",
]