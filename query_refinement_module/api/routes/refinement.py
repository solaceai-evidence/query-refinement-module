"""
Query refinement workflow API routes with comprehensive logging and tracing.

Integrates the core refinement pipeline with API endpoints.

Key Features:
- Request ID generation for distributed tracing
- Comprehensive logging at all stages
- LLM metadata capture (tokens, cost, duration)
- Database metadata persistence
- Performance monitoring
- Error handling with detailed context
"""
import asyncio
import json
import logging
import time
from fastapi import APIRouter, Body, Depends, HTTPException, status, Request
from sqlalchemy.orm import Session
from typing import Dict, Any, Optional, Union, List

logger = logging.getLogger(__name__)

from query_refinement_module.db.session import get_db
from query_refinement_module.db.crud import (
    get_query,
    update_refined_query,
    get_query_refinement_steps,
    abandon_query_session,
    get_user_framework_names,
    update_refinement_step_final_value,
)
from query_refinement_module.api.auth import get_current_user_or_integration
from query_refinement_module.api.config import get_settings
from query_refinement_module.api.dependencies import get_refinement_manager, get_session_manager
from query_refinement_module.schema.registry import get_framework, list_frameworks
from query_refinement_module.api.session_manager import SessionManager
from query_refinement_module.audit import audit_service
from query_refinement_module.db.models.audit_log import AuditEventType
from query_refinement_module.application.refinement_api_service import RefinementApiService
from query_refinement_module.application.refinement_workflow import (
    is_session_ready_for_synthesis as workflow_is_session_ready_for_synthesis,
    restore_session_from_db_state as workflow_restore_session_from_db_state,
)
from query_refinement_module.settings import LLMSettings
from query_refinement_module.core import (
    QueryRefinementManager,
)
from query_refinement_module.tracing import generate_request_id, get_logger, set_request_id
from query_refinement_module.services.progress_tracker import get_progress_tracker, track_progress
from query_refinement_module.models.progress import ProgressStage
from query_refinement_module.schema import (
    QueryRefinementResponse,
    SearchExpansionContext,
)
from query_refinement_module.schema.response import (
    CombinedBlock,
    SearchExpansionInput,
    SearchExpansionResponse,
)

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator, AnyHttpUrl


router = APIRouter(prefix="/refinement", tags=["Query Refinement Workflow"])


# ==========================================
# Request/Response Models
# ==========================================

class StartRefinementRequest(BaseModel):
    """Request to start a new refinement workflow."""
    original_query: str = Field(
        ..., 
        min_length=3,
        max_length=5000,
        description="The query to refine"
    )
    framework_name: str = Field(
        ..., 
        min_length=1,
        max_length=128,
        description="Name of the refinement framework to use"
    )
    source: str = Field(
        default="gui",
        description="Request origin channel: gui or api_integration",
    )
    skip_refinement: bool = Field(
        default=False,
        description="When True, skip all refinement dimensions and go straight to synthesis. "
                    "No per-dimension LLM calls are made; only the synthesis LLM call is used."
    )

    @field_validator('original_query')
    @classmethod
    def query_not_empty(cls, v: str) -> str:
        """Validate that query is not just whitespace."""
        if not v or not v.strip():
            raise ValueError("Query cannot be empty or just whitespace")
        if len(v.strip()) < 3:
            raise ValueError("Query must be at least 3 characters long")
        return v.strip()
    
    @field_validator('framework_name')
    @classmethod
    def framework_not_empty(cls, v: str) -> str:
        """Validate that framework name is not just whitespace."""
        if not v or not v.strip():
            raise ValueError("Framework name cannot be empty or just whitespace")
        return v.strip()

    @field_validator('source')
    @classmethod
    def validate_source(cls, v: str) -> str:
        """Validate supported request sources."""
        normalized = (v or '').strip().lower()
        if normalized not in {"gui", "api_integration"}:
            raise ValueError("source must be one of: gui, api_integration")
        return normalized


class StartRefinementResponse(BaseModel):
    """Response with session details and initialization summary."""
    session_id: int = Field(..., description="Database session ID")
    query_id: int = Field(..., description="Database query ID")
    summary: Dict[str, Any] = Field(..., description="Initialization analysis summary")
    next_prompt: Optional[Dict[str, Any]] = Field(
        None,
        description=(
            "Next question for the user. Shape: {aspect_id, name, aspect_name, question, description, examples}. "
            "`question` is plain prose. `examples` is a list of 0–4 concrete quick-reply strings "
            "that span the clarification space and can be rendered as clickable buttons."
        ),
    )
    ready_for_synthesis: bool = Field(False, description="True if all aspects are complete and ready for synthesis")
    source: str = Field(..., description="Request origin channel")
    synthesis: Optional["SynthesizeQueryResponse"] = Field(
        None,
        description="Populated when skip_refinement=True: full synthesis result embedded "
                    "in the start response so no follow-up /synthesize call is needed."
    )


class SubmitAnswerRequest(BaseModel):
    """Request to submit an answer to a refinement question."""
    answer: str = Field(
        ..., 
        min_length=1,
        max_length=2000,
        description="User's answer to the current question or a command (e.g., /status, /back)"
    )
    force: Optional[bool] = Field(
        False,
        description="Force navigation commands that invalidate dependent aspects"
    )
    
    @field_validator('answer')
    @classmethod
    def answer_not_empty(cls, v: str) -> str:
        """Validate that answer is not just whitespace."""
        if not v or not v.strip():
            raise ValueError("Answer cannot be empty or just whitespace")
        return v.strip()


class SubmitAnswerResponse(BaseModel):
    """Response after processing user's answer."""
    refinement_step_id: int = Field(..., description="ID of the refinement step")
    followup_id: int = Field(..., description="ID of the follow-up entry")
    is_complete: bool = Field(..., description="Whether the aspect is complete")
    next_prompt: Optional[Dict[str, Any]] = Field(
        None,
        description="Next question if follow-up needed. Includes `examples` list for quick-reply buttons.",
    )
    ready_for_synthesis: bool = Field(False, description="True if all aspects are complete and ready for synthesis")


class CommandResponse(BaseModel):
    """Response when user issues a command instead of answering."""
    command_type: str = Field(..., description="Type of command executed (status, back, skip, etc.)")
    success: bool = Field(..., description="Whether command executed successfully")
    message: str = Field(..., description="Human-readable feedback message")
    next_prompt: Optional[Dict[str, Any]] = Field(
        None,
        description="Next question after command execution. Includes `examples` list for quick-reply buttons.",
    )
    
    # Optional fields for specific commands
    invalidated_aspects: Optional[List[str]] = Field(None, description="Aspects marked for review (/back, /restart)")
    synthesis_ready: bool = Field(False, description="True if session ready for synthesis (/submit)")
    step_summary: Optional[Dict[str, Any]] = Field(None, description="Step statistics (/status)")
    step_list: Optional[List[Dict[str, Any]]] = Field(None, description="All steps with status (/steps)")
    force_required: Optional[bool] = Field(None, description="True if command requires force=true flag")


class GetRefinementStatusResponse(BaseModel):
    """Current status of a refinement workflow."""
    query_id: int
    original_query: str
    refined_query: Optional[str]
    is_complete: bool
    current_aspect: Optional[str]
    aspects_summary: Dict[str, Any]
    next_prompt: Optional[Dict[str, Any]] = Field(
        None,
        description="Next question for the user. Includes `examples` list for quick-reply buttons.",
    )
    ready_for_synthesis: bool = Field(False, description="True if all aspects are complete and ready for synthesis")
    aspects: List[Dict[str, Any]] = Field(default_factory=list, description="List of aspect summaries")
    conversation_history: List[Dict[str, Any]] = Field(default_factory=list, description="Full conversation history for UI restoration")


class ResumeRefinementResponse(GetRefinementStatusResponse):
    """Current refinement state after an explicit resume operation."""


