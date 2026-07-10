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
    update_refinement_step_generated_examples,
    update_refinement_step_generated_question,
    update_refinement_step_final_value,
)
from query_refinement_module.api.auth import get_current_user_or_integration
from query_refinement_module.api.config import get_settings
from query_refinement_module.api.dependencies import get_refinement_manager, get_session_manager
from query_refinement_module.api.refinement_schemas import (
    AbandonSessionRequest,
    AbandonSessionResponse,
    CommandHistoryEntry,
    CommandHistoryResponse,
    CommandResponse,
    ConstructSearchRequest,
    ConstructSearchResponse,
    ForwardToQARequest,
    ForwardToQAResponse,
    GetRefinementStatusResponse,
    InspectMessagesResponse,
    NormalizeQueryRequest,
    NormalizeQueryResponse,
    RepresentQueryRequest,
    RepresentQueryResponse,
    ResumeRefinementResponse,
    SearchExpandRequest,
    SearchExpandResponse,
    StartRefinementRequest,
    StartRefinementResponse,
    SubmitAnswerRequest,
    SubmitAnswerResponse,
    SynthesizeQueryRequest,
    SynthesizeQueryResponse,
)
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
from query_refinement_module.schema.response import (
    SearchExpansionInput,
)


router = APIRouter(prefix="/refinement", tags=["Query Refinement Workflow"])


# ==========================================
# Utility Functions
# ==========================================

def _persist_generated_question(
    db,
    db_steps: List[Any],
    next_prompt: Optional[Dict[str, Any]],
) -> None:
    """Compatibility wrapper retained for unit tests that import the route helper directly."""
    if not next_prompt or not db:
        return

    aspect_id = next_prompt.get("aspect_id")
    aspect_name = next_prompt.get("name")
    question = next_prompt.get("question")
    if (not aspect_id and not aspect_name) or not question:
        return

    db_step = next(
        (
            step
            for step in db_steps
            if (aspect_id and getattr(step, "aspect_id", None) == aspect_id)
            or (
                not getattr(step, "aspect_id", None)
                and aspect_name
                and getattr(step, "aspect_name", None) == aspect_name
            )
        ),
        None,
    )
    if not db_step:
        return

    try:
        update_refinement_step_generated_question(db, db_step.id, question)
    except Exception as exc:
        logger.warning("Could not persist generated_question for '%s': %s", aspect_id or aspect_name, exc)

    examples = next_prompt.get("examples") or []
    if examples:
        try:
            update_refinement_step_generated_examples(db, db_step.id, examples)
        except Exception as exc:
            logger.warning("Could not persist generated_examples for '%s': %s", aspect_id or aspect_name, exc)

def _restore_session_from_db_state(session, db_steps: List[Any]) -> None:
    """Restore in-memory session state from persisted DB refinement step rows."""
    workflow_restore_session_from_db_state(session, db_steps)


def _is_session_ready_for_synthesis(session) -> bool:
    """Return True when synthesis can be safely executed for a session."""
    return workflow_is_session_ready_for_synthesis(session)


async def _build_command_response(
    manager,
    command_type: str,
    payload: Dict[str, Any],
    session,
    force_confirmation_needed: bool = False,
    db=None,
    query_id: Optional[int] = None,
    db_steps: Optional[List[Any]] = None,
) -> CommandResponse:
    """Compatibility adapter for unit tests; delegates to the application service."""
    workflow_service = RefinementApiService(
        manager=manager,
        db=db,
        session_manager=None,
        settings_factory=get_settings,
        progress_tracker_factory=get_progress_tracker,
        progress_fn=track_progress,
    )
    response_payload = await workflow_service._build_command_response_payload(
        command_type=command_type,
        payload=payload,
        session=session,
        force_confirmation_needed=force_confirmation_needed,
        query_id=query_id if db is not None else None,
    )
    return CommandResponse(**response_payload)


