"""
Unified response schema for refinement analysis.

This module defines the unified response structure used for both initial
and follow-up analysis of refinement aspects.
"""

from pydantic import BaseModel, ConfigDict, Field, validator
from typing import List, Optional, Literal, Dict, Any


class DimensionEvaluationResponse(BaseModel):
    """
    Unified response structure for both initial and follow-up analysis.
    
    This single structure handles:
    - Initial analysis (is aspect clear in original query?)
    - Follow-up analysis (is aspect clear after user's answer?)
    
    The LLM returns this structure for both cases, with only the
    conversation history differing in the input prompt.
    """
    
    is_complete: bool = Field(
        description="Whether this aspect is sufficiently refined and clear"
    )
    
    reasoning: str = Field(
        description="Brief explanation of why the aspect is/isn't complete"
    )
    
    refinement_aspect_value: Optional[str] = Field(
        default=None,
        description="Clean, actionable value extracted or refined (REQUIRED if is_complete=True)"
    )
    
    next_question: Optional[str] = Field(
        default=None,
        description="Focused clarifying question with inline options (REQUIRED if is_complete=False)"
    )
    
    # Metadata for tracking and debugging
    context: Literal['initial', 'followup'] = Field(
        default='initial',
        description="Whether this was initial analysis or follow-up"
    )
    
    round: int = Field(
        default=1,
        ge=1,
        description="Which conversation round (1=initial, 2+=follow-up)"
    )
    
    @validator('refinement_aspect_value')
    def validate_refinement_aspect_value_when_complete(cls, v, values):
        """Ensure refinement_aspect_value is provided when is_complete=True."""
        is_complete = values.get('is_complete', False)
        if is_complete and not v:
            raise ValueError(
                "refinement_aspect_value is required when is_complete=True. "
                "The LLM must extract or synthesize the aspect's value."
            )
        return v
    
    @validator('next_question')
    def validate_next_question_when_incomplete(cls, v, values):
        """Ensure next_question is provided when is_complete=False."""
        is_complete = values.get('is_complete', True)
        if not is_complete and not v:
            raise ValueError(
                "next_question is required when is_complete=False. "
                "The LLM must ask a clarifying question."
            )
        return v
    
    class Config:
        """Pydantic config."""
        frozen = False
        validate_assignment = True


class SearchTerms(BaseModel):
    required: List[str] = Field(default_factory=list)
    optional: List[str] = Field(default_factory=list)
    excluded: List[str] = Field(default_factory=list)

class KeywordSearch(BaseModel):
    structured: str
    phrases: List[str] = Field(default_factory=list)
    terms: SearchTerms

class GreyLiteratureSearch(BaseModel):
    broad_concepts: List[str] = Field(default_factory=list)
    organizational_terms: List[str] = Field(default_factory=list)
    geographic_variants: List[str] = Field(default_factory=list)

class SearchOptimized(BaseModel):
    semantic: str
    keyword: KeywordSearch
    grey_literature: GreyLiteratureSearch

class SearchFilters(BaseModel):
    publication_years: str = ""
    venues: str = ""
    authors: List[str] = Field(default_factory=list)
    publication_types: List[str] = Field(default_factory=list)
    fields_of_study: str = ""

class Terminology(BaseModel):
    primary_terms: List[str] = Field(default_factory=list)
    synonyms: Dict[str, List[str]] = Field(default_factory=dict)
    domain_specific: List[str] = Field(default_factory=list)
    colloquial: List[str] = Field(default_factory=list)


class Metadata(BaseModel):
    temporal: Optional[str] = None     
    geographic: Optional[str] = None    
    source_types: List[str] = Field(default_factory=list)
    other: Dict[str, Any] = Field(default_factory=dict)


class ProcessingLog(BaseModel):
    preserved: List[str] = Field(default_factory=list)
    normalized: List[str] = Field(default_factory=list)
    integrated: List[str] = Field(default_factory=list)
    expanded: List[str] = Field(default_factory=list)


class QueryRefinementResponse(BaseModel):
    model_config = ConfigDict(
        frozen=False,
        validate_assignment=True
    )
    synthesized_statement: str
    detail_values: Dict[str, str]
    search_optimized: SearchOptimized
    search_filters: SearchFilters
    terminology: Terminology
    metadata: Metadata
    processing_log: ProcessingLog