class SynthesizeQueryRequest(BaseModel):
    """Request to synthesize the refined query."""
    query_id: int = Field(..., gt=0, description="ID of the query to synthesize")
    include_expansion: bool = Field(
        False,
        description=(
            "When true, Agent D (search expansion) runs automatically after A→B→C "
            "and the results are included in expansion_levels and expansion_metadata. "
            "Requires Agent C to produce combined_blocks. Adds one LLM call of latency "
            "when geography or setting blocks are present; Level 1 only otherwise (no LLM)."
        ),
    )


# ---------------------------------------------------------------------------
# Individual agent request / response models
# ---------------------------------------------------------------------------

class NormalizeQueryRequest(BaseModel):
    """Agent A — Normalization request. Requires a completed refinement session."""
    query_id: int = Field(..., gt=0, description="ID of a session ready for synthesis")


class NormalizeQueryResponse(BaseModel):
    """
    Agent A — Normalization response.

    Returns the clean, human-readable research statement without running
    Agents B or C. The session is NOT marked as synthesized — a subsequent
    call to POST /synthesize remains valid.
    """
    query_id: int
    clarified_query: str = Field(
        ...,
        description=(
            "Clarified research statement integrating all refined dimension values. "
            "Human-readable; suitable for display, QA forwarding, or as input to POST /represent."
        ),
    )
    dimensions_specifications: Dict[str, Any] = Field(
        default_factory=dict,
        description="Per-dimension id → refined value, assembled deterministically from session state.",
    )
    used_llm: bool = Field(True, description="Always True; Agent A was invoked.")


class RepresentQueryRequest(BaseModel):
    """Agent B — Semantic Representation request. Accepts Agent A output directly."""
    statement: str = Field(
        ...,
        min_length=3,
        description="Clarified research statement from Agent A (POST /normalize → clarified_query).",
    )
    model: Optional[str] = Field(None, description="Optional LLM model override")

    @field_validator("statement")
    @classmethod
    def _not_empty(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("statement cannot be empty")
        return v.strip()


class RepresentQueryResponse(BaseModel):
    """
    Agent B — Semantic Representation response.

    Produces two filter-free query strings and a structured concept graph.
    Both query strings share the same search_filters produced by Agent C (POST /construct).
    """
    semantic_statement: str = Field(
        ...,
        description=(
            "Dense embedding query (2-3 sentences, 50-70 words) for vector / semantic search. "
            "Information-need framing using document-side vocabulary."
        ),
    )
    keyword_statement: str = Field(
        ...,
        description=(
            "Natural-language keyword query (15-35 words) for BM25 / simple keyword search. "
            "Key concepts and primary synonyms; no Boolean operators; no metadata filters."
        ),
    )
    concept_graph: Dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "Per-concept retrieval metadata. Pass as search_context.concept_graph to "
            "POST /construct and POST /expand."
        ),
    )
    used_llm: bool = Field(True, description="Always True; Agent B was invoked.")


