"""Transport schemas for the refinement workflow API."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import AnyHttpUrl, BaseModel, ConfigDict, Field, field_validator, model_validator

from query_refinement_module.schema import QueryRefinementResponse, SearchExpansionContext
from query_refinement_module.schema.response import CombinedBlock


class StartRefinementRequest(BaseModel):
    """Request to start a new refinement workflow."""

    original_query: str = Field(
        ...,
        min_length=3,
        max_length=5000,
        description="The query to refine",
    )
    framework_name: str = Field(
        ...,
        min_length=1,
        max_length=128,
        description="Name of the refinement framework to use",
    )
    source: str = Field(
        default="gui",
        description="Request origin channel: gui or api_integration",
    )
    skip_refinement: bool = Field(
        default=False,
        description=(
            "When True, skip all refinement dimensions and go straight to synthesis. "
            "No per-dimension LLM calls are made; only the synthesis LLM call is used."
        ),
    )

    @field_validator("original_query")
    @classmethod
    def query_not_empty(cls, value: str) -> str:
        if not value or not value.strip():
            raise ValueError("Query cannot be empty or just whitespace")
        if len(value.strip()) < 3:
            raise ValueError("Query must be at least 3 characters long")
        return value.strip()

    @field_validator("framework_name")
    @classmethod
    def framework_not_empty(cls, value: str) -> str:
        if not value or not value.strip():
            raise ValueError("Framework name cannot be empty or just whitespace")
        return value.strip()

    @field_validator("source")
    @classmethod
    def validate_source(cls, value: str) -> str:
        normalized = (value or "").strip().lower()
        if normalized not in {"gui", "api_integration"}:
            raise ValueError("source must be one of: gui, api_integration")
        return normalized


class SynthesizeQueryResponse(BaseModel):
    """Full output of the A→B→C synthesis pipeline."""

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
        description="Backward-compatible alias for clarified_query retained for existing frontend clients.",
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


class StartRefinementResponse(BaseModel):
    """Response with session details and initialization summary."""

    session_id: int = Field(..., description="Database session ID")
    query_id: int = Field(..., description="Database query ID")
    summary: Dict[str, Any] = Field(..., description="Initialization analysis summary")
    next_prompt: Optional[Dict[str, Any]] = Field(
        None,
        description=(
            "Next question for the user. Shape: {aspect_id, name, aspect_name, question, description, examples}. "
            "question is plain prose. examples is a list of 0-4 concrete quick-reply strings "
            "that span the clarification space and can be rendered as clickable buttons."
        ),
    )
    ready_for_synthesis: bool = Field(False, description="True if all aspects are complete and ready for synthesis")
    source: str = Field(..., description="Request origin channel")
    synthesis: Optional[SynthesizeQueryResponse] = Field(
        None,
        description=(
            "Populated when skip_refinement=True: full synthesis result embedded "
            "in the start response so no follow-up /synthesize call is needed."
        ),
    )


class SubmitAnswerRequest(BaseModel):
    """Request to submit an answer to a refinement question."""

    answer: str = Field(
        ...,
        min_length=1,
        max_length=2000,
        description="User's answer to the current question or a command (e.g., /status, /back)",
    )
    force: Optional[bool] = Field(
        False,
        description="Force navigation commands that invalidate dependent aspects",
    )

    @field_validator("answer")
    @classmethod
    def answer_not_empty(cls, value: str) -> str:
        if not value or not value.strip():
            raise ValueError("Answer cannot be empty or just whitespace")
        return value.strip()


class SubmitAnswerResponse(BaseModel):
    """Response after processing user's answer."""

    refinement_step_id: int = Field(..., description="ID of the refinement step")
    followup_id: int = Field(..., description="ID of the follow-up entry")
    is_complete: bool = Field(..., description="Whether the aspect is complete")
    next_prompt: Optional[Dict[str, Any]] = Field(
        None,
        description="Next question if follow-up needed. Includes examples list for quick-reply buttons.",
    )
    ready_for_synthesis: bool = Field(False, description="True if all aspects are complete and ready for synthesis")


