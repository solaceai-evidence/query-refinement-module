"""Shared support primitives for refinement application services."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

from query_refinement_module.api.exceptions import (
    FrameworkNotFoundError,
    QueryRefinementException,
    ResourceNotFoundError,
    UnauthorizedError,
)
from query_refinement_module.db.crud import (
    get_query,
    get_query_refinement_steps,
    user_has_framework_access,
)
from query_refinement_module.schema.registry import get_framework
from query_refinement_module.services.progress_tracker import get_progress_tracker, track_progress

from .refinement_workflow import restore_session_from_db_state


logger = logging.getLogger(__name__)


@dataclass(slots=True)
class RefinementServiceSupport:
    """Shared dependencies and reconstruction helpers for refinement services."""

    manager: Any
    db: Any
    session_manager: Any
    settings_factory: Callable[[], Any]
    progress_tracker_factory: Callable[[], Any] = get_progress_tracker
    progress_fn: Callable[..., Awaitable[Any]] = track_progress
    query_loader: Callable[..., Any] = get_query
    framework_resolver: Callable[[str], Any] = get_framework

    def get_framework_or_raise(self, framework_name: str):
        try:
            return self.framework_resolver(framework_name)
        except Exception as exc:
            raise FrameworkNotFoundError(framework_name) from exc

    def require_start_permissions(self, *, current_user, framework_name: str) -> None:
        settings = self.settings_factory()
        if settings.enforce_workflow_limit and not current_user.is_superuser and current_user.has_completed_workflow:
            raise UnauthorizedError(
                "You have already completed one refinement workflow. "
                "For evaluation purposes, only one workflow per participant is allowed. "
                "Thank you for your participation!"
            )

        if not current_user.is_superuser and not user_has_framework_access(self.db, current_user.id, framework_name):
            raise UnauthorizedError(
                f"You are not authorized to use framework '{framework_name}'"
            )

    async def initialize_session(self, *, original_query: str, framework):
        try:
            return await asyncio.to_thread(
                self.manager.initialize_sequential,
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

    def get_query_for_user(self, *, query_id: int, current_user):
        db_query = self.query_loader(self.db, query_id)
        if not db_query:
            raise ResourceNotFoundError("Query", query_id)
        if db_query.session.user_id != current_user.id:
            raise ResourceNotFoundError("Query", query_id)
        return db_query

    async def load_or_reconstruct_session(self, *, query_id: int, db_query, framework):
        session = self.session_manager.load_session(query_id, framework)
        if session:
            return session

        return await self.reconstruct_session_from_db(
            query_id=query_id,
            db_query=db_query,
            framework=framework,
        )

    async def reconstruct_session_from_db(self, *, query_id: int, db_query, framework):

        logger.warning(
            "Session not found in Redis for query_id=%d, reconstructing from database",
            query_id,
        )
        session = await asyncio.to_thread(
            self.manager.initialize_sequential,
            db_query.original_query,
            framework,
        )
        db_steps = get_query_refinement_steps(self.db, query_id)
        restore_session_from_db_state(session, db_steps)
        return session