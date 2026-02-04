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
    
    complete: bool = Field(
        description="Whether this dimension is sufficiently refined and clear"
    )
    
    current: str = Field(
        default="",
        description="Assembled value using user's exact words (REQUIRED if complete=True, empty string otherwise)"
    )
    
    question: str = Field(
        default="",
        description="Focused question with 2-4 inline examples (REQUIRED if complete=False, empty string otherwise)"
    )
    
    model_config = ConfigDict(
        frozen=False,
        validate_assignment=True
    )
    
    @field_validator('current')
    @classmethod
    def validate_value_when_complete(cls, v, info):
        """Ensure current provided when complete=True."""
        data = info.data
        complete = data.get('complete', False)
        if complete and not v:
            raise ValueError(
                "current is required when complete=True. "
                "Must extract or assemble the dimension's value."
            )
        return v
    
    @field_validator('question')
    @classmethod
    def validate_question_when_incomplete(cls, v, info):
        """Ensure question provided when complete=False."""
        data = info.data
        complete = data.get('complete', True)
        if not complete and not v:
            raise ValueError(
                "question is required when complete=False. "
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
    venues: List[str] = Field(default_factory=list)
    authors: List[str] = Field(default_factory=list)
    publication_types: List[str] = Field(default_factory=list)
    fields_of_study: List[str] = Field(default_factory=list)

class Terminology(BaseModel):
    """Terminology mapping and variants."""
    primary_terms: List[str] = Field(default_factory=list)
    synonyms: Dict[str, List[str]] = Field(default_factory=dict)
    domain_specific: List[str] = Field(default_factory=list)
    colloquial: List[str] = Field(default_factory=list)





class QueryRefinementResponse(BaseModel):
    """
    Complete synthesis output integrating all refined dimensions.
    
    Provides:
    - Synthesized research statement
    - Individual dimension values
    - Search-optimized variants
    - Filters and terminology
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


# Backward compatibility alias
QueryRefinementResponse = QueryRefinementResponse

__all__ = [
    "DimensionEvaluationResponse",
    "QueryRefinementResponse",
    "QueryRefinementResponse",  # Alias for backward compatibility
    "SearchOptimized",
    "SearchFilters",
    "Terminology",
]