class CommandResponse(BaseModel):
    """Response when user issues a command instead of answering."""

    command_type: str = Field(..., description="Type of command executed (status, back, skip, etc.)")
    success: bool = Field(..., description="Whether command executed successfully")
    message: str = Field(..., description="Human-readable feedback message")
    next_prompt: Optional[Dict[str, Any]] = Field(
        None,
        description="Next question after command execution. Includes examples list for quick-reply buttons.",
    )
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
        description="Next question for the user. Includes examples list for quick-reply buttons.",
    )
    ready_for_synthesis: bool = Field(False, description="True if all aspects are complete and ready for synthesis")
    aspects: List[Dict[str, Any]] = Field(default_factory=list, description="List of aspect summaries")
    conversation_history: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="Full conversation history for UI restoration",
    )


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


class NormalizeQueryRequest(BaseModel):
    """Agent A normalization request. Requires a completed refinement session."""

    query_id: int = Field(..., gt=0, description="ID of a session ready for synthesis")


class NormalizeQueryResponse(BaseModel):
    """Agent A normalization response."""

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
        description="Per-dimension id -> refined value, assembled deterministically from session state.",
    )
    used_llm: bool = Field(True, description="Always True; Agent A was invoked.")


class RepresentQueryRequest(BaseModel):
    """Agent B semantic representation request."""

    statement: str = Field(
        ...,
        min_length=3,
        description="Clarified research statement from Agent A (POST /normalize -> clarified_query).",
    )
    model: Optional[str] = Field(None, description="Optional LLM model override")

    @field_validator("statement")
    @classmethod
    def _not_empty(cls, value: str) -> str:
        if not value or not value.strip():
            raise ValueError("statement cannot be empty")
        return value.strip()


class RepresentQueryResponse(BaseModel):
    """Agent B semantic representation response."""

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
    """Agent C search construction request."""

    statement: str = Field(
        ...,
        min_length=3,
        description="Clarified research statement from Agent A (POST /normalize -> clarified_query).",
    )
    concept_graph: Dict[str, Any] = Field(
        default_factory=dict,
        description="Concept graph from Agent B (POST /represent -> concept_graph).",
    )
    model: Optional[str] = Field(None, description="Optional LLM model override")

    @field_validator("statement")
    @classmethod
    def _not_empty(cls, value: str) -> str:
        if not value or not value.strip():
            raise ValueError("statement cannot be empty")
        return value.strip()