async def _run_synthesis(
    *,
    manager: QueryRefinementManager,
    session,
    db,
    db_query,
    current_user,
    session_manager: SessionManager,
    query_id: int,
    request_id: str,
    include_expansion: bool = False,
) -> SynthesizeQueryResponse:
    """Compatibility adapter for unit tests; delegates to the application service."""
    workflow_service = RefinementApiService(
        manager=manager,
        db=db,
        session_manager=session_manager,
        settings_factory=get_settings,
        progress_tracker_factory=get_progress_tracker,
        progress_fn=track_progress,
    )
    payload = await workflow_service._run_synthesis(
        session=session,
        db_query=db_query,
        current_user=current_user,
        query_id=query_id,
        request_id=request_id,
        include_expansion=include_expansion,
    )
    return SynthesizeQueryResponse(**payload)


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
    workflow_service = RefinementApiService(
        manager=manager,
        db=None,
        session_manager=None,
        settings_factory=get_settings,
    )
    payload = await workflow_service.expand_workflow(
        statement=request.statement,
        anchor_blocks=request.anchor_blocks,
        search_context=request.search_context,
        semantic_statement=request.semantic_statement,
        keyword_statement=request.keyword_statement,
        keyword_structured=request.keyword_structured,
        search_filters=request.search_filters,
        phrases=request.phrases,
        model=request.model,
        current_user=current_user,
        request_id=request_id_val,
    )
    return SearchExpandResponse(**payload)


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

    workflow_service = RefinementApiService(
        manager=manager,
        db=db,
        session_manager=session_manager,
        settings_factory=get_settings,
    )
    payload = await workflow_service.normalize_workflow(
        query_id=request.query_id,
        current_user=current_user,
        request_id=request_id_val,
    )
    return NormalizeQueryResponse(**payload)


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

    workflow_service = RefinementApiService(
        manager=manager,
        db=None,
        session_manager=None,
        settings_factory=get_settings,
    )
    payload = await workflow_service.represent_workflow(
        statement=request.statement,
        model=request.model,
        current_user=current_user,
        request_id=request_id_val,
    )
    return RepresentQueryResponse(**payload)


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

    workflow_service = RefinementApiService(
        manager=manager,
        db=None,
        session_manager=None,
        settings_factory=get_settings,
    )
    payload = await workflow_service.construct_workflow(
        statement=request.statement,
        concept_graph=request.concept_graph,
        model=request.model,
        current_user=current_user,
        request_id=request_id_val,
    )
    return ConstructSearchResponse(**payload)


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
    workflow_service = RefinementApiService(
        manager=None,
        db=db,
        session_manager=None,
        settings_factory=get_settings,
    )
    payload = await workflow_service.forward_to_qa_workflow(
        query_id=query_id,
        qa_system_url=request.qa_system_url,
        qa_system_auth=request.qa_system_auth,
        timeout_seconds=request.timeout_seconds,
        include_refinement_metadata=request.include_refinement_metadata,
        forward_original_query=request.forward_original_query,
        current_user=current_user,
        request_id=request_id_val,
    )
    return ForwardToQAResponse(**payload)


@router.get("/queries/{query_id}/command-history", response_model=CommandHistoryResponse)
def get_command_history(
    query_id: int,
    limit: int = 100,
    current_user = Depends(get_current_user_or_integration),
    db: Session = Depends(get_db),
):
    """
    Retrieve execution history of all commands for a specific query.

    Returns chronological list of command executions with full context.
    """
    workflow_service = RefinementApiService(
        manager=None,
        db=db,
        session_manager=None,
        settings_factory=get_settings,
    )
    payload = workflow_service.get_command_history_payload(
        query_id=query_id,
        limit=limit,
        current_user=current_user,
    )
    return CommandHistoryResponse(**payload)


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
    workflow_service = RefinementApiService(
        manager=None,
        db=db,
        session_manager=session_manager,
        settings_factory=get_settings,
    )
    payload = workflow_service.inspect_messages_payload(
        query_id=query_id,
        current_user=current_user,
    )
    return InspectMessagesResponse(**payload)


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
    
    Note: AuditLog entries are preserved for research.
    """
    from query_refinement_module.tracing import generate_request_id, set_request_id
    
    # Generate and set request ID for tracing
    request_id = generate_request_id()
    set_request_id(request_id)
    
    workflow_service = RefinementApiService(
        manager=None,
        db=db,
        session_manager=session_manager,
        settings_factory=get_settings,
    )
    payload = await workflow_service.abandon_session_workflow(
        session_id=request.session_id,
        current_user=current_user,
        http_request=http_request,
        request_id=request_id,
    )
    return AbandonSessionResponse(**payload)


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
    request_id = generate_request_id()
    set_request_id(request_id)
    query = get_query(db, query_id)
    if not query:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Query {query_id} not found",
        )

    workflow_service = RefinementApiService(
        manager=None,
        db=db,
        session_manager=None,
        settings_factory=get_settings,
    )
    return await workflow_service.get_query_progress_payload(
        query_id=query_id,
        current_user=current_user,
    )
