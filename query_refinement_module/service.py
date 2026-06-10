"""Async-friendly service facade for the query refinement manager."""

from __future__ import annotations

import asyncio
import logging
import uuid
from typing import Callable, Optional

logger = logging.getLogger(__name__)

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
    RefinementSession,
    is_user_command,
    parse_user_command,
)
from .interfaces import SessionStorageInterface, TracingProviderInterface
from .next_prompt import resolve_next_prompt
from .providers import LiteLLMProvider
from .settings import LLMSettings


def build_manager_from_env(
    *,
    settings: Optional[LLMSettings] = None,
    tracing_provider: Optional[TracingProviderInterface] = None,
) -> QueryRefinementManager:
    """Construct a ``QueryRefinementManager`` using environment-driven LLM settings.
    
    Note: This creates a manager WITHOUT a query analyzer (deprecated).
    Use initialize_sequential() for on-demand refinement.
    """

    resolved_settings = settings or LLMSettings.from_env(load_env_file=True)
    provider = LiteLLMProvider(**resolved_settings.as_provider_kwargs())
    # Analyzer is deprecated - don't create one by default

    return QueryRefinementManager(
        llm_provider=provider,
        tracing_provider=tracing_provider,
        default_temperature=getattr(resolved_settings, "temperature", 0.0),
        default_max_tokens=getattr(resolved_settings, "max_tokens", 4096) or 4096,
        terminal_reinforcement_threshold=resolved_settings.terminal_reinforcement_threshold,
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

    @staticmethod
    def _build_prompt_payload(
        session: RefinementSession,
        step,
        question: str,
    ) -> NextPrompt:
        """Convert an active step into the service-layer prompt payload."""

        dependency_context = {
            dep_id: entry["value"]
            for dep_id, entry in session.get_dependency_context(
                step.refinement_aspect.id
            ).items()
        }

        return NextPrompt(
            aspect_id=step.refinement_aspect.id,
            aspect_name=step.refinement_aspect.name,
            question=question,
            description=step.refinement_aspect.description,
            reasoning=step.reasoning,
            dependency_context=dependency_context,
        )

    async def create_session(self, request: SessionCreateRequest) -> SessionCreateResponse:
        """Initialize a new refinement session using sequential on-demand workflow."""

        session_id = request.session_id or self._session_id_factory()
        
        # Always use sequential initialization (no parallel mode)
        session = self._manager.initialize_sequential(
            request.original_query,
            request.refinement_framework,
        )

        try:
            await asyncio.to_thread(self._storage.save_session, session_id, session)
        except Exception as exc:
            logger.error(
                "Failed to save new session to storage: session_id=%s error=%s",
                session_id,
                exc,
                exc_info=True,
            )
            raise

        next_prompt = await self._build_next_prompt(session)
        summary = self._manager.get_initialization_summary(session)

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

        try:
            session: RefinementSession = await asyncio.to_thread(
                self._storage.load_session, request.session_id
            )
        except KeyError:
            raise
        except Exception as exc:
            logger.error(
                "Failed to load session from storage: session_id=%s error=%s",
                request.session_id,
                exc,
                exc_info=True,
            )
            raise

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
                    active_step.follow_up_question
                    or active_step.refinement_aspect.name
                )
                active_step.add_follow_up(question=question, response=message)
                active_step.needs_review = False

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

                success = True
                if analysis_status.get("complete", False):
                    response_message = (
                        f"Recorded response for {active_step.refinement_aspect.name}."
                    )
                else:
                    response_message = (
                        f"Recorded response for {active_step.refinement_aspect.name}. "
                        "More clarification is required."
                    )

        next_prompt = await self._build_next_prompt(session)
        summary = self._manager.get_initialization_summary(session)
        session_complete = session.is_complete()

        try:
            await asyncio.to_thread(self._storage.save_session, request.session_id, session)
        except Exception as exc:
            logger.error(
                "Failed to save session to storage after message: session_id=%s error=%s",
                request.session_id,
                exc,
                exc_info=True,
            )
            raise

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

        try:
            session: RefinementSession = await asyncio.to_thread(
                self._storage.load_session, session_id
            )
        except KeyError:
            raise
        except Exception as exc:
            logger.error(
                "Failed to load session from storage: session_id=%s error=%s",
                session_id,
                exc,
                exc_info=True,
            )
            raise
        next_prompt = await self._build_next_prompt(session)
        summary = self._manager.get_initialization_summary(session)
        history = session.get_full_conversation() if summary["total_aspects"] else None

        try:
            await asyncio.to_thread(self._storage.save_session, session_id, session)
        except Exception as exc:
            logger.error(
                "Failed to save session to storage after status refresh: session_id=%s error=%s",
                session_id,
                exc,
                exc_info=True,
            )
            raise

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

    async def _build_next_prompt(self, session: RefinementSession) -> Optional[NextPrompt]:
        """Construct the next prompt using the manager's canonical analysis path."""
        return await resolve_next_prompt(
            session,
            analyze_initial=lambda step: self._manager.get_analysis_prompts(
                session=session,
                aspect_id=step.refinement_aspect.id,
                mode="initial",
            ),
            process_analysis_result=lambda step, result: self._manager.process_analysis_result(
                session=session,
                aspect_id=step.refinement_aspect.id,
                result=result,
            ),
            build_payload=self._build_prompt_payload,
            logger=logger,
            failure_log_message="Failed to analyze initial prompt for aspect '%s': %s",
        )
