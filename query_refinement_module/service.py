"""Async-friendly service facade for the query refinement manager."""

from __future__ import annotations

import asyncio
import uuid
from typing import Callable, Optional

from .analyzers import LLMQueryAnalyzer
from .api_models import (
    InteractionRequest,
    InteractionResponse,
    NextPrompt,
    SessionCreateRequest,
    SessionCreateResponse,
    SessionStatusResponse,
)
from .core import (
    QueryRefinementManager,
    QueryRefinementSession,
    is_user_command,
    parse_user_command,
)
from .interfaces import SessionStorageInterface, TracingProviderInterface
from .providers import LiteLLMProvider
from .settings import LLMSettings


def build_manager_from_env(
    *,
    settings: Optional[LLMSettings] = None,
    tracing_provider: Optional[TracingProviderInterface] = None,
) -> QueryRefinementManager:
    """Construct a ``QueryRefinementManager`` using environment-driven LLM settings."""

    resolved_settings = settings or LLMSettings.from_env()
    provider = LiteLLMProvider(**resolved_settings.as_provider_kwargs())
    analyzer = LLMQueryAnalyzer(provider, **resolved_settings.as_analyzer_kwargs())

    return QueryRefinementManager(
        llm_provider=provider,
        query_analyzer=analyzer,
        tracing_provider=tracing_provider,
    )


class QueryRefinementService:
    """High-level orchestration layer that exposes async APIs for clients."""

    def __init__(
        self,
        manager: QueryRefinementManager,
        storage: SessionStorageInterface,
        session_id_factory: Optional[Callable[[], str]] = None,
    ) -> None:
        self._manager = manager
        self._storage = storage
        self._session_id_factory = session_id_factory or (lambda: str(uuid.uuid4()))

    async def create_session(self, request: SessionCreateRequest) -> SessionCreateResponse:
        """Initialize a new refinement session using sequential on-demand workflow."""

        session_id = request.session_id or self._session_id_factory()
        
        # Always use sequential initialization (no parallel mode)
        session = await asyncio.to_thread(
            self._manager.initialize_sequential,
            request.original_query,
            request.refinement_framework,
        )

        await asyncio.to_thread(self._storage.save_session, session_id, session)

        summary = self._manager.get_initialization_summary(session)
        next_prompt = self._build_next_prompt(session)

        metadata = request.metadata or {}
        metadata = {**metadata, "session_id": session_id}

        return SessionCreateResponse(
            session_id=session_id,
            summary=summary,
            next_prompt=next_prompt,
            metadata=metadata,
        )

    async def submit_user_message(self, request: InteractionRequest) -> InteractionResponse:
        """Process a user message (command or free-form response)."""

        session: QueryRefinementSession = await asyncio.to_thread(
            self._storage.load_session, request.session_id
        )

        message = request.message.strip()
        invalidated: list[str] = []

        if is_user_command(message):
            command_result = parse_user_command(message)
            result_payload = session.handle_command(command_result)
            success = result_payload.get("success", False)
            response_message = result_payload.get("message", "")
            invalidated = result_payload.get("invalidated", []) or []
        else:
            active_step = session.get_active_step()
            if not active_step:
                success = False
                response_message = "Refinement session is already complete."
            else:
                question = (
                    active_step.refinement_question
                    or active_step.refinement_aspect.aspect_name
                )
                active_step.add_follow_up(question=question, response=message)
                active_step.is_complete = True
                active_step.needs_review = False
                success = True
                response_message = (
                    f"Recorded response for {active_step.refinement_aspect.aspect_name}."
                )

        summary = self._manager.get_initialization_summary(session)
        next_prompt = self._build_next_prompt(session)
        session_complete = session.is_complete()

        await asyncio.to_thread(self._storage.save_session, request.session_id, session)

        metadata = request.metadata or {}

        return InteractionResponse(
            session_id=request.session_id,
            success=success,
            message=response_message,
            next_prompt=next_prompt,
            summary=summary,
            invalidated_aspects=invalidated,
            session_complete=session_complete,
            metadata=metadata,
        )

    async def get_session_status(self, session_id: str) -> SessionStatusResponse:
        """Fetch a point-in-time view of the session state."""

        session: QueryRefinementSession = await asyncio.to_thread(
            self._storage.load_session, session_id
        )
        summary = self._manager.get_initialization_summary(session)
        next_prompt = self._build_next_prompt(session)
        history = session.get_full_conversation() if summary["total_aspects"] else None

        return SessionStatusResponse(
            session_id=session_id,
            summary=summary,
            next_prompt=next_prompt,
            session_complete=session.is_complete(),
            history=history,
        )

    async def delete_session(self, session_id: str) -> None:
        """Remove a persisted session."""

        await asyncio.to_thread(self._storage.delete_session, session_id)

    @staticmethod
    def _build_next_prompt(session: QueryRefinementSession) -> Optional[NextPrompt]:
        """Construct the next prompt payload for the caller."""

        step = session.get_active_step()
        if not step:
            return None

        question = step.refinement_question
        if not question:
            try:
                question = step.refinement_aspect.get_evaluation_instructions_prompt(
                    statement=session.original_query
                )
            except Exception:  # pragma: no cover - best effort fallback
                question = step.refinement_aspect.aspect_description

        dependency_context = {
            dep_id: entry["value"]
            for dep_id, entry in session.get_dependency_context(
                step.refinement_aspect.id
            ).items()
        }

        return NextPrompt(
            aspect_id=step.refinement_aspect.id,
            aspect_name=step.refinement_aspect.aspect_name,
            question=question,
            reasoning=step.needs_refinement_rationale,
            dependency_context=dependency_context,
        )