class ConstructSearchRequest(BaseModel):
    """Agent C — Search Construction request. Accepts Agents A and B output directly."""
    statement: str = Field(
        ...,
        min_length=3,
        description="Clarified research statement from Agent A (POST /normalize → clarified_query).",
    )
    concept_graph: Dict[str, Any] = Field(
        default_factory=dict,
        description="Concept graph from Agent B (POST /represent → concept_graph).",
    )
    model: Optional[str] = Field(None, description="Optional LLM model override")

    @field_validator("statement")
    @classmethod
    def _not_empty(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("statement cannot be empty")
        return v.strip()


class ConstructSearchResponse(BaseModel):
    """
    Agent C — Search Construction response.

    Produces Boolean keyword query constructions and metadata search filters.
    Filters apply to both the semantic_statement and keyword_statement from Agent B.
    """
    keyword: Dict[str, Any] = Field(
        ...,
        description=(
            "Keyword query artifacts: structured (Boolean), phrases, terms (required/optional/excluded), "
            "combined_blocks (primary RAG artifact — AND-blocks with free_text and controlled_vocabulary)."
        ),
    )
    search_filters: Dict[str, Any] = Field(
        ...,
        description=(
            "Metadata narrowing filters: publication_years, venues, authors, publication_types, "
            "fields_of_study. Apply to both semantic and keyword retrieval."
        ),
    )
    used_llm: bool = Field(True, description="Always True; Agent C was invoked.")


class SynthesizeQueryResponse(BaseModel):
    """
    Full output of the A→B→C synthesis pipeline.

    Pipeline stages and field mapping
    ----------------------------------
    Agent A — Normalization
      clarified_query
          Clarified research statement.
      structured_output["dimensions_specifications"]
          Per-dimension id → value map.

    Agent B — Semantic Representation
      structured_output["search_optimized"]["semantic"]
          Dense embedding query (50-75 words) for vector search.
      structured_output["concept_graph"]
          Per-concept retrieval metadata: true_synonyms, abbreviations,
          spelling_variants, lexical_variants, domain_terms, colloquial,
          controlled_vocabulary_hints (vocabulary_name, terms, confidence).
      structured_output["terminology"]
          Primary terms, synonyms, domain-specific, colloquial variants.

    Agent C — Search Construction
      structured_output["search_optimized"]["keyword"]["structured"]
          Boolean anchor query (AND-connected OR-blocks).
      structured_output["search_optimized"]["keyword"]["phrases"]
          Exact key phrases (2-4 words each).
      structured_output["search_optimized"]["keyword"]["terms"]
          required / optional / excluded single-word or compound terms.
      structured_output["search_optimized"]["keyword"]["combined_blocks"]  ← PRIMARY RAG ARTIFACT
          One entry per AND-block. Each entry has:
            role: query_role of the dominant concept in this block
            free_text: all OR-group terms for this block
            controlled_vocabulary: vocabulary_name → list of thesaurus headings
          Source connectors: OR free_text with controlled_vocabulary within each block,
          then AND all blocks together.
          Use controlled_vocabulary only for indexed databases (PubMed → MeSH, WHO IRIS → DeCS).
          Use free_text alone for unindexed sources (OpenAlex, ReliefWeb, CORE).
      structured_output["search_filters"]
          Metadata filters: publication_years, venues, publication_types, fields_of_study.

    Agent D — Search Expansion
      Included when include_expansion=true was set on the request.
      expansion_levels
          List of ExpansionLevel objects (same structure as POST /expand → levels).
          Level 0 is the anchor. Level 1 is always present (deterministic). Levels 2–3 require geography or
          setting blocks to be present in Agent C output.
      expansion_metadata
          geography_broadening_strategy, recommended_starting_level,
          recommendation_rationale, status, used_llm, generated_level_count.

      To call Agent D separately: POST /expand with
        statement = clarified_query
        anchor_blocks = structured_output["search_optimized"]["keyword"]["combined_blocks"]
        search_context.concept_graph = structured_output["concept_graph"]
    """
    query_id: int = Field(..., description="Database ID of the synthesized query")
    clarified_query: Optional[str] = Field(
        None,
        description=(
            "Agent A output. Clarified research statement integrating all user-provided "
            "dimension values. Pass as statement to /expand for Agent D broadening levels."
        ),
    )
    integrated_statement: Optional[str] = Field(
        None,
        description=(
            "Backward-compatible alias for clarified_query retained for existing frontend clients."
        ),
    )
    used_llm: bool = Field(..., description="Always True; LLM was invoked for synthesis")
    structured_output: Optional[Dict[str, Any]] = Field(
        None,
        description=(
            "Structured pipeline output. See class docstring for full field mapping. "
            "RAG connectors: primary artifact is "
            "structured_output['search_optimized']['keyword']['combined_blocks']."
        ),
    )
    expansion_levels: Optional[List[Dict[str, Any]]] = Field(
        None,
        description=(
            "Agent D output. Present only when include_expansion=true. "
            "List of expansion levels in ascending broadening order; Level 0 is the anchor."
        ),
    )
    expansion_metadata: Optional[Dict[str, Any]] = Field(
        None,
        description=(
            "Agent D metadata. Present only when include_expansion=true. "
            "Includes geography_broadening_strategy, recommended_starting_level, "
            "recommendation_rationale, status, used_llm, generated_level_count."
        ),
    )

    @model_validator(mode="before")
    @classmethod
    def _sync_statement_aliases(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data

        clarified_query = data.get("clarified_query")
        integrated_statement = data.get("integrated_statement")

        if not clarified_query and integrated_statement:
            data["clarified_query"] = integrated_statement
        if not integrated_statement and clarified_query:
            data["integrated_statement"] = clarified_query
        return data


class SearchExpandRequest(BaseModel):
    """
    Agent D — Search Expansion request.

    Generates Cochrane-compliant broadening levels beyond the anchor query.
    Level 0 (the anchor) is included in the response.

    Typical flow after POST /synthesize:
      statement            = synthesize_response.clarified_query
      anchor_blocks        = synthesize_response.structured_output["search_optimized"]["keyword"]["combined_blocks"]
      concept_graph        = synthesize_response.structured_output["concept_graph"]
      semantic_statement   = synthesize_response.structured_output["search_optimized"]["semantic"]
      keyword_statement    = synthesize_response.structured_output["keyword_statement"]
      keyword_structured   = synthesize_response.structured_output["search_optimized"]["keyword"]["structured"]
      search_filters       = synthesize_response.structured_output["search_filters"]
      phrases              = synthesize_response.structured_output["search_optimized"]["keyword"]["phrases"]

    Level 0  anchor        Exact Agent C output — no enrichment.
    Level 1  deterministic Full lexical ring built in Python — free_text + domain_terms per block. No LLM.
    Level 2  LLM-assisted  Geography block replaced with contextual analogy or geographic superset.
    Level 3  LLM-assisted  Geography block removed — Cochrane-compliant globally sensitive search.
    """
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "statement": "How to improve mental health outcomes among children in Qoloji camp, Ethiopia.",
                "anchor_blocks": [
                    {
                        "role": "topic_or_condition",
                        "free_text": ["mental health", "psychological wellbeing", "MHPSS"],
                        "controlled_vocabulary": {"MeSH": ["Mental Health"]},
                    },
                    {
                        "role": "population_or_entity",
                        "free_text": ["children under five", "young children", "U5"],
                        "controlled_vocabulary": {"MeSH": ["Child"]},
                    },
                    {
                        "role": "setting_or_context",
                        "free_text": ["refugee camp", "displacement camp", "IDP camp"],
                        "controlled_vocabulary": {"MeSH": ["Refugees", "Displaced Persons"]},
                    },
                    {
                        "role": "geography",
                        "free_text": ["Qoloji", "Ethiopia"],
                        "controlled_vocabulary": {"MeSH": ["Ethiopia"]},
                    },
                ],
                "search_context": {
                    "concept_graph": {
                        "mental health": {
                            "query_role": "topic_or_condition",
                            "domain_terms": ["psychosocial wellbeing", "depression", "anxiety"],
                        }
                    }
                },
                "semantic_statement": "Studies examining interventions to improve mental health outcomes among children in refugee camp settings in Ethiopia.",
                "keyword_statement": "mental health children refugee camp Ethiopia",
                "keyword_structured": "(mental health OR psychological wellbeing OR MHPSS) AND (children under five OR young children OR U5) AND (refugee camp OR displacement camp OR IDP camp) AND (Qoloji OR Ethiopia)",
                "search_filters": {
                    "publication_years": "",
                    "venues": [],
                    "authors": [],
                    "publication_types": [],
                    "fields_of_study": ["Public Health", "Psychology"],
                },
                "phrases": ["mental health outcomes", "children under five", "refugee camp Ethiopia"],
            }
        }
    )
    statement: str = Field(
        ...,
        description=(
            "Exact anchor query (unchanged). "
            "Use POST /normalize → clarified_query or POST /synthesize → clarified_query."
        ),
    )
    anchor_blocks: List[CombinedBlock] = Field(
        ...,
        description=(
            "Agent C combined_blocks from POST /construct → keyword.combined_blocks "
            "(or POST /synthesize → structured_output.search_optimized.keyword.combined_blocks). "
            "Level 1 is built deterministically in Python; the LLM is called only for "
            "geography broadening proposals (Levels 2–3)."
        ),
    )
    search_context: Optional[SearchExpansionContext] = Field(
        None,
        description=(
            "Optional retrieval context. Set search_context.concept_graph to "
            "POST /represent → concept_graph for domain_term enrichment at Level 1 "
            "and accurate broadening candidates at Levels 2–3."
        ),
    )
    # Agent B passthrough — used to populate Level 0
    semantic_statement: Optional[str] = Field(
        None,
        description="POST /represent → semantic_statement. Used as Level 0 semantic_statement.",
    )
    keyword_statement: Optional[str] = Field(
        None,
        description="POST /represent → keyword_statement. Used as Level 0 keyword_statement.",
    )
    # Agent C passthrough — used to populate Level 0 and response-level fields
    keyword_structured: Optional[str] = Field(
        None,
        description="POST /construct → keyword.structured. Used as Level 0 search_query.",
    )
    search_filters: Optional[Dict[str, Any]] = Field(
        None,
        description="POST /construct → search_filters. Passed through to response.",
    )
    phrases: Optional[List[str]] = Field(
        None,
        description="POST /construct → keyword.phrases. Passed through to response.",
    )
    model: Optional[str] = Field(None, description="Optional LLM model override")

    @field_validator("statement")
    @classmethod
    def validate_statement(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("statement cannot be empty or just whitespace")
        return v.strip()


class SearchExpandResponse(BaseModel):
    """Agent D — Search Expansion response.

    All levels share the same structure. Level 0 is always levels[0].

    Each level object:
      level                 int     Level number (0 = anchor, 1 = full lexical ring, 2-3 = broadening)
      label                 str     Short descriptor
      boolean_query         str     Generic boolean query for PubMed, WHO IRIS, OpenAlex, CORE
      query                 str     NL query adapted for this level's scope.
                                    Use for ReliefWeb, WHO IRIS NL mode, UI display, and semantic fallback.
      semantic_query        str     Semantic/vector query for this level.
      keyword_query         str     BM25/simple keyword query for this level.
      controlled_vocabulary dict    vocabulary_name → term list for database-specific connectors.
                                    Use MeSH terms with [MeSH Terms] tag for PubMed.
                                    Geography block CV excluded at Level 2+ by design.
      broadened_aspect      str     Which block role was modified (e.g. "geography"). Empty at Level 1.
      broadened_value       str     What the aspect was replaced with. Empty at Level 1.
      rationale             str     Why this broadening improves Cochrane-compliant recall.
      cochrane_compliant    bool    true when geographic restriction is fully removed (Level 3).

    Apply levels in order: start with recommended_starting_level and escalate when
    result count at the current level is insufficient.
    """
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "levels": [
                    {
                        "level": 0,
                        "label": "Anchor query",
                        "query": "How to improve mental health outcomes among children in Qoloji camp, Ethiopia.",
                        "semantic_query": "Studies examining interventions to improve mental health outcomes among children in refugee camp settings in Ethiopia.",
                        "keyword_query": "mental health children refugee camp Ethiopia",
                        "boolean_query": "(mental health OR psychological wellbeing OR MHPSS) AND (children under five OR young children OR U5) AND (refugee camp OR displacement camp OR IDP camp) AND (Qoloji OR Ethiopia)",
                        "controlled_vocabulary": {"MeSH": ["Mental Health", "Child", "Ethiopia"]},
                        "blocks": [
                            {
                                "role": "topic_or_condition",
                                "free_text": ["mental health", "psychological wellbeing", "MHPSS"],
                                "controlled_vocabulary": {"MeSH": ["Mental Health"]},
                            }
                        ],
                        "broadened_aspect": "",
                        "broadened_value": "",
                        "rationale": "Your refined query as-is — exact concepts from your refinement session, no broadening.",
                        "cochrane_compliant": False,
                    },
                    {
                        "level": 1,
                        "label": "Full lexical ring",
                        "query": "How to improve mental health outcomes among children in Qoloji camp, Ethiopia.",
                        "semantic_query": "How to improve mental health outcomes among children in Qoloji camp, Ethiopia.",
                        "keyword_query": "mental health psychological wellbeing MHPSS children under five young children refugee camp displacement camp Qoloji Ethiopia",
                        "boolean_query": "(mental health OR psychological wellbeing OR MHPSS OR depression OR anxiety) AND (children under five OR young children OR U5) AND (refugee camp OR displacement camp OR IDP camp) AND (Qoloji OR Ethiopia)",
                        "controlled_vocabulary": {"MeSH": ["Mental Health", "Child", "Ethiopia"]},
                        "blocks": [
                            {
                                "role": "topic_or_condition",
                                "free_text": ["mental health", "psychological wellbeing", "MHPSS", "depression", "anxiety"],
                                "controlled_vocabulary": {"MeSH": ["Mental Health"]},
                            }
                        ],
                        "broadened_aspect": "",
                        "broadened_value": "",
                        "rationale": "Full synonym and domain-term ring for every concept block.",
                        "cochrane_compliant": False,
                    },
                    {
                        "level": 2,
                        "label": "Contextual analogy — conflict-affected settings",
                        "query": "How to improve mental health outcomes among children in displacement camps in conflict-affected low- and middle-income countries.",
                        "semantic_query": "How to improve mental health outcomes among children in displacement camps in conflict-affected low- and middle-income countries.",
                        "keyword_query": "mental health psychological wellbeing MHPSS children under five young children refugee camp displacement camp conflict-affected settings LMICs",
                        "boolean_query": "(mental health OR psychological wellbeing OR MHPSS OR depression OR anxiety) AND (children under five OR young children OR U5) AND (refugee camp OR displacement camp OR IDP camp) AND (conflict-affected settings OR fragile states OR LMICs)",
                        "controlled_vocabulary": {"MeSH": ["Mental Health", "Child"]},
                        "blocks": [
                            {
                                "role": "geography",
                                "free_text": ["conflict-affected settings", "fragile states", "LMICs"],
                                "controlled_vocabulary": {},
                            }
                        ],
                        "broadened_aspect": "geography",
                        "broadened_value": "conflict-affected low- and middle-income countries",
                        "rationale": "Broadens beyond the named location to comparable humanitarian settings.",
                        "cochrane_compliant": False,
                    },
                ],
                "geography_broadening_strategy": "context_proxy",
                "recommended_starting_level": 2,
                "recommendation_rationale": "The named camp is too specific for first-pass retrieval; start with a comparable-context search.",
                "search_filters": {
                    "publication_years": "",
                    "venues": [],
                    "authors": [],
                    "publication_types": [],
                    "fields_of_study": ["Public Health", "Psychology"],
                },
                "phrases": ["mental health outcomes", "children under five", "refugee camp Ethiopia"],
                "metadata": {
                    "status": "completed",
                    "generated_level_count": 3,
                    "used_llm": True,
                    "total_tokens": 1234,
                },
            }
        }
    )
    levels: List[Dict[str, Any]] = Field(
        ...,
        description=(
            "Ordered expansion levels (Level 0 first). "
            "Each entry: {level, label, query, semantic_query, keyword_query, boolean_query, controlled_vocabulary, "
            "broadened_aspect, broadened_value, rationale, cochrane_compliant}."
        ),
    )
    geography_broadening_strategy: str = Field(
        default="none",
        description="Broadening strategy used for geography when present.",
    )
    recommended_starting_level: int = Field(
        default=1,
        description="Recommended level to run first following Cochrane-style escalation logic.",
    )
    recommendation_rationale: str = Field(
        default="",
        description="Why the recommended_starting_level is the best initial retrieval level.",
    )
    search_filters: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Agent C search filters that apply across all levels.",
    )
    phrases: Optional[List[str]] = Field(
        default=None,
        description="Agent C key phrases that apply across all levels.",
    )
    metadata: Optional[Dict[str, Any]] = Field(
        None,
        description=(
            "Generation metadata: status, generated_level_count, used_llm, total_tokens."
        ),
    )


