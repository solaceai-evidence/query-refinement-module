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
        description="The accumulated value of this dimension using the user's exact words. Non-empty whenever any value has been extracted, regardless of completion state. Empty string only when no information for this dimension exists across all sources."
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

# ===============================================================
# Synthesis Response Models
# ===============================================================

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
    grey_literature: Optional[GreyLiteratureSearch] = None

class SearchFilters(BaseModel):
    """Metadata filters for search refinement."""
    publication_years: str = Field(default="")
    venues: List[str] = Field(default_factory=list)
    authors: List[str] = Field(default_factory=list)
    publication_types: List[str] = Field(default_factory=list)
    fields_of_study: List[str] = Field(default_factory=list)

class Terminology(BaseModel):
    """Terminology mapping and variants."""
    primary_terms: Optional[List[str]] = None
    synonyms: Dict[str, List[str]] = Field(default_factory=dict)
    domain_specific: Optional[List[str]] = None
    colloquial: List[str] = Field(default_factory=list)


class StatementResponse(BaseModel):
    """Structured output for the statement synthesis call."""
    integrated_statement: str = Field(
        description="Integrated research specification preserving accepted constraints"
    )


class SemanticQueryResponse(BaseModel):
    """Structured output for the semantic retrieval phrasing call."""
    semantic: str = Field(
        description="Natural language retrieval query for semantic or embedding search"
    )


class TerminologyResponse(BaseModel):
    """Structured output for the terminology expansion call."""
    synonyms: Dict[str, List[str]] = Field(default_factory=dict)


class KeywordSupportResponse(BaseModel):
    """Structured output for keyword-support generation."""
    phrases: List[str] = Field(default_factory=list)
    required: List[str] = Field(default_factory=list)
    optional: List[str] = Field(default_factory=list)
    excluded: List[str] = Field(default_factory=list)


class FilterSuggestionResponse(BaseModel):
    """Structured output for constrained filter suggestions."""
    publication_years: str = Field(default="", description="Year range in YYYY-YYYY or YYYY- format, empty if not stated")
    venues: List[str] = Field(default_factory=list, description="Journal or conference names, empty if not stated")
    authors: List[str] = Field(default_factory=list, description="Author names, empty if not stated")
    publication_types: List[str] = Field(default_factory=list, description="Publication types e.g. randomised controlled trial, systematic review")
    fields_of_study: List[str] = Field(default_factory=list)





class QueryRefinementResponse(BaseModel):
    """
    Complete synthesis output integrating all refined dimensions.
    
    Provides:
    - Integrated research statement
    - Individual dimension specifications
    - Search-optimized variants
    - Filters and terminology
    - Optional metadata and processing logs
    
    Uses LLM template field names as canonical:
    - integrated_statement (not synthesized_statement)
    - dimensions_specifications (not refined_dimensions)
    """
    model_config = ConfigDict(
        frozen=False,
        validate_assignment=True,
        populate_by_name=True  # Allow both names for backward compatibility
    )
    integrated_statement: str = Field(
        description="Integrated research specification preserving user's voice",
        alias="synthesized_statement"  # Database column name (for backward compatibility)
    )
    dimensions_specifications: Dict[str, Optional[str]] = Field(
        description="Normalized value for each dimension (dimension_id -> value)",
        alias="refined_dimensions"  # Database column name (for backward compatibility)
    )
    search_optimized: SearchOptimized
    search_filters: SearchFilters
    terminology: Terminology
    metadata: Optional[Dict[str, Any]] = None
    processing_log: Optional[Dict[str, Any]] = None


# Backward compatibility alias

__all__ = [
    "DimensionEvaluationResponse",
    "QueryRefinementResponse",  # Alias for backward compatibility
    "SearchOptimized",
    "SearchFilters",
    "Terminology",
    "StatementResponse",
    "SemanticQueryResponse",
    "TerminologyResponse",
    "KeywordSupportResponse",
    "FilterSuggestionResponse",
]