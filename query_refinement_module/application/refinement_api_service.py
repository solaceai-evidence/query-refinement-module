"""Application service for the refinement workflow HTTP entry points."""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Awaitable, Callable, Dict, Optional

from query_refinement_module.api.exceptions import (
    FrameworkNotFoundError,
    QueryRefinementException,
    ResourceNotFoundError,
    UnauthorizedError,
)
from query_refinement_module.core import QueryRefinementManager
from query_refinement_module.db.crud import (
    create_query,
    create_query_session,
    create_refinement_step,
    get_query,
    get_query_refinement_steps,
    mark_refinement_step_skipped,
    user_has_framework_access,
)
from query_refinement_module.models.progress import ProgressStage
from query_refinement_module.schema.registry import get_framework
from query_refinement_module.services.progress_tracker import get_progress_tracker, track_progress

from .refinement_workflow import (
    build_next_prompt,
    build_status_payload,
    get_active_prompt,
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
        synthesis_runner: Callable[..., Awaitable[Any]],
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

            synthesis_response = await synthesis_runner(
                manager=self._manager,
                session=session,
                db=self._db,
                db_query=db_query,
                current_user=current_user,
                session_manager=self._session_manager,
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
