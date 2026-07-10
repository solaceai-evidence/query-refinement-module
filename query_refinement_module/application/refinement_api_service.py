"""Stable facade for refinement application workflows."""

from __future__ import annotations

from typing import Any, Awaitable, Callable, Dict, Optional

from query_refinement_module.core import QueryRefinementManager
from query_refinement_module.db.crud import get_query
from query_refinement_module.schema.registry import get_framework
from query_refinement_module.services.progress_tracker import get_progress_tracker, track_progress

from .refinement_agent_service import RefinementAgentService
from .refinement_lifecycle_service import RefinementLifecycleService
from .refinement_service_support import RefinementServiceSupport
from .refinement_utility_service import RefinementUtilityService


class RefinementApiService:
    """Public application-layer entry point for refinement HTTP workflows.

    The facade preserves the route-facing API while delegating behavior to
    focused collaborators for lifecycle orchestration, agent transforms, and
    utility workflows.
    """

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
        self._support = RefinementServiceSupport(
            manager=manager,
            db=db,
            session_manager=session_manager,
            settings_factory=settings_factory,
            progress_tracker_factory=progress_tracker_factory,
            progress_fn=progress_fn,
            query_loader=get_query,
            framework_resolver=get_framework,
        )
        self._lifecycle_service = RefinementLifecycleService(self._support)
        self._agent_service = RefinementAgentService(self._support)
        self._utility_service = RefinementUtilityService(self._support)

    def _get_framework_or_raise(self, framework_name: str):
        return self._support.get_framework_or_raise(framework_name)

    def _require_start_permissions(self, *, current_user, framework_name: str) -> None:
        self._support.require_start_permissions(current_user=current_user, framework_name=framework_name)

    async def _initialize_session(self, *, original_query: str, framework):
        return await self._support.initialize_session(original_query=original_query, framework=framework)

    def _get_query_for_user(self, *, query_id: int, current_user):
        return self._support.get_query_for_user(query_id=query_id, current_user=current_user)

    async def load_or_reconstruct_session(self, *, query_id: int, db_query, framework):
        return await self._support.load_or_reconstruct_session(
            query_id=query_id,
            db_query=db_query,
            framework=framework,
        )

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
        return await self._lifecycle_service.start_workflow(
            original_query=original_query,
            framework_name=framework_name,
            source=source,
            skip_refinement=skip_refinement,
            current_user=current_user,
            request_id=request_id,
        )

    async def synthesize_workflow(
        self,
        *,
        query_id: int,
        include_expansion: bool,
        current_user,
        request_id: str,
    ) -> Dict[str, Any]:
        return await self._lifecycle_service.synthesize_workflow(
            query_id=query_id,
            include_expansion=include_expansion,
            current_user=current_user,
            request_id=request_id,
        )

    async def normalize_workflow(
        self,
        *,
        query_id: int,
        current_user,
        request_id: str,
    ) -> Dict[str, Any]:
        return await self._agent_service.normalize_workflow(
            query_id=query_id,
            current_user=current_user,
            request_id=request_id,
        )

    async def represent_workflow(
        self,
        *,
        statement: str,
        model: Optional[str],
        current_user,
        request_id: str,
    ) -> Dict[str, Any]:
        return await self._agent_service.represent_workflow(
            statement=statement,
            model=model,
            current_user=current_user,
            request_id=request_id,
        )

    async def construct_workflow(
        self,
        *,
        statement: str,
        concept_graph: Dict[str, Any],
        model: Optional[str],
        current_user,
        request_id: str,
    ) -> Dict[str, Any]:
        return await self._agent_service.construct_workflow(
            statement=statement,
            concept_graph=concept_graph,
            model=model,
            current_user=current_user,
            request_id=request_id,
        )

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
        return await self._agent_service.expand_workflow(
            statement=statement,
            anchor_blocks=anchor_blocks,
            search_context=search_context,
            semantic_statement=semantic_statement,
            keyword_statement=keyword_statement,
            keyword_structured=keyword_structured,
            search_filters=search_filters,
            phrases=phrases,
            model=model,
            current_user=current_user,
            request_id=request_id,
        )

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
        return await self._utility_service.forward_to_qa_workflow(
            query_id=query_id,
            qa_system_url=qa_system_url,
            qa_system_auth=qa_system_auth,
            timeout_seconds=timeout_seconds,
            include_refinement_metadata=include_refinement_metadata,
            forward_original_query=forward_original_query,
            current_user=current_user,
            request_id=request_id,
        )

    def get_command_history_payload(self, *, query_id: int, limit: int, current_user) -> Dict[str, Any]:
        return self._utility_service.get_command_history_payload(
            query_id=query_id,
            limit=limit,
            current_user=current_user,
        )

    def inspect_messages_payload(self, *, query_id: int, current_user) -> Dict[str, Any]:
        return self._utility_service.inspect_messages_payload(
            query_id=query_id,
            current_user=current_user,
        )

    async def abandon_session_workflow(
        self,
        *,
        session_id: int,
        current_user,
        http_request,
        request_id: str,
    ) -> Dict[str, Any]:
        return await self._utility_service.abandon_session_workflow(
            session_id=session_id,
            current_user=current_user,
            http_request=http_request,
            request_id=request_id,
        )

    async def get_query_progress_payload(self, *, query_id: str, current_user):
        return await self._utility_service.get_query_progress_payload(
            query_id=query_id,
            current_user=current_user,
        )

    async def get_status_payload(self, *, query_id: int, current_user, request_id: str) -> Dict[str, Any]:
        return await self._lifecycle_service.get_status_payload(
            query_id=query_id,
            current_user=current_user,
            request_id=request_id,
        )

    async def resume_workflow(self, *, query_id: int, current_user, request_id: str) -> Dict[str, Any]:
        return await self._lifecycle_service.resume_workflow(
            query_id=query_id,
            current_user=current_user,
            request_id=request_id,
        )

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
        return await self._lifecycle_service.submit_answer(
            query_id=query_id,
            answer=answer,
            force=force,
            current_user=current_user,
            http_request=http_request,
            request_id=request_id,
        )

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
        return await self._lifecycle_service._submit_answer_locked(
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
        return await self._lifecycle_service._handle_command(
            query_id=query_id,
            user_input=user_input,
            force=force,
            http_request=http_request,
            current_user=current_user,
            session=session,
        )

    async def _build_command_response_payload(
        self,
        *,
        command_type: str,
        payload: Dict[str, Any],
        session,
        force_confirmation_needed: bool = False,
        query_id: Optional[int] = None,
    ) -> Dict[str, Any]:
        return await self._lifecycle_service._build_command_response_payload(
            command_type=command_type,
            payload=payload,
            session=session,
            force_confirmation_needed=force_confirmation_needed,
            query_id=query_id,
        )

    async def _ensure_reopened_step_question(self, *, session) -> None:
        await self._lifecycle_service._ensure_reopened_step_question(session=session)

    def _extract_generated_question(self, llm_context: Any) -> Optional[str]:
        return self._lifecycle_service._extract_generated_question(llm_context)

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
        return await self._lifecycle_service._run_synthesis(
            session=session,
            db_query=db_query,
            current_user=current_user,
            query_id=query_id,
            request_id=request_id,
            include_expansion=include_expansion,
        )

    def _extract_structured_output_from_query_string(
        self,
        *,
        clarified_query: str,
        request_id: str,
    ) -> tuple[Optional[Dict[str, Any]], str]:
        return self._lifecycle_service._extract_structured_output_from_query_string(
            clarified_query=clarified_query,
            request_id=request_id,
        )

    async def _persist_command_side_effects(
        self,
        *,
        query_id: int,
        command_type: str,
        session,
        command_payload: Dict[str, Any],
        pre_command_active_step,
    ) -> None:
        await self._lifecycle_service._persist_command_side_effects(
            query_id=query_id,
            command_type=command_type,
            session=session,
            command_payload=command_payload,
            pre_command_active_step=pre_command_active_step,
        )
