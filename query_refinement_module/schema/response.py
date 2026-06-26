"""
Unified response schema for refinement analysis.

This module defines the unified response structure used for both initial
and follow-up analysis of refinement aspects.
"""

import json as _json
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator, validator
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
# Search Expansion: context model for optional concept graph passthrough
# ============================================================================

class SearchExpansionContext(BaseModel):
    """Optional retrieval context that can inform search broadening."""
    filters: Dict[str, Any] = Field(default_factory=dict)
    synonyms: Dict[str, List[str]] = Field(default_factory=dict)
    concept_graph: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Structured concept graph from Agent B; when present, takes precedence over synonyms for lexical context.",
    )


# ============================================================================
# Search Expansion: block-aware, Cochrane-compliant, deterministic Level 1
# ============================================================================

class SearchExpansionInput(BaseModel):
    """Input to Agent D — all Agent A/B/C output needed to build a complete unified response."""
    clarified_query: str = Field(description="NL anchor from Agent A (clarified_query)")
    anchor_blocks: List[CombinedBlock] = Field(
        default_factory=list,
        description="Agent C's combined_blocks — one AND-block per query role",
    )
    concept_graph: Dict[str, Any] = Field(
        default_factory=dict,
        description="Agent B's concept graph — used to enrich blocks with domain_terms",
    )
    # Agent B passthrough — used to populate Level 0
    semantic_statement: str = Field(
        default="",
        description="Agent B's dense embedding query — used as Level 0 semantic_statement",
    )
    keyword_statement: str = Field(
        default="",
        description="Agent B's compact NL keyword query — used as Level 0 keyword_statement",
    )
    # Agent C passthrough — used to populate Level 0 and top-level response fields
    keyword_structured: str = Field(
        default="",
        description="Agent C's boolean anchor query (keyword.structured) — used as Level 0 search_query; "
                    "derived from anchor_blocks if not provided",
    )
    search_filters: Optional["SearchFilters"] = Field(
        default=None,
        description="Agent C's search filters — passed through to SearchExpansionResponse",
    )
    phrases: List[str] = Field(
        default_factory=list,
        description="Agent C's exact key phrases (keyword.phrases) — passed through to SearchExpansionResponse",
    )

    @field_validator("clarified_query")
    @classmethod
    def validate_non_empty(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("clarified_query must be non-empty")
        return v.strip()


class ExpansionLevelLLMBroadening(BaseModel):
    """What the LLM proposes for one expansion level's broadening."""
    level: int
    label: str
    broadened_value: str = Field(description="What replaces the block; '(no restriction)' means remove")
    boolean_terms: List[str] = Field(
        default_factory=list,
        description="Replacement OR-terms for the broadened block; empty = remove block (geography only)",
    )
    controlled_vocabulary_hints: Dict[str, List[str]] = Field(
        default_factory=dict,
        description="Optional replacement CV terms for the broadened block (e.g. MeSH for setting broadening). "
                    "vocab_name → terms. Leave empty for geography broadening.",
    )
    clarified_query: str = Field(description="NL anchor adapted for this level's scope")
    rationale: str

    @field_validator("clarified_query")
    @classmethod
    def validate_clarified_query_non_empty(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("clarified_query must be non-empty")
        return v.strip()


class SearchExpansionLLMResponse(BaseModel):
    """Full LLM output for Agent D — broadening proposals only."""
    geography_broadening_strategy: str = Field(
        default="none",
        description="context_proxy | containment_hierarchy | none",
    )
    levels: List[ExpansionLevelLLMBroadening] = Field(default_factory=list)
    recommended_starting_level: int = Field(default=1)
    recommendation_rationale: str = Field(default="")


class ExpansionLevel(BaseModel):
    """One complete expansion level — same structure at every level for uniform downstream consumption."""
    model_config = ConfigDict(populate_by_name=True)
    level: int
    label: str
    search_query: str = Field(
        serialization_alias="boolean_query",
        description="Generic boolean query (free-text terms only, no field tags)",
    )
    clarified_query: str = Field(
        serialization_alias="query",
        description="Natural-language query for display and NL-search databases (ReliefWeb, WHO IRIS)",
    )
    semantic_statement: str = Field(
        default="",
        serialization_alias="semantic_query",
        description="Dense or natural-language semantic query for vector/semantic search. "
                    "Level 0 uses Agent B's semantic query. Levels 1-3 use the broadened natural-language query.",
    )
    keyword_statement: str = Field(
        default="",
        serialization_alias="keyword_query",
        description="Compact keyword query for BM25/simple keyword search. "
                    "Level 0: Agent B's keyword_query. Levels 1-3: derived from blocks without Boolean wildcards.",
    )
    controlled_vocabulary: Dict[str, List[str]] = Field(
        default_factory=dict,
        description="vocabulary_name → terms for database-specific connectors (e.g. MeSH for PubMed). "
                    "Geography block CV excluded at Level 2+ (MeSH geo terms don't transfer to broadened searches).",
    )
    blocks: List[CombinedBlock] = Field(
        default_factory=list,
        description="Structured blocks — same interface as Agent C combined_blocks at every level. "
                    "Use these to build source-specific queries (PubMed field tags, CORE boolean, etc.) "
                    "without parsing search_query. Geography block absent at Level 3; replaced at Level 2.",
    )
    broadened_aspect: str = Field(default="", description="Which block role was modified (e.g. 'geography')")
    broadened_value: str = Field(default="", description="What the aspect was replaced with; empty at Level 1")
    rationale: str
    cochrane_compliant: bool = Field(
        default=False,
        description="True when all geographic restriction has been removed (Cochrane-sensitive search)",
    )


class SearchExpansionResponse(BaseModel):
    """Agent D output — all levels share the same ExpansionLevel structure.

    Level 0 is the anchor (Agent C output). Level 1+ are broadening levels.
    Level 1 is built deterministically in Python. Level 2+ from LLM proposals.
    """
    levels: List[ExpansionLevel] = Field(default_factory=list)
    geography_broadening_strategy: str = Field(default="none")
    recommended_starting_level: int = Field(default=1)
    recommendation_rationale: str = Field(default="")
    search_filters: Optional["SearchFilters"] = Field(
        default=None,
        description="Agent C search filters (publication_years, publication_types, etc.) — applies to all levels",
    )
    phrases: List[str] = Field(
        default_factory=list,
        description="Agent C exact key phrases — for exact-phrase matching at any level",
    )





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
    search_filters: SearchFilters = Field(default_factory=SearchFilters)

    @model_validator(mode="before")
    @classmethod
    def _decode_string_fields(cls, data):
        if isinstance(data, dict):
            for field in ("keyword", "search_filters"):
                v = data.get(field)
                if isinstance(v, str):
                    v = v.strip()
                    start = v.find("{")
                    if start != -1:
                        obj, _ = _json.JSONDecoder().raw_decode(v, start)
                        data[field] = obj
                    else:
                        data[field] = _json.loads(v)
        return data


# Backward compatibility alias

__all__ = [
    "DimensionEvaluationResponse",
    "QueryRefinementResponse",
    "SearchOptimized",
    "SearchFilters",
    "Terminology",
    "SearchExpansionContext",
    "SearchExpansionInput",
    "ExpansionLevelLLMBroadening",
    "SearchExpansionLLMResponse",
    "ExpansionLevel",
    "SearchExpansionResponse",
    "CombinedBlock",
    "VocabularyHint",
    "ConceptEntry",
    "ResearchStatementResponse",
    "SemanticRepresentationResponse",
    "SearchConstructionResponse",
]