class ForwardToQARequest(BaseModel):
    """Request to forward refined query to external QA system."""
    qa_system_url: AnyHttpUrl = Field(
        ...,
        description="URL of the external question-answering system"
    )
    qa_system_auth: Optional[Dict[str, str]] = Field(
        None,
        description="Authentication headers for the QA system (e.g., {'Authorization': 'Bearer token'})"
    )
    timeout_seconds: int = Field(
        default=30,
        ge=5,
        le=120,
        description="Request timeout in seconds"
    )
    include_refinement_metadata: bool = Field(
        default=True,
        description="Include refinement metadata in the request to QA system"
    )
    forward_original_query: bool = Field(
        default=False,
        description="Also include the original query alongside the refined query"
    )

    @field_validator("qa_system_url")
    @classmethod
    def _no_private_url(cls, v: AnyHttpUrl) -> AnyHttpUrl:
        """Block RFC-1918, loopback, and link-local targets to prevent SSRF."""
        import ipaddress
        host = v.host or ""
        if host.lower() in {"localhost", "0.0.0.0"}:
            raise ValueError("Internal/loopback hostnames are not permitted as qa_system_url")
        try:
            addr = ipaddress.ip_address(host)
            if addr.is_private or addr.is_loopback or addr.is_link_local or addr.is_reserved:
                raise ValueError("Private or internal IP addresses are not permitted as qa_system_url")
        except ValueError as exc:
            if "not permitted" in str(exc):
                raise
        return v

    @field_validator("qa_system_auth")
    @classmethod
    def _safe_auth_headers(cls, v: Optional[Dict[str, str]]) -> Optional[Dict[str, str]]:
        """Reject hop-by-hop and host-spoofing headers that could alter request semantics."""
        if not v:
            return v
        _FORBIDDEN = frozenset({
            "host", "content-length", "transfer-encoding",
            "connection", "te", "trailer", "upgrade",
        })
        for key in v:
            if key.lower() in _FORBIDDEN:
                raise ValueError(f"Header '{key}' is not permitted in qa_system_auth")
        return v


class ForwardToQAResponse(BaseModel):
    """Response from forwarding to external QA system."""
    query_id: int
    refined_query: str
    original_query: Optional[str] = None
    qa_system_url: str
    qa_system_response: Dict[str, Any]
    qa_system_status_code: int
    response_time_ms: int
    refinement_metadata: Optional[Dict[str, Any]] = None


# ==========================================
# Utility Functions
# ==========================================

def _restore_session_from_db_state(session, db_steps: List[Any]) -> None:
    """Restore in-memory session state from persisted DB refinement step rows."""
    workflow_restore_session_from_db_state(session, db_steps)


def _is_session_ready_for_synthesis(session) -> bool:
    """Return True when synthesis can be safely executed for a session."""
    return workflow_is_session_ready_for_synthesis(session)
# ==========================================
# Refinement Workflow Endpoints
# ==========================================

@router.get("/frameworks")
def get_available_frameworks(
    current_user = Depends(get_current_user_or_integration),
    db: Session = Depends(get_db),
):
    """
    List all available refinement frameworks.
    """
    frameworks = list_frameworks()
    if not current_user.is_superuser:
        allowed = set(get_user_framework_names(db, current_user.id))
        frameworks = [name for name in frameworks if name in allowed]

    return {
        "frameworks": frameworks,
        "count": len(frameworks)
    }


@router.post("/start", response_model=StartRefinementResponse, status_code=status.HTTP_201_CREATED)
async def start_refinement(
    request: StartRefinementRequest,
    manager: QueryRefinementManager = Depends(get_refinement_manager),
    current_user = Depends(get_current_user_or_integration),
    db: Session = Depends(get_db),
    session_manager: SessionManager = Depends(get_session_manager)
):
    """
    Start a new query refinement workflow using sequential on-demand mode.
    
    This initializes a refinement session by:
    1. Loading the specified framework
    2. Creating session WITHOUT upfront LLM analysis
    3. Creating database records for session, query, and steps
    4. Generating first question on-demand and returning it
    
    Aspects are refined sequentially in dependency order, one at a time.
    """
    from query_refinement_module.tracing import generate_request_id, set_request_id, get_request_id
    
    # Generate and set request ID for tracing
    request_id = generate_request_id()
    set_request_id(request_id)
    
    workflow_service = RefinementApiService(
        manager=manager,
        db=db,
        session_manager=session_manager,
        settings_factory=get_settings,
    )
    payload = await workflow_service.start_workflow(
        original_query=request.original_query,
        framework_name=request.framework_name,
        source=request.source,
        skip_refinement=request.skip_refinement,
        current_user=current_user,
        request_id=request_id,
    )
    return StartRefinementResponse(**payload)


