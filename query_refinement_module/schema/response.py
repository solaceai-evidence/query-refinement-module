"""
Unified response schema for refinement analysis.

This module defines the unified response structure used for both initial
and follow-up analysis of refinement aspects.
"""

from enum import Enum

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
        description="Focused clarifying question — plain prose, no embedded examples (REQUIRED if complete=False, empty string otherwise)"
    )

    examples: List[str] = Field(
        default_factory=list,
        description="2-4 concrete quick-reply options that span the clarification space. Each string is a standalone answer the user can select as-is. Empty list when complete=True."
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


class CombinedBlock(BaseModel):
    """One AND-block with free-text terms and controlled vocabulary merged, for source connectors."""
    role: str = Field(description="query_role of the dominant concept in this block")
    free_text: List[str] = Field(default_factory=list, description="OR-group terms: true_synonyms + abbreviations + spelling_variants + lexical_variants")
    controlled_vocabulary: Dict[str, List[str]] = Field(
        default_factory=dict,
        description="vocabulary_name → deduplicated terms from controlled_vocabulary_hints of all concepts in this block",
    )


class KeywordSearch(BaseModel):
    """Keyword search optimization."""
    structured: str = Field(description="Boolean query with operators")
    phrases: List[str] = Field(default_factory=list, description="Exact phrases")
    terms: SearchTerms
    combined_blocks: Optional[List[CombinedBlock]] = Field(
        default=None,
        description="Structured blocks for source-specific query construction; mirrors AND-blocks in keyword.structured",
    )


class SearchOptimized(BaseModel):
    """Search variants optimized for different retrieval strategies."""
    semantic: str = Field(description="Natural language semantic search query")
    keyword: KeywordSearch

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


# ============================================================================
# Search Expansion: fixed aspect ontology, policy, and models
# ============================================================================

class SearchAspect(str, Enum):
    """Fixed internal ontology of search-expansion aspect classes.

    This ontology is internal to the search expansion stage and is the only authoritative set of axes along which a query may be broadened. It is not derived from framework dimensions.
    """
    TOPIC_OR_CONDITION = "topic_or_condition"
    POPULATION_OR_ENTITY = "population_or_entity"
    INTERVENTION_OR_EXPOSURE_OR_PHENOMENON = "intervention_or_exposure_or_phenomenon"
    SETTING_OR_CONTEXT = "setting_or_context"
    GEOGRAPHY = "geography"
    TIME_SCOPE = "time_scope"


class AspectSafety(str, Enum):
    """Deterministic safety classification for broadening a given aspect."""
    SAFE = "safe"
    CONDITIONAL = "conditional"
    AVOID = "avoid"


#: Evidence-backed default safety policy aligned with Cochrane/Campbell/JBI standards.
#:
#: CONDITIONAL aspects change the research question scope when broadened and must
#: only be used at Level 3 with explicit rationale:
#:   - TOPIC_OR_CONDITION: the condition defines what is being reviewed; broadening
#:     it (e.g. "VTE" → "thrombosis") crosses into a different research question.
#:   - INTERVENTION_OR_EXPOSURE_OR_PHENOMENON: broadening risks scope drift into
#:     different mechanisms or exposure classes.
#:
#: SAFE aspects are search-strategy constraints that do not define the research
#: question and can be relaxed for recall without changing review scope:
#:   - POPULATION_OR_ENTITY: widening to a broader but still coherent population class.
#:   - SETTING_OR_CONTEXT: removing a setting restriction to capture analogous contexts.
#:   - GEOGRAPHY: geographic restrictions are search artifacts; broaden or remove first.
#:     Includes contextual analogy (replacing a location with its context characteristic).
#:   - TIME_SCOPE: widening an existing date range only; never adding a new restriction.
#:
#: Comparators, outcomes, and methodological constraints are outside the ontology.
DEFAULT_ASPECT_SAFETY: Dict["SearchAspect", "AspectSafety"] = {
    SearchAspect.TOPIC_OR_CONDITION: AspectSafety.CONDITIONAL,
    SearchAspect.POPULATION_OR_ENTITY: AspectSafety.SAFE,
    SearchAspect.INTERVENTION_OR_EXPOSURE_OR_PHENOMENON: AspectSafety.CONDITIONAL,
    SearchAspect.SETTING_OR_CONTEXT: AspectSafety.SAFE,
    SearchAspect.GEOGRAPHY: AspectSafety.SAFE,
    SearchAspect.TIME_SCOPE: AspectSafety.SAFE,
}


class ExpansionStrategy(str, Enum):
    """Methodological strategy type of one expansion level."""
    ANCHOR = "anchor"
    LEXICAL = "lexical"
    CONCEPTUAL_SINGLE_ASPECT = "conceptual_single_aspect"
    CONCEPTUAL_MULTI_ASPECT = "conceptual_multi_aspect"


class SearchAspectAssessment(BaseModel):
    """Assessment of one fixed aspect against the anchor query.

    ``safety`` is assigned deterministically by the policy layer after the
    LLM detection call; the LLM never controls safety classification.
    """
    aspect: SearchAspect
    detected: bool = False
    detected_value: str = ""
    broadening_candidates: List[str] = Field(default_factory=list)
    reasoning: str = ""
    safety: Optional[AspectSafety] = None

    @field_validator("detected_value")
    @classmethod
    def validate_detected_value(cls, v: str, info) -> str:
        if info.data.get("detected") and not (v or "").strip():
            raise ValueError("detected_value is required when detected=True")
        return (v or "").strip()


class SearchAspectAssessmentResponse(BaseModel):
    """LLM response for the aspect-detection call."""
    assessments: List[SearchAspectAssessment] = Field(default_factory=list)


class SearchExpansionLevel(BaseModel):
    """One retrieval broadening level. Level 0 is the deterministic anchor."""
    level: int
    label: str
    strategy: ExpansionStrategy = ExpansionStrategy.CONCEPTUAL_SINGLE_ASPECT
    search_query: str
    relaxed_aspects: Dict[str, str] = Field(
        default_factory=dict,
        description="Fixed aspect id -> search-only broadened value",
    )
    rationale: str

    @field_validator("label", "search_query", "rationale")
    @classmethod
    def validate_non_empty_text(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("field must be non-empty")
        return v.strip()


class SearchExpansionResponse(BaseModel):
    """LLM response containing only generated Levels 1-N."""
    levels: List[SearchExpansionLevel] = Field(default_factory=list)

    @field_validator("levels")
    @classmethod
    def validate_llm_levels_start_at_one(cls, v: List[SearchExpansionLevel]) -> List[SearchExpansionLevel]:
        bad = [level.level for level in v if level.level < 1]
        if bad:
            raise ValueError(f"LLM-generated expansion levels must be >= 1: {bad}")
        return v


class SearchExpansionContext(BaseModel):
    """Optional retrieval context that can inform search broadening."""
    filters: Dict[str, Any] = Field(default_factory=dict)
    synonyms: Dict[str, List[str]] = Field(default_factory=dict)
    concept_graph: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Structured concept graph from Agent B; when present, takes precedence over synonyms for lexical context.",
    )


class SearchExpansionInput(BaseModel):
    """Standalone input contract for the fixed-core search expansion stage."""
    statement: str = Field(description="Exact Level 0 query preserved as the retrieval anchor")
    search_context: Optional[SearchExpansionContext] = None
    dimensions_specifications: Dict[str, Any] = Field(
        default_factory=dict,
        description="Refined dimension values for context (e.g., population, intervention)"
    )

    @field_validator("statement")
    @classmethod
    def validate_statement(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("statement must be non-empty")
        return v.strip()


class SearchAspectAssessmentSummary(BaseModel):
    """Transparent assessment metadata exposed alongside expansion levels."""
    assessed_aspects: List[SearchAspectAssessment] = Field(default_factory=list)
    safe_aspects: List[SearchAspect] = Field(default_factory=list)
    conditional_aspects: List[SearchAspect] = Field(default_factory=list)
    avoided_aspects: List[SearchAspect] = Field(default_factory=list)





class QueryRefinementResponse(BaseModel):
    """
    Complete synthesis output integrating all refined dimensions.

    Provides:
    - Clarified statement
    - Individual dimension specifications
    - Search-optimized variants
    - Filters and terminology
    - Optional metadata and processing logs

    Uses LLM template field names as canonical:
    - clarified_query (not synthesized_statement)
    - dimensions_specifications (not refined_dimensions)
    """
    model_config = ConfigDict(
        frozen=False,
        validate_assignment=True
    )
    clarified_query: str = Field(
        description="Clarified statement preserving user's voice",
    )
    dimensions_specifications: Dict[str, Any] = Field(
        description="Normalized value for each dimension (dimension_id -> value)",
    )
    search_optimized: SearchOptimized
    search_filters: SearchFilters
    terminology: Terminology
    metadata: Optional[Dict[str, Any]] = None
    processing_log: Optional[Dict[str, Any]] = None


# ============================================================================
# Multi-agent synthesis pipeline models (Agents A, B, C)
# ============================================================================

class VocabularyHint(BaseModel):
    """One controlled vocabulary entry inferred by Agent B for a concept."""
    vocabulary_name: str = Field(description="e.g. 'MeSH', 'PsycINFO Thesaurus', 'ERIC Thesaurus', 'ACM CCS'")
    terms: List[str] = Field(default_factory=list)
    confidence: str = Field(default="medium", description="'high' | 'medium' | 'low'")


class ConceptEntry(BaseModel):
    """Structured retrieval representation of one canonical concept (Agent B output)."""
    query_role: Optional[str] = Field(
        default=None,
        description="SearchAspect value, 'comparator', 'outcome', 'other', or null",
    )
    true_synonyms: List[str] = Field(default_factory=list)
    abbreviations: List[str] = Field(default_factory=list)
    spelling_variants: List[str] = Field(default_factory=list)
    lexical_variants: List[str] = Field(default_factory=list)
    domain_terms: List[str] = Field(default_factory=list)
    colloquial: List[str] = Field(default_factory=list)
    controlled_vocabulary_hints: List[VocabularyHint] = Field(default_factory=list)


class ResearchStatementResponse(BaseModel):
    """Agent A output: clarified statement + dimension passthrough."""
    clarified_query: str
    dimensions_specifications: Dict[str, Any] = Field(default_factory=dict)


class SemanticRepresentationResponse(BaseModel):
    """Agent B output: embedding query + keyword query + structured concept graph."""
    semantic_statement: str
    keyword_statement: str
    concept_graph: Dict[str, ConceptEntry] = Field(default_factory=dict)


class SearchConstructionResponse(BaseModel):
    """Agent C output: anchor keyword search + filters."""
    keyword: KeywordSearch
    search_filters: SearchFilters


# Backward compatibility alias

__all__ = [
    "DimensionEvaluationResponse",
    "QueryRefinementResponse",
    "SearchOptimized",
    "SearchFilters",
    "Terminology",
    "SearchAspect",
    "AspectSafety",
    "DEFAULT_ASPECT_SAFETY",
    "ExpansionStrategy",
    "SearchAspectAssessment",
    "SearchAspectAssessmentResponse",
    "SearchAspectAssessmentSummary",
    "SearchExpansionLevel",
    "SearchExpansionResponse",
    "SearchExpansionContext",
    "SearchExpansionInput",
    "CombinedBlock",
    "VocabularyHint",
    "ConceptEntry",
    "ResearchStatementResponse",
    "SemanticRepresentationResponse",
    "SearchConstructionResponse",
]