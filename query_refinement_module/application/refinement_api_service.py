"""Application service for the refinement workflow HTTP entry points."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any, Awaitable, Callable, Dict, Optional

from query_refinement_module.api.exceptions import (
    FrameworkNotFoundError,
    QueryRefinementException,
    ResourceNotFoundError,
    UnauthorizedError,
)
from query_refinement_module.audit import audit_service
from query_refinement_module.core import UserCommand, is_user_command, parse_user_command
from query_refinement_module.core import QueryRefinementManager
from query_refinement_module.db.crud import (
    abandon_query_session,
    create_followup,
    create_query,
    create_query_session,
    create_refinement_step,
    delete_refinement_steps_by_aspects,
    get_query,
    get_query_session,
    get_query_refinement_steps,
    mark_refinement_step_skipped,
    mark_refinement_step_user_ended_early,
    reset_refinement_step,
    save_query_refinement_response,
    update_refinement_step_final_value,
    user_has_framework_access,
)
from query_refinement_module.db.models.audit_log import AuditEventType
from query_refinement_module.models.progress import ProgressStage, ProgressStatus
from query_refinement_module.schema import DimensionEvaluationResponse
from query_refinement_module.schema.prompt_builder import PromptBuilder
from query_refinement_module.schema.response import SearchExpansionInput
from query_refinement_module.schema.registry import get_framework
from query_refinement_module.settings import LLMSettings
from query_refinement_module.services.progress_tracker import get_progress_tracker, track_progress

from .refinement_workflow import (
    build_next_prompt,
    build_status_payload,
    find_db_step_for_aspect,
    get_active_prompt,
    is_session_ready_for_synthesis,
    persist_generated_question,
    restore_session_from_db_state,
)


logger = logging.getLogger(__name__)


class RefinementApiService:
    """Shared orchestration service for the refinement API workflow routes."""

    def __init__(
        self,
        *,
        manager: QueryRefinementManager,
        db,
        session_manager,
        settings_factory: Callable[[], Any],
        progress_tracker_factory: Callable[[], Any] = get_progress_tracker,
        progress_fn: Callable[..., Awaitable[Any]] = track_progress,
    ) -> None:
        self._manager = manager
        self._db = db
        self._session_manager = session_manager
        self._settings_factory = settings_factory
        self._progress_tracker_factory = progress_tracker_factory
        self._track_progress = progress_fn

    def _get_framework_or_raise(self, framework_name: str):
        try:
            return get_framework(framework_name)
        except Exception as exc:
            raise FrameworkNotFoundError(framework_name) from exc

    def _require_start_permissions(self, *, current_user, framework_name: str) -> None:
        settings = self._settings_factory()
        if settings.enforce_workflow_limit and not current_user.is_superuser and current_user.has_completed_workflow:
            raise UnauthorizedError(
                "You have already completed one refinement workflow. "
                "For evaluation purposes, only one workflow per participant is allowed. "
                "Thank you for your participation!"
            )

        if not current_user.is_superuser and not user_has_framework_access(self._db, current_user.id, framework_name):
            raise UnauthorizedError(
                f"You are not authorized to use framework '{framework_name}'"
            )

    async def _initialize_session(self, *, original_query: str, framework):
        try:
            return await asyncio.to_thread(
                self._manager.initialize_sequential,
                original_query,
                framework,
            )
        except ConnectionError as exc:
            raise QueryRefinementException(
                f"Unable to connect to LLM service: {str(exc)}",
                status_code=503,
            ) from exc
        except TimeoutError as exc:
            raise QueryRefinementException(
                f"LLM service request timed out: {str(exc)}",
                status_code=504,
            ) from exc
        except Exception as exc:
            logger.error("Error initializing refinement session: %s", exc, exc_info=True)
            error_str = str(exc).lower()
            if "credit balance" in error_str or "insufficient" in error_str:
                raise QueryRefinementException(
                    "LLM service credits exhausted. Please configure valid API credentials.",
                    status_code=402,
                ) from exc
            if "api key" in error_str or "authentication" in error_str:
                raise QueryRefinementException(
                    "LLM service authentication error. Please check API configuration.",
                    status_code=500,
                ) from exc
            if "rate limit" in error_str:
                raise QueryRefinementException(
                    "LLM service rate limit exceeded. Please try again later.",
                    status_code=429,
                ) from exc
            raise QueryRefinementException(
                "Failed to initialize refinement. LLM service may be unavailable.",
                status_code=500,
            ) from exc

    def _get_query_for_user(self, *, query_id: int, current_user):
        db_query = get_query(self._db, query_id)
        if not db_query:
            raise ResourceNotFoundError("Query", query_id)
        if db_query.session.user_id != current_user.id:
            raise UnauthorizedError("Access denied")
        return db_query

    async def load_or_reconstruct_session(self, *, query_id: int, db_query, framework):
        session = self._session_manager.load_session(query_id, framework)
        if session:
            return session

        logger.warning(
            "Session not found in Redis for query_id=%d, reconstructing from database",
            query_id,
        )
        session = await asyncio.to_thread(
            self._manager.initialize_sequential,
            db_query.original_query,
            framework,
        )
        db_steps = get_query_refinement_steps(self._db, query_id)
        restore_session_from_db_state(session, db_steps)
        return session

    async def start_workflow(
        self,
        *,
        original_query: str,
        framework_name: str,
        source: str,
        skip_refinement: bool,
        current_user,
        request_id: str,
    ) -> Dict[str, Any]:
        start_time = time.time()
        self._require_start_permissions(current_user=current_user, framework_name=framework_name)

        logger.info(
            "API: Starting refinement workflow",
            extra={
                "request_id": request_id,
                "user_id": current_user.id,
                "framework_name": framework_name,
                "query_length": len(original_query),
                "source": source,
            },
        )

        framework = self._get_framework_or_raise(framework_name)
        session = await self._initialize_session(original_query=original_query, framework=framework)

        db_session = create_query_session(self._db, user_id=current_user.id, framework_name=framework_name)
        db_query = create_query(self._db, session_id=db_session.id, original_query=original_query)

        tracker = self._progress_tracker_factory()
        try:
            await tracker.create(
                query_id=str(db_query.id),
                initial_stage=ProgressStage.EXTRACTING_ASPECTS,
                initial_message=f"Analyzing query structure with {framework_name} framework...",
            )
        except Exception as exc:  # pragma: no cover - non-fatal progress path
            logger.error("Failed to create progress tracking: %s", exc, exc_info=True)

        for step in session.steps:
            create_refinement_step(
                self._db,
                query_id=db_query.id,
                aspect_name=step.refinement_aspect.name,
                aspect_id=step.refinement_aspect.id,
            )

        if skip_refinement:
            for step in session.steps:
                step.is_complete = True
                step.was_skipped = True
            session.synthesis_requested = True

            db_steps = get_query_refinement_steps(self._db, db_query.id)
            for db_step in db_steps:
                mark_refinement_step_skipped(self._db, db_step.id)

            self._session_manager.save_session(db_query.id, session)
            await self._track_progress(
                query_id=str(db_query.id),
                stage=ProgressStage.SUGGESTIONS_READY,
                message="All refinements skipped, proceeding to synthesis",
            )

            logger.info(
                "API: Refinement workflow started (skip_refinement=True) – running synthesis inline",
                extra={
                    "request_id": request_id,
                    "user_id": current_user.id,
                    "session_id": db_session.id,
                    "query_id": db_query.id,
                    "total_aspects": len(session.steps),
                },
            )

            synthesis_response = await self._run_synthesis(
                session=session,
                db_query=db_query,
                current_user=current_user,
                query_id=db_query.id,
                request_id=request_id,
            )

            return {
                "session_id": db_session.id,
                "query_id": db_query.id,
                "summary": {
                    "total_aspects": len(session.steps),
                    "aspects_needing_refinement": 0,
                    "aspects_clear": len(session.steps),
                    "is_complete": True,
                },
                "next_prompt": None,
                "ready_for_synthesis": True,
                "source": source,
                "synthesis": synthesis_response,
            }

        await self._track_progress(
            query_id=str(db_query.id),
            stage=ProgressStage.ASPECTS_EXTRACTED,
            message=f"Identified {len(session.steps)} aspects to refine",
            aspects_count=len(session.steps),
            details={"framework": framework_name},
        )
        await self._track_progress(
            query_id=str(db_query.id),
            stage=ProgressStage.GENERATING_SUGGESTIONS,
            message="Generating refinement suggestions...",
            turn_number=1,
            total_turns=len(session.steps),
        )

        summary = {
            "total_aspects": len(session.steps),
            "aspects_needing_refinement": len([step for step in session.steps if not step.is_complete]),
            "aspects_clear": len([step for step in session.steps if step.is_complete]),
            "is_complete": session.is_complete(),
        }

        db_steps = get_query_refinement_steps(self._db, db_query.id)
        next_prompt = await build_next_prompt(self._manager, session, db=self._db, db_steps=db_steps)
        persist_generated_question(self._db, db_steps, next_prompt)
        ready_for_synthesis = next_prompt is None and session.is_complete()

        if next_prompt:
            suggestions_count = len([step for step in session.steps if not step.is_complete])
            await self._track_progress(
                query_id=str(db_query.id),
                stage=ProgressStage.SUGGESTIONS_READY,
                message="Refinement suggestions ready",
                suggestions_count=suggestions_count,
            )
            await self._track_progress(
                query_id=str(db_query.id),
                stage=ProgressStage.WAITING_FOR_USER,
                message=f"Waiting for your input on '{next_prompt.get('name', 'aspect')}'",
                details={"current_aspect": next_prompt.get("name")},
            )
        elif ready_for_synthesis:
            await self._track_progress(
                query_id=str(db_query.id),
                stage=ProgressStage.SUGGESTIONS_READY,
                message="All aspects refined, ready for synthesis",
            )

        self._session_manager.save_session(db_query.id, session)

        duration_ms = (time.time() - start_time) * 1000
        logger.info(
            "API: Refinement workflow started successfully",
            extra={
                "request_id": request_id,
                "user_id": current_user.id,
                "session_id": db_session.id,
                "query_id": db_query.id,
                "total_aspects": summary["total_aspects"],
                "ready_for_synthesis": ready_for_synthesis,
                "duration_ms": round(duration_ms, 2),
            },
        )

        return {
            "session_id": db_session.id,
            "query_id": db_query.id,
            "summary": summary,
            "next_prompt": next_prompt,
            "ready_for_synthesis": ready_for_synthesis,
            "source": source,
        }

    async def synthesize_workflow(
        self,
        *,
        query_id: int,
        include_expansion: bool,
        current_user,
        request_id: str,
    ) -> Dict[str, Any]:
        db_query = self._get_query_for_user(query_id=query_id, current_user=current_user)

        framework_name = db_query.session.framework_name
        if not framework_name:
            raise QueryRefinementException("Framework name not found for session", status_code=400)
        framework = self._get_framework_or_raise(framework_name)

        try:
            async with self._session_manager.session_lock(query_id):
                session = self._session_manager.load_session(query_id, framework)
                if not session:
                    logger.warning(
                        "Session not found in Redis for query_id=%d, reconstructing from database",
                        query_id,
                    )
                    session = await asyncio.to_thread(
                        self._manager.initialize_sequential,
                        db_query.original_query,
                        framework,
                    )
                    db_steps = get_query_refinement_steps(self._db, query_id)
                    restore_session_from_db_state(session, db_steps)

                if not is_session_ready_for_synthesis(session):
                    raise QueryRefinementException(
                        "Query is not ready for synthesis. Complete all dimensions or use /submit first.",
                        status_code=409,
                    )

                return await self._run_synthesis(
                    session=session,
                    db_query=db_query,
                    current_user=current_user,
                    query_id=query_id,
                    request_id=request_id,
                    include_expansion=include_expansion,
                )
        except RuntimeError as exc:
            logger.warning("Could not acquire session lock for query %d during synthesis: %s", query_id, exc)
            raise QueryRefinementException(
                "Session is temporarily locked by another request. Please retry in a moment.",
                status_code=503,
            ) from exc

    async def normalize_workflow(
        self,
        *,
        query_id: int,
        current_user,
        request_id: str,
    ) -> Dict[str, Any]:
        db_query = self._get_query_for_user(query_id=query_id, current_user=current_user)

        framework_name = db_query.session.framework_name
        if not framework_name:
            raise QueryRefinementException("Framework name not found for session", status_code=400)
        framework = self._get_framework_or_raise(framework_name)

        try:
            async with self._session_manager.session_lock(query_id):
                session = await self.load_or_reconstruct_session(
                    query_id=query_id,
                    db_query=db_query,
                    framework=framework,
                )
                if not is_session_ready_for_synthesis(session):
                    raise QueryRefinementException(
                        "Query is not ready for normalization. Complete all dimensions or use /submit first.",
                        status_code=409,
                    )

                norm, _ = await self._manager._run_normalization(session)
        except RuntimeError as exc:
            logger.warning("Could not acquire session lock for query %d during normalization: %s", query_id, exc)
            raise QueryRefinementException(
                "Session is temporarily locked by another request. Please retry in a moment.",
                status_code=503,
            ) from exc

        logger.info(
            "API: Agent A completed",
            extra={
                "request_id": request_id,
                "user_id": current_user.id,
                "query_id": query_id,
                "clarified_query_length": len(norm.clarified_query),
            },
        )
        return {
            "query_id": query_id,
            "clarified_query": norm.clarified_query,
            "dimensions_specifications": norm.dimensions_specifications,
            "used_llm": True,
        }

    async def represent_workflow(
        self,
        *,
        statement: str,
        model: Optional[str],
        current_user,
        request_id: str,
    ) -> Dict[str, Any]:
        logger.info(
            "API: Running Agent B (Semantic Representation)",
            extra={
                "request_id": request_id,
                "user_id": current_user.id,
                "statement_length": len(statement),
            },
        )

        try:
            sem, _ = await self._manager._run_semantic_representation(
                statement,
                model=model,
            )
        except Exception as exc:
            logger.exception("API: Agent B failed", extra={"request_id": request_id})
            raise QueryRefinementException(
                f"Semantic representation failed: {exc}",
                status_code=500,
            ) from exc

        concept_graph_dict = {
            key: (value.model_dump() if hasattr(value, "model_dump") else value)
            for key, value in sem.concept_graph.items()
        }
        return {
            "semantic_statement": sem.semantic_statement,
            "keyword_statement": sem.keyword_statement,
            "concept_graph": concept_graph_dict,
            "used_llm": True,
        }

    async def construct_workflow(
        self,
        *,
        statement: str,
        concept_graph: Dict[str, Any],
        model: Optional[str],
        current_user,
        request_id: str,
    ) -> Dict[str, Any]:
        logger.info(
            "API: Running Agent C (Search Construction)",
            extra={
                "request_id": request_id,
                "user_id": current_user.id,
                "statement_length": len(statement),
                "concept_graph_size": len(concept_graph),
            },
        )

        try:
            construction, _ = await self._manager._run_search_construction(
                statement=statement,
                concept_graph=concept_graph,
                model=model,
            )
        except Exception as exc:
            logger.exception("API: Agent C failed", extra={"request_id": request_id})
            raise QueryRefinementException(
                f"Search construction failed: {exc}",
                status_code=500,
            ) from exc

        keyword_dict = construction.keyword.model_dump() if hasattr(construction.keyword, "model_dump") else construction.keyword
        filters_dict = construction.search_filters.model_dump() if hasattr(construction.search_filters, "model_dump") else construction.search_filters
        return {
            "keyword": keyword_dict,
            "search_filters": filters_dict,
            "used_llm": True,
        }

    async def expand_workflow(
        self,
        *,
        statement: str,
        anchor_blocks,
        search_context,
        semantic_statement: Optional[str],
        keyword_statement: Optional[str],
        keyword_structured: Optional[str],
        search_filters,
        phrases,
        model: Optional[str],
        current_user,
        request_id: str,
    ) -> Dict[str, Any]:
        start_time = time.time()
        concept_graph = {}
        if search_context and search_context.concept_graph:
            concept_graph = search_context.concept_graph

        logger.info(
            "API: Generating search expansion levels",
            extra={
                "request_id": request_id,
                "user_id": current_user.id,
                "model_override": model,
                "statement_length": len(statement),
                "anchor_block_count": len(anchor_blocks),
            },
        )

        try:
            expansion_input = SearchExpansionInput(
                clarified_query=statement,
                anchor_blocks=anchor_blocks,
                concept_graph=concept_graph,
                semantic_statement=semantic_statement or "",
                keyword_statement=keyword_statement or "",
                keyword_structured=keyword_structured or "",
                search_filters=search_filters,
                phrases=phrases or [],
            )
            result, metadata = await self._manager.generate_search_expansion_levels(
                search_input=expansion_input,
                model=model,
            )
        except Exception as exc:
            logger.exception(
                "API: Search expansion generation failed unexpectedly",
                extra={"request_id": request_id, "error": str(exc)},
            )
            raise QueryRefinementException(
                f"Failed to generate search expansion levels: {str(exc)}",
                status_code=500,
            ) from exc

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

        duration_ms = (time.time() - start_time) * 1000
        logger.info(
            "API: Search expansion completed",
            extra={
                "request_id": request_id,
                "duration_ms": round(duration_ms, 2),
                "returned_level_count": len(levels_payload),
                "generated_level_count": metadata.get("generated_level_count", 0),
                "status": metadata.get("status"),
            },
        )

        return {
            "levels": levels_payload,
            "geography_broadening_strategy": result.geography_broadening_strategy,
            "recommended_starting_level": result.recommended_starting_level,
            "recommendation_rationale": result.recommendation_rationale,
            "search_filters": (
                result.search_filters.model_dump()
                if hasattr(result.search_filters, "model_dump")
                else result.search_filters
            ) if result.search_filters else None,
            "phrases": result.phrases or None,
            "metadata": metadata,
        }

    async def forward_to_qa_workflow(
        self,
        *,
        query_id: int,
        qa_system_url,
        qa_system_auth,
        timeout_seconds: int,
        include_refinement_metadata: bool,
        forward_original_query: bool,
        current_user,
        request_id: str,
    ) -> Dict[str, Any]:
        request_logger = logger
        start_time = time.time()
        db_query = self._get_query_for_user(query_id=query_id, current_user=current_user)
        if not db_query.refined_query:
            raise QueryRefinementException(
                "Query has not been synthesized yet. Complete refinement and synthesis first.",
                status_code=400,
            )

        qa_payload = {"refined_query": db_query.refined_query}
        if forward_original_query:
            qa_payload["original_query"] = db_query.original_query

        if include_refinement_metadata:
            refinement_steps = get_query_refinement_steps(self._db, query_id=query_id)
            qa_payload["refinement_metadata"] = {
                "framework": db_query.session.framework_name if hasattr(db_query.session, "framework_name") else None,
                "total_steps": len(refinement_steps),
                "dimensions_refined": [step.aspect_id for step in refinement_steps if step.is_refined],
                "query_id": query_id,
            }

        import httpx

        qa_start_time = time.time()
        try:
            async with httpx.AsyncClient(timeout=timeout_seconds) as client:
                headers = qa_system_auth or {}
                headers["Content-Type"] = "application/json"
                headers["X-Request-ID"] = request_id
                response = await client.post(
                    qa_system_url,
                    json=qa_payload,
                    headers=headers,
                )
                qa_response_time_ms = int((time.time() - qa_start_time) * 1000)
                try:
                    qa_response_data = response.json()
                except Exception:
                    qa_response_data = {"response": response.text}
        except httpx.TimeoutException as exc:
            raise QueryRefinementException(
                f"QA system did not respond within {timeout_seconds} seconds",
                status_code=504,
            ) from exc
        except httpx.RequestError as exc:
            raise QueryRefinementException(
                f"Failed to connect to QA system: {str(exc)}",
                status_code=502,
            ) from exc
        except Exception as exc:
            request_logger.error(
                "Unexpected error during QA forwarding: %s",
                exc,
                extra={"request_id": request_id, "query_id": query_id},
                exc_info=True,
            )
            raise QueryRefinementException(
                f"Failed to forward query to QA system: {str(exc)}",
                status_code=500,
            ) from exc

        total_duration_ms = int((time.time() - start_time) * 1000)
        request_logger.info(
            "API: Forward to QA system completed",
            extra={
                "request_id": request_id,
                "user_id": current_user.id,
                "query_id": query_id,
                "qa_status_code": response.status_code,
                "qa_response_time_ms": qa_response_time_ms,
                "total_duration_ms": total_duration_ms,
            },
        )
        return {
            "query_id": query_id,
            "refined_query": db_query.refined_query,
            "original_query": db_query.original_query if forward_original_query else None,
            "qa_system_url": qa_system_url,
            "qa_system_response": qa_response_data,
            "qa_system_status_code": response.status_code,
            "response_time_ms": qa_response_time_ms,
            "refinement_metadata": qa_payload.get("refinement_metadata") if include_refinement_metadata else None,
        }

    def get_command_history_payload(self, *, query_id: int, limit: int, current_user) -> Dict[str, Any]:
        from query_refinement_module.db.models.audit_log import AuditLog

        query = self._get_query_for_user(query_id=query_id, current_user=current_user)
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
        audit_logs = self._db.query(AuditLog).filter(
            AuditLog.resource_type == "query",
            AuditLog.resource_id == str(query.id),
            AuditLog.event_type.in_(command_event_types),
        ).order_by(AuditLog.timestamp.desc()).limit(limit).all()

        commands = []
        for log in reversed(audit_logs):
            details = log.details or {}
            commands.append(
                {
                    "timestamp": log.timestamp.isoformat(),
                    "event_id": log.id,
                    "command": details.get("command", "unknown"),
                    "command_input": details.get("command_input", ""),
                    "argument": details.get("argument"),
                    "active_dimension": details.get("active_dimension"),
                    "success": details.get("success", False),
                    "status": log.status or "unknown",
                    "force_requested": details.get("force_requested", False),
                    "force_confirmation_needed": details.get("force_confirmation_needed", False),
                    "cleared_aspects": details.get("cleared_aspects"),
                    "invalidated_aspects": details.get("invalidated_aspects"),
                    "target_aspect": details.get("target_aspect"),
                    "deleted_db_records": details.get("deleted_db_records"),
                    "username": log.username or "unknown",
                    "request_id": log.request_id,
                }
            )

        return {
            "query_id": query_id,
            "total_commands": len(commands),
            "commands": commands,
        }

    def inspect_messages_payload(self, *, query_id: int, current_user) -> Dict[str, Any]:
        query = get_query(self._db, query_id)
        if not query or query.session.user_id != current_user.id:
            raise ResourceNotFoundError("Query", query_id)

        session = self._session_manager.load_session(query_id)
        if not session:
            raise ResourceNotFoundError("Session", query_id)

        active_step = session.get_active_step()
        if not active_step:
            raise QueryRefinementException("No active dimension to inspect", status_code=400)

        llm_settings = LLMSettings.from_env(require_model=False)
        dependency_context = session.get_dependency_context(active_step.refinement_aspect.id)
        messages = active_step.get_messages(
            query=session.original_query,
            dependency_context=dependency_context,
            terminal_reinforcement_threshold=llm_settings.terminal_reinforcement_threshold,
        )
        return {
            "query_id": query_id,
            "current_dimension": active_step.refinement_aspect.id,
            "message_count": len(messages),
            "messages": messages,
        }

    async def abandon_session_workflow(
        self,
        *,
        session_id: int,
        current_user,
        http_request,
        request_id: str,
    ) -> Dict[str, Any]:
        start_time = time.time()
        logger.info(
            "API: Abandoning session",
            extra={"request_id": request_id, "user_id": current_user.id, "session_id": session_id},
        )
        try:
            result = abandon_query_session(self._db, session_id, current_user.id)
        except ValueError as exc:
            raise ResourceNotFoundError("Session", session_id) from exc
        except Exception as exc:
            logger.error(
                "Error abandoning session: %s",
                exc,
                extra={"request_id": request_id, "user_id": current_user.id, "session_id": session_id},
                exc_info=True,
            )
            raise QueryRefinementException(f"Failed to abandon session: {str(exc)}", status_code=500) from exc

        try:
            audit_service.log_from_request(
                db=self._db,
                request=http_request,
                event_type=AuditEventType.SESSION_ABANDONED,
                user=current_user,
                resource_type="session",
                resource_id=str(session_id),
                action=f"Abandoned session {session_id}",
                status="success",
                details={"deletion_counts": result["deletion_counts"], "request_id": request_id},
            )
        except Exception as exc:
            logger.error("Failed to log audit event: %s", exc, exc_info=True)

        duration_ms = (time.time() - start_time) * 1000
        logger.info(
            "API: Session abandoned successfully",
            extra={
                "request_id": request_id,
                "user_id": current_user.id,
                "session_id": session_id,
                "deletion_counts": result["deletion_counts"],
                "duration_ms": round(duration_ms, 2),
            },
        )
        return {
            "status": "success",
            "session_id": session_id,
            "deletion_counts": result["deletion_counts"],
            "message": (
                f"Session {session_id} abandoned successfully. "
                f"Deleted {result['deletion_counts']['queries']} queries, "
                f"{result['deletion_counts']['refinement_steps']} refinement steps."
            ),
        }

    async def get_query_progress_payload(self, *, query_id: str, current_user) -> ProgressStatus:
        query = get_query(self._db, query_id)
        if not query:
            raise ResourceNotFoundError("Query", query_id)

        if query.session_id:
            query_session = get_query_session(self._db, query.session_id)
            if query_session and query_session.user_id != current_user.id:
                raise UnauthorizedError("Not authorized to view this query's progress")

        tracker = self._progress_tracker_factory()
        progress = await tracker.get(query_id)
        if progress:
            return progress

        from datetime import datetime

        if query.refined_query:
            stage = ProgressStage.COMPLETED
            message = "Refinement completed"
            progress_pct = 1.0
        else:
            stage = ProgressStage.WAITING_FOR_USER
            message = "Waiting for user interaction"
            progress_pct = 0.5

        return ProgressStatus(
            query_id=query_id,
            stage=stage,
            progress=progress_pct,
            message=message,
            started_at=query.created_at,
            updated_at=query.updated_at or query.created_at,
            elapsed_seconds=(datetime.utcnow() - query.created_at).total_seconds(),
        )

    async def get_status_payload(self, *, query_id: int, current_user, request_id: str) -> Dict[str, Any]:
        start_time = time.time()
        logger.info(
            "API: Getting refinement status",
            extra={"request_id": request_id, "user_id": current_user.id, "query_id": query_id},
        )

        db_query = self._get_query_for_user(query_id=query_id, current_user=current_user)
        if db_query.refined_query and db_query.refined_query.strip():
            logger.info("Query %d already synthesized, returning completion status", query_id)
            return {
                "query_id": query_id,
                "original_query": db_query.original_query,
                "refined_query": db_query.refined_query,
                "is_complete": True,
                "current_aspect": None,
                "aspects_summary": {},
                "next_prompt": None,
                "ready_for_synthesis": True,
                "aspects": [],
                "conversation_history": [],
            }

        framework_name = db_query.session.framework_name
        if not framework_name:
            raise QueryRefinementException("Framework name not found for session", status_code=400)

        framework = self._get_framework_or_raise(framework_name)
        session = await self.load_or_reconstruct_session(query_id=query_id, db_query=db_query, framework=framework)
        summary = self._manager.get_initialization_summary(session)
        payload = build_status_payload(query_id, db_query, session, summary)

        duration_ms = (time.time() - start_time) * 1000
        logger.info(
            "API: Refinement status retrieved",
            extra={
                "request_id": request_id,
                "user_id": current_user.id,
                "query_id": query_id,
                "is_complete": session.is_complete(),
                "current_aspect": payload["current_aspect"],
                "ready_for_synthesis": payload["ready_for_synthesis"],
                "duration_ms": round(duration_ms, 2),
            },
        )
        return payload

    async def resume_workflow(self, *, query_id: int, current_user, request_id: str) -> Dict[str, Any]:
        start_time = time.time()
        db_query = self._get_query_for_user(query_id=query_id, current_user=current_user)

        framework_name = db_query.session.framework_name
        if not framework_name:
            raise QueryRefinementException("Framework name not found for session", status_code=400)
        framework = self._get_framework_or_raise(framework_name)

        try:
            async with self._session_manager.session_lock(query_id):
                session = self._session_manager.load_session(query_id, framework)
                if not session:
                    logger.warning(
                        "Session not found in Redis for query_id=%d, reconstructing from database",
                        query_id,
                    )
                    session = await asyncio.to_thread(
                        self._manager.initialize_sequential,
                        db_query.original_query,
                        framework,
                    )
                    db_steps = get_query_refinement_steps(self._db, query_id)
                    restore_session_from_db_state(session, db_steps)
                else:
                    db_steps = get_query_refinement_steps(self._db, query_id)

                if not session.synthesis_requested and get_active_prompt(session) is None:
                    next_prompt = await build_next_prompt(self._manager, session, db=self._db, db_steps=db_steps)
                    persist_generated_question(self._db, db_steps, next_prompt)

                self._session_manager.save_session(query_id, session)
        except RuntimeError as exc:
            logger.warning("Could not acquire session lock for query %d during resume: %s", query_id, exc)
            raise QueryRefinementException(
                "Session is temporarily locked by another request. Please retry in a moment.",
                status_code=503,
            ) from exc

        summary = self._manager.get_initialization_summary(session)
        payload = build_status_payload(query_id, db_query, session, summary)
        duration_ms = (time.time() - start_time) * 1000
        logger.info(
            "API: Refinement session resumed",
            extra={
                "request_id": request_id,
                "user_id": current_user.id,
                "query_id": query_id,
                "current_aspect": payload["current_aspect"],
                "ready_for_synthesis": payload["ready_for_synthesis"],
                "duration_ms": round(duration_ms, 2),
            },
        )
        return payload

    async def submit_answer(
        self,
        *,
        query_id: int,
        answer: str,
        force: bool,
        current_user,
        http_request,
        request_id: str,
    ) -> Any:
        start_time = time.time()
        is_command = answer.strip().startswith("/")

        logger.info(
            "API: Submitting answer",
            extra={
                "request_id": request_id,
                "user_id": current_user.id,
                "query_id": query_id,
                "is_command": is_command,
                "answer_length": len(answer),
            },
        )

        db_query = self._get_query_for_user(query_id=query_id, current_user=current_user)
        framework_name = db_query.session.framework_name
        if not framework_name:
            raise QueryRefinementException("Framework name not found for session", status_code=400)
        framework = self._get_framework_or_raise(framework_name)

        try:
            async with self._session_manager.session_lock(query_id):
                return await self._submit_answer_locked(
                    query_id=query_id,
                    answer=answer,
                    force=force,
                    http_request=http_request,
                    current_user=current_user,
                    db_query=db_query,
                    framework=framework,
                    request_id=request_id,
                    start_time=start_time,
                    is_command=is_command,
                )
        except RuntimeError as exc:
            logger.warning("Could not acquire session lock for query %d: %s", query_id, exc)
            raise QueryRefinementException(
                "Session is temporarily locked by another request. Please retry in a moment.",
                status_code=503,
            ) from exc

    async def _submit_answer_locked(
        self,
        *,
        query_id: int,
        answer: str,
        force: bool,
        http_request,
        current_user,
        db_query,
        framework,
        request_id: str,
        start_time: float,
        is_command: bool,
    ) -> Any:
        session = self._session_manager.load_session(query_id, framework)
        if not session:
            logger.warning("Session not found in Redis for query_id=%d, reconstructing from database", query_id)
            session = await asyncio.to_thread(
                self._manager.initialize_sequential,
                db_query.original_query,
                framework,
            )
            db_steps = get_query_refinement_steps(self._db, query_id)
            restore_session_from_db_state(session, db_steps)
            self._session_manager.save_session(query_id, session)

        user_input = answer.strip()
        logger.info("[Query %d] Processing answer/command: %s...", query_id, user_input[:100])
        logger.info("[Query %d] Is command: %s", query_id, is_user_command(user_input))

        if is_user_command(user_input):
            return await self._handle_command(
                query_id=query_id,
                user_input=user_input,
                force=force,
                http_request=http_request,
                current_user=current_user,
                session=session,
            )

        active_step = session.get_active_step()
        if not active_step:
            raise QueryRefinementException("No active refinement step", status_code=400)

        active_step.conversation_history.append(
            {
                "question": active_step.follow_up_question or active_step.refinement_aspect.name,
                "response": user_input,
            }
        )

        await self._track_progress(
            query_id=str(query_id),
            stage=ProgressStage.USER_REFINING,
            message=f"Processing your input for '{active_step.refinement_aspect.name}'...",
            details={"aspect": active_step.refinement_aspect.name},
        )

        try:
            tracker = self._progress_tracker_factory()
            await tracker.increment_llm_calls(str(query_id))
            analysis_result = await self._manager.get_analysis_prompts(
                session=session,
                aspect_id=active_step.refinement_aspect.id,
                mode="followup",
            )
            analysis_status = self._manager.process_analysis_result(
                session=session,
                aspect_id=active_step.refinement_aspect.id,
                result=analysis_result,
            )
        except ConnectionError as exc:
            raise QueryRefinementException(
                f"Unable to connect to LLM service: {str(exc)}",
                status_code=503,
            ) from exc
        except TimeoutError as exc:
            raise QueryRefinementException(
                f"LLM service request timed out: {str(exc)}",
                status_code=504,
            ) from exc
        except Exception as exc:
            logger.error("Error in follow-up loop: %s", exc, exc_info=True)
            raise QueryRefinementException(
                f"Failed to process answer: {str(exc)}",
                status_code=500,
            ) from exc

        db_steps = get_query_refinement_steps(self._db, query_id)
        db_step = find_db_step_for_aspect(db_steps, active_step.refinement_aspect)
        if not db_step:
            logger.warning(
                "Missing refinement_step row for active aspect; recreating",
                extra={"query_id": query_id, "aspect": active_step.refinement_aspect.name},
            )
            db_step = create_refinement_step(
                self._db,
                query_id=query_id,
                aspect_name=active_step.refinement_aspect.name,
                aspect_id=active_step.refinement_aspect.id,
            )

        db_followup = create_followup(
            self._db,
            refinement_step_id=db_step.id,
            question=active_step.follow_up_question or active_step.refinement_aspect.name,
            answer=user_input,
        )
        followup_id = db_followup.id
        is_complete = analysis_status.get("complete", False)

        if is_complete and active_step.normalized_value:
            update_refinement_step_final_value(
                self._db,
                step_id=db_step.id,
                final_value=active_step.normalized_value_as_str,
                is_complete=True,
                was_skipped=False,
                user_ended_early=False,
            )
            logger.info(
                "Saved final value to DB for dimension '%s'",
                active_step.refinement_aspect.name,
                extra={"query_id": query_id, "dimension": active_step.refinement_aspect.name},
            )

        if not is_complete:
            fallback_question = f"Please provide more details about {active_step.refinement_aspect.name}."
            next_prompt = {
                "aspect_id": active_step.refinement_aspect.id,
                "name": active_step.refinement_aspect.name,
                "aspect_name": active_step.refinement_aspect.name,
                "question": active_step.follow_up_question or fallback_question,
                "description": active_step.refinement_aspect.description or "",
            }
        else:
            next_prompt = await build_next_prompt(self._manager, session, db=self._db, db_steps=db_steps)
            persist_generated_question(self._db, db_steps, next_prompt)

        self._session_manager.save_session(query_id, session)
        ready_for_synthesis = next_prompt is None and session.is_complete()

        duration_ms = (time.time() - start_time) * 1000
        logger.info(
            "API: Answer submitted successfully",
            extra={
                "request_id": request_id,
                "user_id": current_user.id,
                "query_id": query_id,
                "is_command": is_command,
                "is_complete": is_complete,
                "ready_for_synthesis": ready_for_synthesis,
                "duration_ms": round(duration_ms, 2),
            },
        )

        return {
            "refinement_step_id": db_step.id,
            "followup_id": followup_id,
            "is_complete": is_complete,
            "next_prompt": next_prompt,
            "ready_for_synthesis": ready_for_synthesis,
        }

    async def _handle_command(
        self,
        *,
        query_id: int,
        user_input: str,
        force: bool,
        http_request,
        current_user,
        session,
    ) -> Any:
        logger.info("[Query %d] COMMAND DETECTED: %s", query_id, user_input)
        cmd_result = parse_user_command(user_input)
        logger.info(
            "[Query %d] Command parsed - valid: %s, command: %s, arg: %s",
            query_id,
            cmd_result.is_valid,
            cmd_result.command,
            cmd_result.argument,
        )

        if not cmd_result.is_valid:
            logger.warning("[Query %d] Invalid command: %s", query_id, cmd_result.error_message)
            return await self._build_command_response_payload(
                command_type=cmd_result.command.value,
                payload={"success": False, "message": cmd_result.error_message or "Invalid command"},
                session=session,
                force_confirmation_needed=False,
                query_id=query_id,
            )

        logger.info("[Query %d] Executing command: %s", query_id, cmd_result.command.value)
        pre_command_active_step = session.get_active_step()
        command_payload = session.handle_command(cmd_result)
        command_type = cmd_result.command.value
        logger.info(
            "[Query %d] Command result - success: %s, message: %s",
            query_id,
            command_payload.get("success"),
            command_payload.get("message", "")[:100],
        )

        force_confirmation_needed = False
        if not force and command_type in {UserCommand.BACK.value, UserCommand.PREVIOUS.value, UserCommand.RESTART.value}:
            invalidated = command_payload.get("invalidated", [])
            if invalidated and command_payload.get("success", False):
                force_confirmation_needed = True
                logger.info("[Query %d] Force confirmation needed - would invalidate: %s", query_id, invalidated)
                command_payload["success"] = False
                command_payload["message"] = (
                    f"⚠️ Warning: This action will invalidate {len(invalidated)} dependent aspect(s): "
                    f"{', '.join(invalidated)}. This means you'll need to re-answer those aspects. "
                    f"Click 'Confirm' to proceed."
                )

        active_step = session.get_active_step()
        active_dimension = active_step.refinement_aspect.name if active_step else None
        command_audit_map = {
            "back": AuditEventType.COMMAND_BACK,
            "prev": AuditEventType.COMMAND_BACK,
            "previous": AuditEventType.COMMAND_BACK,
            "restart": AuditEventType.COMMAND_RESTART,
            "clear": AuditEventType.COMMAND_CLEAR,
            "skip": AuditEventType.COMMAND_SKIP,
            "done": AuditEventType.COMMAND_DONE,
            "status": AuditEventType.COMMAND_STATUS,
            "help": AuditEventType.COMMAND_HELP,
            "steps": AuditEventType.COMMAND_STEPS,
        }
        audit_event_type = command_audit_map.get(command_type, AuditEventType.COMMAND_EXECUTE)
        audit_details = {
            "command": command_type,
            "command_input": user_input,
            "argument": cmd_result.argument,
            "active_dimension": active_dimension,
            "force_requested": force,
            "force_confirmation_needed": force_confirmation_needed,
            "success": command_payload.get("success", False),
        }
        if "cleared_aspects" in command_payload:
            audit_details["cleared_aspects"] = command_payload["cleared_aspects"]
        if "invalidated" in command_payload:
            audit_details["invalidated_aspects"] = command_payload["invalidated"]
        if "target_aspect" in command_payload:
            audit_details["target_aspect"] = command_payload["target_aspect"]
        if "deleted_count" in command_payload:
            audit_details["deleted_db_records"] = command_payload["deleted_count"]

        if command_payload.get("success", False) and not force_confirmation_needed:
            await self._persist_command_side_effects(
                query_id=query_id,
                command_type=command_type,
                session=session,
                command_payload=command_payload,
                pre_command_active_step=pre_command_active_step,
            )

        audit_service.log_from_request(
            db=self._db,
            request=http_request,
            event_type=audit_event_type,
            user=current_user,
            severity="info" if command_payload.get("success") else "warning",
            resource_type="query",
            resource_id=str(query_id),
            action=f"Executed /{command_type} command" + (f" with arg '{cmd_result.argument}'" if cmd_result.argument else ""),
            status="success" if command_payload.get("success") and not force_confirmation_needed else "needs_confirmation" if force_confirmation_needed else "failure",
            details=audit_details,
        )

        command_response = await self._build_command_response_payload(
            command_type=command_type,
            payload=command_payload,
            session=session,
            force_confirmation_needed=force_confirmation_needed,
            query_id=query_id,
        )
        self._session_manager.save_session(query_id, session)
        return command_response

    async def _build_command_response_payload(
        self,
        *,
        command_type: str,
        payload: Dict[str, Any],
        session,
        force_confirmation_needed: bool = False,
        query_id: Optional[int] = None,
    ) -> Dict[str, Any]:
        logger.info("[_build_command_response_payload] Building response for command: %s", command_type)

        success = payload.get("success", False)
        message = payload.get("message", "")
        response: Dict[str, Any] = {
            "command_type": command_type,
            "success": success,
            "message": message,
            "next_prompt": None,
            "invalidated_aspects": None,
            "synthesis_ready": False,
            "step_summary": None,
            "step_list": None,
            "force_required": None,
        }

        db_steps = get_query_refinement_steps(self._db, query_id) if query_id is not None else []

        if not success or force_confirmation_needed:
            logger.info(
                "[_build_command_response_payload] Command failed or needs confirmation, preserving current prompt"
            )
            response["next_prompt"] = get_active_prompt(session) or await build_next_prompt(
                self._manager,
                session,
                db=self._db,
                db_steps=db_steps,
            )
            persist_generated_question(self._db, db_steps, response["next_prompt"])
            if force_confirmation_needed:
                response["force_required"] = True
                response["invalidated_aspects"] = payload.get("invalidated", [])
            return response

        if command_type == UserCommand.STATUS.value:
            response["step_summary"] = payload.get("summary")
            response["next_prompt"] = get_active_prompt(session)
            response["synthesis_ready"] = is_session_ready_for_synthesis(session)
        elif command_type == UserCommand.STEPS.value:
            steps = payload.get("steps", [])
            active_step = session.get_active_step()
            if steps:
                response["step_list"] = [
                    {
                        "name": step.refinement_aspect.name,
                        "aspect_id": step.refinement_aspect.id,
                        "is_complete": step.is_complete,
                        "needs_review": step.needs_review,
                        "was_skipped": step.was_skipped,
                        "follow_up_count": step.follow_up_count,
                        "status": (
                            "completed" if step.is_complete and not step.needs_review else
                            "needs review" if step.needs_review else
                            "active" if step == active_step else
                            "not started"
                        ),
                        "is_active": step == active_step,
                    }
                    for step in steps
                ]
            response["next_prompt"] = get_active_prompt(session)
        elif command_type == UserCommand.HELP.value:
            response["next_prompt"] = get_active_prompt(session)
        elif command_type == UserCommand.SUBMIT.value:
            response["synthesis_ready"] = True
            response["next_prompt"] = None
        elif command_type == UserCommand.CLEAR.value:
            response["next_prompt"] = await build_next_prompt(
                self._manager,
                session,
                db=self._db,
                db_steps=db_steps,
            )
            persist_generated_question(self._db, db_steps, response["next_prompt"])
        elif command_type in {UserCommand.BACK.value, UserCommand.PREVIOUS.value, UserCommand.RESTART.value}:
            response["invalidated_aspects"] = payload.get("invalidated", [])
            if command_type in {UserCommand.BACK.value, UserCommand.RESTART.value}:
                await self._ensure_reopened_step_question(session=session)
            response["next_prompt"] = await build_next_prompt(
                self._manager,
                session,
                db=self._db,
                db_steps=db_steps,
            )
            persist_generated_question(self._db, db_steps, response["next_prompt"])
        elif command_type in {UserCommand.SKIP.value, UserCommand.DONE.value}:
            response["next_prompt"] = await build_next_prompt(
                self._manager,
                session,
                db=self._db,
                db_steps=db_steps,
            )
            persist_generated_question(self._db, db_steps, response["next_prompt"])
            if response["next_prompt"] is None and session.is_complete():
                response["synthesis_ready"] = True

        if not response["synthesis_ready"]:
            response["synthesis_ready"] = is_session_ready_for_synthesis(session)

        logger.info(
            "[_build_command_response_payload] Response built successfully - next_prompt: %s, synthesis_ready: %s",
            "yes" if response["next_prompt"] else "no",
            response["synthesis_ready"],
        )
        return response

    async def _ensure_reopened_step_question(self, *, session) -> None:
        reopened_step = session.get_active_step()
        if not reopened_step or reopened_step.follow_up_question:
            return

        prompt_builder = PromptBuilder()
        aspect = reopened_step.refinement_aspect
        logger.info("[NAVIGATION] Generating fresh question for reopened dimension: %s", aspect.name)

        try:
            messages = prompt_builder.build_refinement_messages(
                dimension=aspect,
                query=session.original_query,
                conversation_history=[],
                dependency_context=session.get_dependency_context(aspect.id),
                completed_context=session.get_completed_context(aspect.id),
                terminal_reinforcement_threshold=getattr(self._manager, "terminal_reinforcement_threshold", 3),
            )
            if messages and messages[-1].get("role") == "user":
                messages[-1]["content"] += (
                    "\n\nCRITICAL: The user has navigated back to review this dimension from scratch. "
                    "The dimension has been completely reset with no previous values. You MUST ask a "
                    "clarifying question as if this is the very first time asking about this dimension. "
                    "Do NOT assume anything is already clear - treat this as a fresh initial question."
                )

            llm_result = await self._manager.llm_provider.complete_async(
                messages=messages,
                temperature=0.0,
                response_format=DimensionEvaluationResponse,
                cache_system_prompt=True,
            )
            generated_question = self._extract_generated_question(llm_result.context)
            if generated_question:
                reopened_step.follow_up_question = generated_question
                return
            logger.warning("[NAVIGATION] LLM did not generate proper question, using fallback")
        except Exception as exc:
            logger.error("[NAVIGATION] Error generating question for reopened step: %s", exc, exc_info=True)

        reopened_step.follow_up_question = (
            f"Let's review {aspect.name} for your research query. "
            "What would you like to specify for this dimension?"
        )

    def _extract_generated_question(self, llm_context: Any) -> Optional[str]:
        if isinstance(llm_context, DimensionEvaluationResponse):
            candidate = llm_context.question
        elif isinstance(llm_context, dict):
            candidate = llm_context.get("question") or llm_context.get("next_question")
        elif isinstance(llm_context, str):
            cleaned = llm_context.strip()
            if cleaned.startswith("```"):
                lines = cleaned.splitlines()
                body = lines[1:]
                if body and body[-1].startswith("```"):
                    body = body[:-1]
                cleaned = "\n".join(body).strip()
            try:
                parsed = json.loads(cleaned)
                candidate = parsed.get("question") or parsed.get("next_question")
            except Exception:
                candidate = None
        else:
            candidate = None

        if isinstance(candidate, str) and candidate.strip():
            return candidate.strip()
        return None

    async def _run_synthesis(
        self,
        *,
        session,
        db_query,
        current_user,
        query_id: int,
        request_id: str,
        include_expansion: bool = False,
    ) -> Dict[str, Any]:
        tracker = self._progress_tracker_factory()

        await self._track_progress(
            query_id=str(query_id),
            stage=ProgressStage.SYNTHESIZING,
            message="Synthesizing final refined query...",
            details={"framework": db_query.session.framework_name},
        )

        try:
            await tracker.increment_llm_calls(str(query_id))
            synthesis_result = await self._manager.synthesize_refined_query(session)
        except Exception as exc:
            await self._track_progress(
                query_id=str(query_id),
                stage=ProgressStage.FAILED,
                message="Synthesis failed",
                error=str(exc),
            )
            raise QueryRefinementException(
                f"Failed to synthesize query: {str(exc)}",
                status_code=500,
            ) from exc

        clarified_query = synthesis_result.get("clarified_query", "")
        structured_output = None
        if synthesis_result.get("dimensions_specifications"):
            structured_output = {
                "dimensions_specifications": synthesis_result.get("dimensions_specifications"),
                "keyword_statement": synthesis_result.get("keyword_statement"),
                "search_optimized": synthesis_result.get("search_optimized"),
                "search_filters": synthesis_result.get("search_filters"),
                "terminology": synthesis_result.get("terminology"),
                "concept_graph": synthesis_result.get("concept_graph"),
            }
        elif clarified_query and (clarified_query.startswith("{") or clarified_query.startswith("`")):
            structured_output, clarified_query = self._extract_structured_output_from_query_string(
                clarified_query=clarified_query,
                request_id=request_id,
            )

        if not clarified_query or not clarified_query.strip():
            raise QueryRefinementException(
                "Synthesis produced empty result. Please try again.",
                status_code=500,
            )

        settings = self._settings_factory()
        if settings.enforce_workflow_limit and not current_user.is_superuser:
            current_user.has_completed_workflow = True

        save_query_refinement_response(
            self._db,
            query_id,
            {
                "clarified_query": clarified_query,
                "dimensions_specifications": (
                    structured_output.get("dimensions_specifications")
                    if structured_output
                    else synthesis_result.get("dimensions_specifications")
                ),
                "search_optimized": (
                    structured_output.get("search_optimized")
                    if structured_output
                    else synthesis_result.get("search_optimized")
                ),
                "search_filters": (
                    structured_output.get("search_filters")
                    if structured_output
                    else synthesis_result.get("search_filters")
                ),
                "terminology": (
                    structured_output.get("terminology")
                    if structured_output
                    else synthesis_result.get("terminology")
                ),
                "metadata": synthesis_result.get("metadata"),
                "processing_log": synthesis_result.get("processing_log"),
            },
        )

        await self._track_progress(
            query_id=str(query_id),
            stage=ProgressStage.SYNTHESIS_COMPLETE,
            message="Synthesis completed successfully",
        )
        self._session_manager.delete_session(query_id)
        await self._track_progress(
            query_id=str(query_id),
            stage=ProgressStage.COMPLETED,
            message="Refinement completed successfully",
        )

        expansion_levels = None
        expansion_metadata = None
        if include_expansion:
            so = synthesis_result.get("search_optimized")
            keyword = getattr(so, "keyword", None) if so else None
            combined_blocks = getattr(keyword, "combined_blocks", None) if keyword else None
            concept_graph = synthesis_result.get("concept_graph") or {}
            if combined_blocks and clarified_query:
                try:
                    exp_input = SearchExpansionInput(
                        clarified_query=clarified_query,
                        anchor_blocks=combined_blocks,
                        concept_graph=concept_graph,
                        semantic_statement=getattr(so, "semantic", "") or "",
                        keyword_statement=synthesis_result.get("keyword_statement") or "",
                        keyword_structured=getattr(keyword, "structured", "") or "",
                        search_filters=synthesis_result.get("search_filters"),
                        phrases=list(getattr(keyword, "phrases", None) or []),
                    )
                    exp_result, exp_meta = await self._manager.generate_search_expansion_levels(
                        search_input=exp_input,
                    )
                    expansion_levels = [level.model_dump(by_alias=True) for level in exp_result.levels]
                    expansion_metadata = {
                        "geography_broadening_strategy": exp_result.geography_broadening_strategy,
                        "recommended_starting_level": exp_result.recommended_starting_level,
                        "recommendation_rationale": exp_result.recommendation_rationale,
                        **exp_meta,
                    }
                except Exception as exc:
                    logger.warning(
                        "Agent D expansion failed during synthesize pipeline: %s",
                        exc,
                        extra={"request_id": request_id, "query_id": query_id},
                    )

        return {
            "query_id": query_id,
            "clarified_query": clarified_query,
            "integrated_statement": clarified_query,
            "used_llm": synthesis_result.get("used_llm", False),
            "structured_output": structured_output,
            "expansion_levels": expansion_levels,
            "expansion_metadata": expansion_metadata,
        }

    def _extract_structured_output_from_query_string(
        self,
        *,
        clarified_query: str,
        request_id: str,
    ) -> tuple[Optional[Dict[str, Any]], str]:
        structured_output = None
        current_query = clarified_query
        try:
            json_str = clarified_query
            if json_str.startswith("`"):
                lines = json_str.split("\n")
                if lines[0].startswith("`"):
                    lines = lines[1:]
                if lines and lines[-1].strip().startswith("`"):
                    lines = lines[:-1]
                json_str = "\n".join(lines)

            if not json_str.rstrip().endswith("}"):
                logger.error(
                    "JSON response appears truncated (doesn't end with '}'), likely hit max_tokens limit",
                    extra={"json_length": len(json_str), "request_id": request_id},
                )
                import re
                match = re.search(r'"clarified_query"\s*:\s*"([^"]+)"', json_str)
                if match:
                    current_query = match.group(1)
                raise ValueError("JSON response was truncated, increase max_tokens")

            parsed = json.loads(json_str)
            structured_output = {
                "dimensions_specifications": parsed.get("dimensions_specifications"),
                "search_optimized": parsed.get("search_optimized"),
                "search_filters": parsed.get("search_filters"),
                "terminology": parsed.get("terminology"),
                "concept_graph": parsed.get("concept_graph"),
            }
            if parsed.get("clarified_query"):
                current_query = parsed["clarified_query"]
        except (json.JSONDecodeError, ValueError) as exc:
            logger.error(
                "Failed to parse JSON from clarified_query: %s",
                exc,
                extra={"error_type": type(exc).__name__},
            )
        return structured_output, current_query

    async def _persist_command_side_effects(
        self,
        *,
        query_id: int,
        command_type: str,
        session,
        command_payload: Dict[str, Any],
        pre_command_active_step,
    ) -> None:
        if command_type not in {
            UserCommand.BACK.value,
            UserCommand.PREVIOUS.value,
            UserCommand.RESTART.value,
            UserCommand.SKIP.value,
            UserCommand.DONE.value,
            UserCommand.SUBMIT.value,
        }:
            return

        logger.info("[Query %d] Saving session state after command: %s", query_id, command_type)

        if command_type in {UserCommand.BACK.value, UserCommand.PREVIOUS.value, UserCommand.RESTART.value}:
            cleared_aspects = command_payload.get("cleared_aspects", [])
            if cleared_aspects:
                deleted_count = delete_refinement_steps_by_aspects(
                    self._db,
                    query_id=query_id,
                    aspect_names=cleared_aspects,
                )
                logger.info(
                    "[Query %d] Cascade deleted %d DB records for truncated dimensions: %s",
                    query_id,
                    deleted_count,
                    cleared_aspects,
                    extra={"query_id": query_id, "command": command_type, "deleted_count": deleted_count},
                )

            if command_type in {UserCommand.BACK.value, UserCommand.PREVIOUS.value}:
                reopened_step = session.get_active_step()
                if reopened_step:
                    db_steps = get_query_refinement_steps(self._db, query_id)
                    db_step = find_db_step_for_aspect(db_steps, reopened_step.refinement_aspect)
                    if db_step:
                        reset_refinement_step(self._db, step_id=db_step.id, clear_followup_history=True)
                        logger.info(
                            "[Query %d] Reset DB record for reopened dimension: '%s'",
                            query_id,
                            reopened_step.refinement_aspect.name,
                            extra={"query_id": query_id, "dimension": reopened_step.refinement_aspect.name},
                        )

        if command_type == UserCommand.CLEAR.value:
            active_step = session.get_active_step()
            if active_step:
                db_steps = get_query_refinement_steps(self._db, query_id)
                db_step = find_db_step_for_aspect(db_steps, active_step.refinement_aspect)
                if db_step:
                    reset_refinement_step(self._db, step_id=db_step.id, clear_followup_history=True)
                    logger.info(
                        "[Query %d] Reset DB record for cleared dimension: '%s'",
                        query_id,
                        active_step.refinement_aspect.name,
                        extra={"query_id": query_id, "dimension": active_step.refinement_aspect.name},
                    )

        if command_type in {UserCommand.SKIP.value, UserCommand.DONE.value}:
            command_step = pre_command_active_step or command_payload.get("step")
            if command_step and command_step.is_complete:
                db_steps = get_query_refinement_steps(self._db, query_id)
                db_step = find_db_step_for_aspect(db_steps, command_step.refinement_aspect)
                if db_step:
                    if command_type == UserCommand.SKIP.value:
                        mark_refinement_step_skipped(self._db, db_step.id)
                        logger.info(
                            "Marked dimension as skipped in DB: '%s'",
                            command_step.refinement_aspect.name,
                            extra={"query_id": query_id, "dimension": command_step.refinement_aspect.name},
                        )
                    elif command_type == UserCommand.DONE.value:
                        mark_refinement_step_user_ended_early(
                            self._db,
                            step_id=db_step.id,
                            final_value=command_step.normalized_value_as_str if command_step.normalized_value_as_str else None,
                        )
                        logger.info(
                            "Marked dimension as user-completed in DB: '%s'",
                            command_step.refinement_aspect.name,
                            extra={"query_id": query_id, "dimension": command_step.refinement_aspect.name},
                        )

        self._session_manager.save_session(query_id, session)