@router.post("/queries/{query_id}/answer", response_model=Union[SubmitAnswerResponse, CommandResponse])
async def submit_answer(
    query_id: int,
    request: SubmitAnswerRequest,
    http_request: Request,
    manager: QueryRefinementManager = Depends(get_refinement_manager),
    current_user = Depends(get_current_user_or_integration),
    db: Session = Depends(get_db),
    session_manager: SessionManager = Depends(get_session_manager)
):
    """
    Submit an answer to the current refinement question, or execute a command.
    
    Regular answer processing:
    1. Stores answer in the follow-up history
    2. Runs the follow-up loop to check if more clarification is needed
    3. Marks the aspect as complete if satisfied
    4. Returns the next question if follow-up is needed, or moves to next aspect
    
    Command processing (input starts with /):
    - Information commands (/status, /steps, /help): Return session state
    - Navigation commands (/back, /restart): Modify session state and return new active step
    - Control commands (/skip, /done): Mark current step complete and advance
    - Synthesis command (/submit, /end): Flag session ready for synthesis
    """
    from query_refinement_module.tracing import generate_request_id, set_request_id, get_request_id
    
    # Generate and set request ID for tracing
    request_id = generate_request_id()
    set_request_id(request_id)
    
    workflow_service = RefinementApiService(
        manager=manager,
        db=db,
        session_manager=session_manager,
        settings_factory=get_settings,
    )
    result = await workflow_service.submit_answer(
        query_id=query_id,
        answer=request.answer,
        force=bool(request.force),
        current_user=current_user,
        http_request=http_request,
        request_id=request_id,
    )
    if isinstance(result, CommandResponse):
        return result
    if isinstance(result, dict) and "command_type" in result:
        return CommandResponse(**result)
    return SubmitAnswerResponse(**result)


@router.get("/queries/{query_id}/status", response_model=GetRefinementStatusResponse)
async def get_refinement_status(
    query_id: int,
    manager: QueryRefinementManager = Depends(get_refinement_manager),
    current_user = Depends(get_current_user_or_integration),
    db: Session = Depends(get_db),
    session_manager: SessionManager = Depends(get_session_manager)
):
    """
    Get the current status of a refinement workflow.
    """
    from query_refinement_module.tracing import generate_request_id, set_request_id, get_request_id
    
    # Generate and set request ID for tracing
    request_id = generate_request_id()
    set_request_id(request_id)
    
    workflow_service = RefinementApiService(
        manager=manager,
        db=db,
        session_manager=session_manager,
        settings_factory=get_settings,
    )
    payload = await workflow_service.get_status_payload(
        query_id=query_id,
        current_user=current_user,
        request_id=request_id,
    )
    return GetRefinementStatusResponse(**payload)


@router.post("/queries/{query_id}/resume", response_model=ResumeRefinementResponse)
async def resume_refinement(
    query_id: int,
    manager: QueryRefinementManager = Depends(get_refinement_manager),
    current_user = Depends(get_current_user_or_integration),
    db: Session = Depends(get_db),
    session_manager: SessionManager = Depends(get_session_manager),
):
    """Resume a refinement workflow and explicitly generate the next prompt when needed."""
    request_id = generate_request_id()
    set_request_id(request_id)
    workflow_service = RefinementApiService(
        manager=manager,
        db=db,
        session_manager=session_manager,
        settings_factory=get_settings,
    )
    payload = await workflow_service.resume_workflow(
        query_id=query_id,
        current_user=current_user,
        request_id=request_id,
    )
    return ResumeRefinementResponse(**payload)


# ==========================================
# Synthesis helper – shared by /synthesize and skip_refinement fast-path
# ==========================================

def _dimension_value_is_accepted(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return value.strip() not in {"", "[SKIPPED]", "null"}
    return True


@router.post("/expand", response_model=SearchExpandResponse)
async def expand_search(
    request: SearchExpandRequest,
    manager: QueryRefinementManager = Depends(get_refinement_manager),
    current_user = Depends(get_current_user_or_integration),
):
    """
    Agent D — Search Expansion. Cochrane-compliant recall ladder beyond the anchor query.

    Level 1  deterministic  Free_text + domain_terms per block — built in Python, no LLM.
    Level 2  LLM-assisted   Geography block replaced (contextual analogy or superset).
    Level 3  LLM-assisted   Geography block removed — Cochrane-sensitive globally open search.

    All output levels share the same structure: boolean_query, query, semantic_query,
    keyword_query, controlled_vocabulary, and cochrane_compliant flag.
    """
    request_id_val = generate_request_id()
    set_request_id(request_id_val)
    start_time = time.time()

    concept_graph = {}
    if request.search_context and request.search_context.concept_graph:
        concept_graph = request.search_context.concept_graph

    logger.info(
        "API: Generating search expansion levels",
        extra={
            "request_id": request_id_val,
            "user_id": current_user.id,
            "model_override": request.model,
            "statement_length": len(request.statement),
            "anchor_block_count": len(request.anchor_blocks),
        },
    )

    try:
        expansion_input = SearchExpansionInput(
            clarified_query=request.statement,
            anchor_blocks=request.anchor_blocks,
            concept_graph=concept_graph,
            semantic_statement=request.semantic_statement or "",
            keyword_statement=request.keyword_statement or "",
            keyword_structured=request.keyword_structured or "",
            search_filters=request.search_filters,
            phrases=request.phrases or [],
        )
        result, metadata = await manager.generate_search_expansion_levels(
            search_input=expansion_input,
            model=request.model,
        )
        levels_payload = [level.model_dump(by_alias=True) for level in result.levels]
        metadata["geography_broadening_strategy"] = result.geography_broadening_strategy
        metadata["recommended_starting_level"] = result.recommended_starting_level
        metadata["recommendation_rationale"] = result.recommendation_rationale
        if result.search_filters:
            metadata["search_filters"] = (
                result.search_filters.model_dump()
                if hasattr(result.search_filters, "model_dump")
                else result.search_filters
            )
        if result.phrases:
            metadata["phrases"] = result.phrases
    except Exception as exc:
        logger.exception(
            "API: Search expansion generation failed unexpectedly",
            extra={"request_id": request_id_val, "error": str(exc)},
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to generate search expansion levels: {str(exc)}",
        )

    duration_ms = (time.time() - start_time) * 1000
    logger.info(
        "API: Search expansion completed",
        extra={
            "request_id": request_id_val,
            "duration_ms": round(duration_ms, 2),
            "returned_level_count": len(levels_payload),
            "generated_level_count": metadata.get("generated_level_count", 0),
            "status": metadata.get("status"),
        },
    )
    return SearchExpandResponse(
        levels=levels_payload,
        geography_broadening_strategy=result.geography_broadening_strategy,
        recommended_starting_level=result.recommended_starting_level,
        recommendation_rationale=result.recommendation_rationale,
        search_filters=(
            result.search_filters.model_dump()
            if hasattr(result.search_filters, "model_dump")
            else result.search_filters
        ) if result.search_filters else None,
        phrases=result.phrases or None,
        metadata=metadata,
    )


# ==========================================
# Individual Agent Endpoints
# ==========================================

@router.post("/normalize", response_model=NormalizeQueryResponse)
async def normalize_query(
    request: NormalizeQueryRequest,
    manager: QueryRefinementManager = Depends(get_refinement_manager),
    current_user = Depends(get_current_user_or_integration),
    db: Session = Depends(get_db),
    session_manager: SessionManager = Depends(get_session_manager),
):
    """
    Agent A — Normalization. Returns the clarified research statement only.

    Use when you need a clean, human-readable version of the refined query without
    running Agents B or C. The session is NOT marked as synthesized — a subsequent
    call to POST /synthesize remains valid.

    Pass the returned clarified_query to POST /represent (Agent B) or directly
    to POST /expand (Agent D) as needed.
    """
    request_id_val = generate_request_id()
    set_request_id(request_id_val)

    db_query = get_query(db, request.query_id)
    if not db_query:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Query not found")
    if db_query.session.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")

    framework_name = db_query.session.framework_name
    if not framework_name:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Framework name not found for session")

    framework = get_framework(framework_name)

    try:
        async with session_manager.session_lock(request.query_id):
            session = session_manager.load_session(request.query_id, framework)
            if not session:
                session = await asyncio.to_thread(
                    manager.initialize_sequential,
                    db_query.original_query,
                    framework,
                )
                db_steps = get_query_refinement_steps(db, request.query_id)
                _restore_session_from_db_state(session, db_steps)

            if not _is_session_ready_for_synthesis(session):
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Query is not ready for normalization. Complete all dimensions or use /submit first.",
                )

            norm, _ = await manager._run_normalization(session)
    except RuntimeError:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Session is temporarily locked by another request. Please retry in a moment.",
        )

    return NormalizeQueryResponse(
        query_id=request.query_id,
        clarified_query=norm.clarified_query,
        dimensions_specifications=norm.dimensions_specifications,
        used_llm=True,
    )