class ConstructSearchResponse(BaseModel):
    """Agent C search construction response."""

    keyword: Dict[str, Any] = Field(
        ...,
        description=(
            "Keyword query artifacts: structured (Boolean), phrases, terms (required/optional/excluded), "
            "combined_blocks (primary RAG artifact - AND-blocks with free_text and controlled_vocabulary)."
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


class SearchExpandRequest(BaseModel):
    """Agent D search expansion request."""

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "statement": "How to improve mental health outcomes among children in Qoloji camp, Ethiopia.",
                "anchor_blocks": [
                    {
                        "role": "topic_or_condition",
                        "free_text": ["mental health", "psychological wellbeing", "MHPSS"],
                        "controlled_vocabulary": {"MeSH": ["Mental Health"]},
                    }
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
                "keyword_structured": "(mental health OR psychological wellbeing OR MHPSS) AND (children under five OR young children OR U5)",
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
    statement: str = Field(..., description="Exact anchor query (unchanged).")
    anchor_blocks: List[CombinedBlock] = Field(
        ...,
        description="Agent C combined_blocks from POST /construct or POST /synthesize.",
    )
    search_context: Optional[SearchExpansionContext] = Field(
        None,
        description="Optional retrieval context, especially Agent B concept_graph.",
    )
    semantic_statement: Optional[str] = Field(None, description="POST /represent -> semantic_statement.")
    keyword_statement: Optional[str] = Field(None, description="POST /represent -> keyword_statement.")
    keyword_structured: Optional[str] = Field(None, description="POST /construct -> keyword.structured.")
    search_filters: Optional[Dict[str, Any]] = Field(None, description="POST /construct -> search_filters.")
    phrases: Optional[List[str]] = Field(None, description="POST /construct -> keyword.phrases.")
    model: Optional[str] = Field(None, description="Optional LLM model override")

    @field_validator("statement")
    @classmethod
    def validate_statement(cls, value: str) -> str:
        if not value or not value.strip():
            raise ValueError("statement cannot be empty or just whitespace")
        return value.strip()


class SearchExpandResponse(BaseModel):
    """Agent D search expansion response."""

    levels: List[Dict[str, Any]] = Field(
        ...,
        description=(
            "Ordered expansion levels (Level 0 first). Each entry: {level, label, query, semantic_query, "
            "keyword_query, boolean_query, controlled_vocabulary, broadened_aspect, broadened_value, rationale, "
            "cochrane_compliant}."
        ),
    )
    geography_broadening_strategy: str = Field(default="none", description="Broadening strategy used for geography when present.")
    recommended_starting_level: int = Field(default=1, description="Recommended level to run first following Cochrane-style escalation logic.")
    recommendation_rationale: str = Field(default="", description="Why the recommended_starting_level is the best initial retrieval level.")
    search_filters: Optional[Dict[str, Any]] = Field(default=None, description="Agent C search filters that apply across all levels.")
    phrases: Optional[List[str]] = Field(default=None, description="Agent C key phrases that apply across all levels.")
    metadata: Optional[Dict[str, Any]] = Field(None, description="Generation metadata: status, generated_level_count, used_llm, total_tokens.")


class ForwardToQARequest(BaseModel):
    """Request to forward refined query to external QA system."""

    qa_system_url: AnyHttpUrl = Field(..., description="URL of the external question-answering system")
    qa_system_auth: Optional[Dict[str, str]] = Field(
        None,
        description="Authentication headers for the QA system (e.g., {'Authorization': 'Bearer token'})",
    )
    timeout_seconds: int = Field(default=30, ge=5, le=120, description="Request timeout in seconds")
    include_refinement_metadata: bool = Field(default=True, description="Include refinement metadata in the request to QA system")
    forward_original_query: bool = Field(default=False, description="Also include the original query alongside the refined query")

    @field_validator("qa_system_url")
    @classmethod
    def _no_private_url(cls, value: AnyHttpUrl) -> AnyHttpUrl:
        import ipaddress

        host = value.host or ""
        if host.lower() in {"localhost", "0.0.0.0"}:
            raise ValueError("Internal/loopback hostnames are not permitted as qa_system_url")
        try:
            addr = ipaddress.ip_address(host)
            if addr.is_private or addr.is_loopback or addr.is_link_local or addr.is_reserved:
                raise ValueError("Private or internal IP addresses are not permitted as qa_system_url")
        except ValueError as exc:
            if "not permitted" in str(exc):
                raise
        return value

    @field_validator("qa_system_auth")
    @classmethod
    def _safe_auth_headers(cls, value: Optional[Dict[str, str]]) -> Optional[Dict[str, str]]:
        if not value:
            return value
        forbidden = frozenset({
            "host", "content-length", "transfer-encoding",
            "connection", "te", "trailer", "upgrade",
        })
        for key in value:
            if key.lower() in forbidden:
                raise ValueError(f"Header '{key}' is not permitted in qa_system_auth")
        return value


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


class InspectMessagesResponse(BaseModel):
    """Response showing the actual messages sent to the LLM."""

    query_id: int
    current_dimension: Optional[str] = None
    message_count: int
    messages: List[Dict[str, Any]]


class AbandonSessionRequest(BaseModel):
    """Request to abandon/delete a session and all its data."""

    session_id: int = Field(..., gt=0, description="ID of the session to abandon")


class AbandonSessionResponse(BaseModel):
    """Response with deletion details."""

    status: str = Field(..., description="Status of the operation")
    session_id: int = Field(..., description="ID of the abandoned session")
    deletion_counts: Dict[str, int] = Field(..., description="Count of deleted records by type")
    message: str = Field(..., description="Human-readable message")


__all__ = [
    "AbandonSessionRequest",
    "AbandonSessionResponse",
    "CommandHistoryEntry",
    "CommandHistoryResponse",
    "CommandResponse",
    "ConstructSearchRequest",
    "ConstructSearchResponse",
    "ForwardToQARequest",
    "ForwardToQAResponse",
    "GetRefinementStatusResponse",
    "InspectMessagesResponse",
    "NormalizeQueryRequest",
    "NormalizeQueryResponse",
    "RepresentQueryRequest",
    "RepresentQueryResponse",
    "ResumeRefinementResponse",
    "SearchExpandRequest",
    "SearchExpandResponse",
    "StartRefinementRequest",
    "StartRefinementResponse",
    "SubmitAnswerRequest",
    "SubmitAnswerResponse",
    "SynthesizeQueryRequest",
    "SynthesizeQueryResponse",
]
