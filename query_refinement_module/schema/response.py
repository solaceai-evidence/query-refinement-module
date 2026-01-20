"""
Unified response schema for refinement analysis.

This module defines the unified response structure used for both initial
and follow-up analysis of refinement aspects.
"""

from pydantic import BaseModel, Field, validator
from typing import Optional, Literal


class RefinementAnalysisResponse(BaseModel):
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


class SynthesisResponse(BaseModel):
    """
    Structured response from query synthesis.
    
    This model ensures synthesis output includes both the refined query
    and traceability metadata mapping back to individual aspect refinements.
    """
    
    refined_query: str = Field(
        ...,
        description="The final synthesized query combining all refinements"
    )
    
    refinement_aspects: dict = Field(
        ...,
        description="Map of aspect_id → refinement_aspect_value for traceability"
    )
    
    key_changes: list = Field(
        default_factory=list,
        description="List of key changes from original query"
    )
    
    # Metadata extraction fields (optional)
    publication_years: str = Field(
        default="",
        description="Temporal constraints extracted from query (e.g., '2020-2025')"
    )
    
    venues: str = Field(
        default="",
        description="Comma-separated venue names"
    )
    
    authors: list = Field(
        default_factory=list,
        description="List of author names mentioned"
    )
    
    fields_of_study: str = Field(
        default="",
        description="Comma-separated research fields"
    )
    
    refined_statement: str = Field(
        default="",
        description="Alternative natural-language statement for semantic search"
    )
    
    refined_statement_keywords: str = Field(
        default="",
        description="Keyword-optimized version"
    )
    
    @validator('refinement_aspects')
    def validate_refinement_aspects(cls, v):
        """Ensure refinement_aspects is a dict."""
        if not isinstance(v, dict):
            raise ValueError("refinement_aspects must be a dictionary")
        return v
    
    class Config:
        """Pydantic config."""
        frozen = False
        validate_assignment = True