@router.post("/represent", response_model=RepresentQueryResponse)
async def represent_query(
    request: RepresentQueryRequest,
    manager: QueryRefinementManager = Depends(get_refinement_manager),
    current_user = Depends(get_current_user_or_integration),
):
    """
    Agent B — Semantic Representation. Produces embedding and keyword query strings
    plus a structured concept graph from a clarified research statement.

    Input: clarified_query from POST /normalize (or POST /synthesize → clarified_query).
    Output: semantic_statement, keyword_statement, concept_graph.

    Pass concept_graph to POST /construct (Agent C) and POST /expand (Agent D).
    No session required — accepts raw text.
    """
    request_id_val = generate_request_id()
    set_request_id(request_id_val)

    logger.info(
        "API: Running Agent B (Semantic Representation)",
        extra={
            "request_id": request_id_val,
            "user_id": current_user.id,
            "statement_length": len(request.statement),
        },
    )

    try:
        sem, _ = await manager._run_semantic_representation(
            request.statement,
            model=request.model,
        )
    except Exception as exc:
        logger.exception("API: Agent B failed", extra={"request_id": request_id_val})
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Semantic representation failed: {exc}",
        )

    concept_graph_dict = {
        k: (v.model_dump() if hasattr(v, "model_dump") else v)
        for k, v in sem.concept_graph.items()
    }
    return RepresentQueryResponse(
        semantic_statement=sem.semantic_statement,
        keyword_statement=sem.keyword_statement,
        concept_graph=concept_graph_dict,
        used_llm=True,
    )


@router.post("/construct", response_model=ConstructSearchResponse)
async def construct_search(
    request: ConstructSearchRequest,
    manager: QueryRefinementManager = Depends(get_refinement_manager),
    current_user = Depends(get_current_user_or_integration),
):
    """
    Agent C — Search Construction. Builds Boolean query constructions and metadata
    search filters from a clarified statement and concept graph.

    Input: clarified_query from POST /normalize, concept_graph from POST /represent.
    Output: keyword (Boolean query + combined_blocks), search_filters.

    search_filters applies to both the semantic_statement and keyword_statement from Agent B.
    No session required — accepts raw text and concept graph.
    """
    request_id_val = generate_request_id()
    set_request_id(request_id_val)

    logger.info(
        "API: Running Agent C (Search Construction)",
        extra={
            "request_id": request_id_val,
            "user_id": current_user.id,
            "statement_length": len(request.statement),
            "concept_graph_size": len(request.concept_graph),
        },
    )

    try:
        construction, _ = await manager._run_search_construction(
            statement=request.statement,
            concept_graph=request.concept_graph,
            model=request.model,
        )
    except Exception as exc:
        logger.exception("API: Agent C failed", extra={"request_id": request_id_val})
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Search construction failed: {exc}",
        )

    keyword_dict = construction.keyword.model_dump() if hasattr(construction.keyword, "model_dump") else construction.keyword
    filters_dict = construction.search_filters.model_dump() if hasattr(construction.search_filters, "model_dump") else construction.search_filters

    return ConstructSearchResponse(
        keyword=keyword_dict,
        search_filters=filters_dict,
        used_llm=True,
    )


@router.post("/synthesize", response_model=SynthesizeQueryResponse)
async def synthesize_refined_query(
    request: SynthesizeQueryRequest,
    manager: QueryRefinementManager = Depends(get_refinement_manager),
    current_user = Depends(get_current_user_or_integration),
    db: Session = Depends(get_db),
    session_manager: SessionManager = Depends(get_session_manager)
):
    """
    Run the A→B→C synthesis pipeline and return all retrieval artifacts.

    Pipeline executed sequentially:
      Agent A — Normalization: integrates dimension values into a normalized research statement.
      Agent B — Semantic Representation: extracts concept graph and dense embedding query.
      Agent C — Search Construction: builds Boolean query, combined_blocks, and metadata filters.

    Primary fields for RAG integration:
      structured_output["search_optimized"]["keyword"]["combined_blocks"]
          Structured AND-blocks pairing free-text terms with controlled vocabulary.
          Use to build source-specific queries: OR terms within each block, AND blocks together.
          Applies to indexed databases (PubMed/MeSH, WHO IRIS/DeCS) and free-text sources.
      structured_output["search_optimized"]["semantic"]
          Dense embedding query for vector / semantic search.
      structured_output["search_optimized"]["keyword"]["structured"]
          Boolean query for keyword / sparse search.
      structured_output["concept_graph"]
          Agent B concept graph. Pass as search_context.concept_graph to POST /expand.
      structured_output["search_filters"]
          Metadata filters ready for database filter parameters.

    Set include_expansion=true to chain Agent D automatically and receive expansion_levels
    in the same response. POST /expand remains available as a standalone call.
    Session must be ready for synthesis: all dimensions answered or /submit issued.
    """
    from query_refinement_module.tracing import generate_request_id, set_request_id

    request_id_val = generate_request_id()
    set_request_id(request_id_val)
    start_time = time.time()

    logger.info(
        "API: Synthesizing refined query",
        extra={
            "request_id": request_id_val,
            "user_id": current_user.id,
            "query_id": request.query_id,
        },
    )

    workflow_service = RefinementApiService(
        manager=manager,
        db=db,
        session_manager=session_manager,
        settings_factory=get_settings,
    )
    payload = await workflow_service.synthesize_workflow(
        query_id=request.query_id,
        include_expansion=request.include_expansion,
        current_user=current_user,
        request_id=request_id_val,
    )

    duration_ms = (time.time() - start_time) * 1000
    logger.info(
        "Returning synthesis response",
        extra={
            "request_id": request_id_val,
            "duration_ms": round(duration_ms, 2),
            "response_query_id": payload["query_id"],
            "response_clarified_query_length": len(payload["clarified_query"]),
            "response_has_structured_output": payload["structured_output"] is not None,
        },
    )
    return SynthesizeQueryResponse(**payload)


# ==========================================
# QA System Forwarding Endpoint
# ==========================================

@router.post("/queries/{query_id}/forward-to-qa", response_model=ForwardToQAResponse)
async def forward_to_qa_system(
    query_id: int,
    request: ForwardToQARequest,
    current_user = Depends(get_current_user_or_integration),
    db: Session = Depends(get_db),
):
    """
    Forward a completed refined query to an external question-answering system.
    
    This endpoint enables middleware integration by forwarding the refined query
    to an external QA system AFTER the complete refinement process (with user
    clarifications for all dimensions).
    
    Requirements:
    - Query must exist and belong to the authenticated user
    - Query must have a refined_query (synthesis must be complete)
    - The refinement workflow must be finished (all dimensions clarified)
    
    The endpoint:
    1. Validates query completion
    2. Retrieves the refined query
    3. Forwards it to the specified QA system
    4. Returns both the refined query and QA system response
    Security:
    - User authentication required
    - Query ownership validated
    - QA system authentication passed through
    - Request timeout enforced
    """
    request_id_val = generate_request_id()
    set_request_id(request_id_val)
    request_logger = get_logger(__name__, request_id=request_id_val)
    
    start_time = time.time()
    
    request_logger.info(
        "API: Forward to QA system request received",
        extra={
            "request_id": request_id_val,
            "user_id": current_user.id,
            "query_id": query_id,
            "qa_system_url": request.qa_system_url,
            "timeout_seconds": request.timeout_seconds,
        },
    )
    
    # Verify query exists and belongs to user
    db_query = get_query(db, query_id=query_id)
    if not db_query:
        request_logger.warning(
            "Query not found",
            extra={"request_id": request_id_val, "query_id": query_id}
        )
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Query {query_id} not found"
        )
    
    # Verify ownership
    if db_query.session.user_id != current_user.id:
        request_logger.warning(
            "Unauthorized access attempt",
            extra={
                "request_id": request_id_val,
                "query_id": query_id,
                "query_owner_id": db_query.session.user_id,
                "requesting_user_id": current_user.id,
            }
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You don't have permission to access this query"
        )
    
    # Verify refinement is complete
    if not db_query.refined_query or not db_query.refined_query.strip():
        request_logger.warning(
            "Attempted to forward incomplete refinement",
            extra={
                "request_id": request_id_val,
                "query_id": query_id,
                "has_refined_query": bool(db_query.refined_query),
            }
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Query refinement is not complete. Please complete the synthesis step first."
        )
    
    # Prepare payload for QA system
    qa_payload = {
        "query": db_query.refined_query,
    }
    
    if request.forward_original_query:
        qa_payload["original_query"] = db_query.original_query
    
    if request.include_refinement_metadata:
        # Gather refinement metadata
        refinement_steps = get_query_refinement_steps(db, query_id=query_id)
        qa_payload["refinement_metadata"] = {
            "framework": db_query.session.framework_name if hasattr(db_query.session, 'framework_name') else None,
            "total_steps": len(refinement_steps),
            "dimensions_refined": [step.aspect_id for step in refinement_steps if step.is_refined],
            "query_id": query_id,
        }
    
    request_logger.info(
        "Forwarding refined query to external QA system",
        extra={
            "request_id": request_id_val,
            "query_id": query_id,
            "refined_query_length": len(db_query.refined_query),
            "payload_keys": list(qa_payload.keys()),
        }
    )
    
    # Forward to external QA system
    import httpx
    
    qa_start_time = time.time()
    try:
        async with httpx.AsyncClient(timeout=request.timeout_seconds) as client:
            headers = request.qa_system_auth or {}
            headers["Content-Type"] = "application/json"
            headers["X-Request-ID"] = request_id_val
            
            response = await client.post(
                request.qa_system_url,
                json=qa_payload,
                headers=headers
            )
            
            qa_response_time_ms = int((time.time() - qa_start_time) * 1000)
            
            # Try to parse JSON response
            try:
                qa_response_data = response.json()
            except Exception:
                qa_response_data = {"response": response.text}
            
            request_logger.info(
                "Received response from QA system",
                extra={
                    "request_id": request_id_val,
                    "query_id": query_id,
                    "status_code": response.status_code,
                    "response_time_ms": qa_response_time_ms,
                }
            )
            
            # Prepare response
            result = ForwardToQAResponse(
                query_id=query_id,
                refined_query=db_query.refined_query,
                original_query=db_query.original_query if request.forward_original_query else None,
                qa_system_url=request.qa_system_url,
                qa_system_response=qa_response_data,
                qa_system_status_code=response.status_code,
                response_time_ms=qa_response_time_ms,
                refinement_metadata=qa_payload.get("refinement_metadata") if request.include_refinement_metadata else None
            )
            
            total_duration_ms = int((time.time() - start_time) * 1000)
            request_logger.info(
                "API: Forward to QA system completed",
                extra={
                    "request_id": request_id_val,
                    "user_id": current_user.id,
                    "query_id": query_id,
                    "qa_status_code": response.status_code,
                    "qa_response_time_ms": qa_response_time_ms,
                    "total_duration_ms": total_duration_ms,
                },
            )
            
            return result
            
    except httpx.TimeoutException:
        request_logger.error(
            "QA system request timed out",
            extra={
                "request_id": request_id_val,
                "query_id": query_id,
                "timeout_seconds": request.timeout_seconds,
            }
        )
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail=f"QA system did not respond within {request.timeout_seconds} seconds"
        )
    except httpx.RequestError as e:
        request_logger.error(
            f"Failed to connect to QA system: {e}",
            extra={
                "request_id": request_id_val,
                "query_id": query_id,
                "qa_system_url": request.qa_system_url,
            },
            exc_info=True
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Failed to connect to QA system: {str(e)}"
        )
    except Exception as e:
        request_logger.error(
            f"Unexpected error during QA forwarding: {e}",
            extra={"request_id": request_id_val, "query_id": query_id},
            exc_info=True
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to forward query to QA system: {str(e)}"
        )


# ==========================================
# Command History Endpoint
# ==========================================

class CommandHistoryEntry(BaseModel):
    """Single command execution record."""
    timestamp: str
    event_id: int
    command: str
    command_input: str
    argument: Optional[str] = None
    active_dimension: Optional[str] = None
    success: bool
    status: str
    force_requested: bool
    force_confirmation_needed: bool
    cleared_aspects: Optional[List[str]] = None
    invalidated_aspects: Optional[List[str]] = None
    target_aspect: Optional[str] = None
    deleted_db_records: Optional[int] = None
    username: str
    request_id: Optional[str] = None


class CommandHistoryResponse(BaseModel):
    """Response containing command execution history for a query."""
    query_id: int
    total_commands: int
    commands: List[CommandHistoryEntry]


@router.get("/queries/{query_id}/command-history", response_model=CommandHistoryResponse)
def get_command_history(
    query_id: int,
    limit: int = 100,
    current_user = Depends(get_current_user_or_integration),
    db: Session = Depends(get_db),
):
    """
    Retrieve execution history of all commands for a specific query.
    
    Returns chronological list of command executions with full context:
    - Command type and arguments
    - Success/failure status
    - Affected dimensions (cleared, invalidated)
    - Active dimension at time of execution
    - User and timestamp information
    
    Useful for:
    - Debugging unexpected session states
    - Understanding user workflow patterns
    - Troubleshooting cascade delete issues
    - Compliance and audit trails
    
    Args:
        query_id: Query ID to get command history for
        limit: Maximum number of commands to return (default: 100)
    """
    from query_refinement_module.db.models.audit_log import AuditLog
    
    # Verify query ownership
    query = get_query(db, query_id)
    if not query or query.session.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Query not found"
        )
    
    # Query audit logs for command events
    command_event_types = [
        AuditEventType.COMMAND_EXECUTE,
        AuditEventType.COMMAND_BACK,
        AuditEventType.COMMAND_RESTART,
        AuditEventType.COMMAND_CLEAR,
        AuditEventType.COMMAND_SKIP,
        AuditEventType.COMMAND_DONE,
        AuditEventType.COMMAND_STATUS,
        AuditEventType.COMMAND_HELP,
        AuditEventType.COMMAND_STEPS,
    ]
    
    audit_logs = db.query(AuditLog).filter(
        AuditLog.resource_type == "query",
        AuditLog.resource_id == str(query_id),
        AuditLog.event_type.in_(command_event_types)
    ).order_by(AuditLog.timestamp.desc()).limit(limit).all()
    
    # Build command history entries
    commands = []
    for log in reversed(audit_logs):  # Reverse to get chronological order
        details = log.details or {}
        commands.append(CommandHistoryEntry(
            timestamp=log.timestamp.isoformat(),
            event_id=log.id,
            command=details.get("command", "unknown"),
            command_input=details.get("command_input", ""),
            argument=details.get("argument"),
            active_dimension=details.get("active_dimension"),
            success=details.get("success", False),
            status=log.status or "unknown",
            force_requested=details.get("force_requested", False),
            force_confirmation_needed=details.get("force_confirmation_needed", False),
            cleared_aspects=details.get("cleared_aspects"),
            invalidated_aspects=details.get("invalidated_aspects"),
            target_aspect=details.get("target_aspect"),
            deleted_db_records=details.get("deleted_db_records"),
            username=log.username or "unknown",
            request_id=log.request_id
        ))
    
    return CommandHistoryResponse(
        query_id=query_id,
        total_commands=len(commands),
        commands=commands
    )


# ==========================================
# Debug Endpoint - Inspect Messages
# ==========================================

class InspectMessagesResponse(BaseModel):
    """Response showing the actual messages sent to the LLM."""
    query_id: int
    current_dimension: Optional[str] = None
    message_count: int
    messages: List[Dict[str, Any]]


@router.get("/queries/{query_id}/inspect-messages", response_model=InspectMessagesResponse)
def inspect_messages(
    query_id: int,
    current_user = Depends(get_current_user_or_integration),
    session_manager: SessionManager = Depends(get_session_manager),
    db: Session = Depends(get_db),
):
    """
    Debug endpoint to inspect the actual messages being sent to the LLM.

    Shows the full message array with roles, content, and message count.
    """
    query = get_query(db, query_id)
    if not query or query.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Query not found"
        )

    session = session_manager.load_session(query_id)
    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Session not found or expired"
        )

    active_step = session.get_active_step()
    if not active_step:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No active dimension to inspect"
        )

    llm_settings = LLMSettings.from_env(require_model=False)
    dependency_context = session.get_dependency_context(active_step.refinement_aspect.id)
    messages = active_step.get_messages(
        query=session.original_query,
        dependency_context=dependency_context,
        terminal_reinforcement_threshold=llm_settings.terminal_reinforcement_threshold
    )

    return InspectMessagesResponse(
        query_id=query_id,
        current_dimension=active_step.refinement_aspect.id,
        message_count=len(messages),
        messages=messages,
    )


# ==========================================
# Session Abandonment Endpoint
# ==========================================

class AbandonSessionRequest(BaseModel):
    """Request to abandon/delete a session and all its data."""
    session_id: int = Field(..., gt=0, description="ID of the session to abandon")


class AbandonSessionResponse(BaseModel):
    """Response with deletion details."""
    status: str = Field(..., description="Status of the operation")
    session_id: int = Field(..., description="ID of the abandoned session")
    deletion_counts: Dict[str, int] = Field(..., description="Count of deleted records by type")
    message: str = Field(..., description="Human-readable message")


@router.post("/sessions/abandon", response_model=AbandonSessionResponse)
async def abandon_session(
    request: AbandonSessionRequest,
    http_request: Request,
    current_user = Depends(get_current_user_or_integration),
    db: Session = Depends(get_db),
    session_manager: SessionManager = Depends(get_session_manager)
):
    """
    Abandon/delete a session and all its associated data.
    
    This endpoint is used when a user clicks "Start Over" to clean up
    incomplete sessions. It:
    
    1. Deletes all refinement data (steps, follow-ups, feedback)
    2. Deletes all queries in the session
    3. Deletes the session itself
    4. Clears the Redis cache
    
    This ensures abandoned sessions don't count toward workflow limits.
    
    Note: AuditLog and FrontendLog entries are preserved for research.
    """
    from query_refinement_module.tracing import generate_request_id, set_request_id
    
    # Generate and set request ID for tracing
    request_id = generate_request_id()
    set_request_id(request_id)
    
    start_time = time.time()
    logger.info(
        "API: Abandoning session",
        extra={
            "request_id": request_id,
            "user_id": current_user.id,
            "session_id": request.session_id,
        },
    )
    
    try:
        # Abandon the session in database (includes authorization check)
        result = abandon_query_session(db, request.session_id, current_user.id)
        
        # Clear Redis cache for all queries in this session
        # Note: We don't have query_ids anymore, but the session is gone
        # Redis will expire naturally, but we can try to clear known keys
        # For now, just log that cache should be cleared
        logger.info(
            "Session abandoned, Redis cache will expire naturally",
            extra={
                "request_id": request_id,
                "session_id": request.session_id,
            }
        )
        
        # Log audit event
        try:
            audit_service.log_from_request(
                db=db,
                request=http_request,
                event_type=AuditEventType.SESSION_ABANDONED,
                user=current_user,
                resource_type="session",
                resource_id=str(request.session_id),
                action=f"Abandoned session {request.session_id}",
                status="success",
                details={
                    "deletion_counts": result["deletion_counts"],
                    "request_id": request_id,
                }
            )
        except Exception as e:
            logger.error(f"Failed to log audit event: {e}", exc_info=True)
        
        duration_ms = (time.time() - start_time) * 1000
        logger.info(
            "API: Session abandoned successfully",
            extra={
                "request_id": request_id,
                "user_id": current_user.id,
                "session_id": request.session_id,
                "deletion_counts": result["deletion_counts"],
                "duration_ms": round(duration_ms, 2),
            },
        )
        
        return AbandonSessionResponse(
            status="success",
            session_id=request.session_id,
            deletion_counts=result["deletion_counts"],
            message=f"Session {request.session_id} abandoned successfully. "
                   f"Deleted {result['deletion_counts']['queries']} queries, "
                   f"{result['deletion_counts']['refinement_steps']} refinement steps."
        )
        
    except ValueError as e:
        # Session not found or authorization failed
        logger.warning(
            f"Failed to abandon session: {e}",
            extra={
                "request_id": request_id,
                "user_id": current_user.id,
                "session_id": request.session_id,
            }
        )
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e)
        )
    except Exception as e:
        logger.error(
            f"Error abandoning session: {e}",
            extra={
                "request_id": request_id,
                "user_id": current_user.id,
                "session_id": request.session_id,
            },
            exc_info=True
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to abandon session: {str(e)}"
        )


# ============================================================
# REAL-TIME PROGRESS TRACKING
# ============================================================

@router.get("/queries/{query_id}/progress")
async def get_query_progress(
    query_id: str,
    current_user = Depends(get_current_user_or_integration),
    db: Session = Depends(get_db)
):
    """
    Get real-time progress for a refinement query.
    
    This endpoint provides polling-based progress tracking for long-running
    refinement operations. Poll this endpoint every 1-2 seconds to get
    live status updates.
    
    Args:
        query_id: Unique query identifier
        
    Returns:
        ProgressStatus with current stage, progress percentage, and metadata
        
    Example response:
        {
            "query_id": "query_abc123",
            "stage": "generating_suggestions",
            "progress": 0.4,
            "message": "Generating refinement suggestions (turn 2 of 3)...",
            "started_at": "2026-02-11T10:30:00Z",
            "updated_at": "2026-02-11T10:30:08Z",
            "elapsed_seconds": 8.2,
            "turn_number": 2,
            "total_turns": 3,
            "llm_calls_made": 2
        }
    """
    from query_refinement_module.services.progress_tracker import get_progress_tracker
    
    request_id = generate_request_id()
    set_request_id(request_id)
    
    # Verify query exists and belongs to user
    query = get_query(db, query_id)
    if not query:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Query {query_id} not found"
        )
    
    # For queries created via API (with session), verify ownership
    if query.session_id:
        from query_refinement_module.db.crud import get_query_session
        query_session = get_query_session(db, query.session_id)
        if query_session and query_session.user_id != current_user.id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Not authorized to view this query's progress"
            )
    
    # Get progress from tracker
    tracker = get_progress_tracker()
    progress = await tracker.get(query_id)
    
    if not progress:
        # No progress tracked - query might be complete or very old
        # Return a synthetic progress based on query state
        from query_refinement_module.models.progress import ProgressStage, ProgressStatus
        from datetime import datetime
        
        # Determine stage from query state
        if query.refined_query:
            stage = ProgressStage.COMPLETED
            message = "Refinement completed"
            progress_pct = 1.0
        else:
            stage = ProgressStage.WAITING_FOR_USER
            message = "Waiting for user interaction"
            progress_pct = 0.5
        
        progress = ProgressStatus(
            query_id=query_id,
            stage=stage,
            progress=progress_pct,
            message=message,
            started_at=query.created_at,
            updated_at=query.updated_at or query.created_at,
            elapsed_seconds=(datetime.utcnow() - query.created_at).total_seconds()
        )
    
    return progress
