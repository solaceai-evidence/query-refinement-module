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
    create_followup,
    create_query,
    create_query_session,
    create_refinement_step,
    delete_refinement_steps_by_aspects,
    get_query,
    get_query_refinement_steps,
    mark_refinement_step_skipped,
    mark_refinement_step_user_ended_early,
    reset_refinement_step,
    update_refinement_step_final_value,
    user_has_framework_access,
)
from query_refinement_module.db.models.audit_log import AuditEventType
from query_refinement_module.models.progress import ProgressStage
from query_refinement_module.schema import DimensionEvaluationResponse
from query_refinement_module.schema.prompt_builder import PromptBuilder
from query_refinement_module.schema.registry import get_framework
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

    async def submit_answer(
        self,
        *,
        query_id: int,
        answer: str,
        force: bool,
        current_user,
        http_request,
        request_id: str,
        command_response_builder: Callable[..., Awaitable[Any]],
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
                    command_response_builder=command_response_builder,
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
        command_response_builder: Callable[..., Awaitable[Any]],
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
                command_response_builder=command_response_builder,
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
        command_response_builder: Callable[..., Awaitable[Any]],
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
            return await command_response_builder(
                manager=self._manager,
                command_type=cmd_result.command.value,
                payload={"success": False, "message": cmd_result.error_message or "Invalid command"},
                session=session,
                force_confirmation_needed=False,
                db=self._db,
                query_id=query_id,
                db_steps=get_query_refinement_steps(self._db, query_id),
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

        command_response = await command_response_builder(
            manager=self._manager,
            command_type=command_type,
            payload=command_payload,
            session=session,
            force_confirmation_needed=force_confirmation_needed,
            db=self._db,
            query_id=query_id,
            db_steps=get_query_refinement_steps(self._db, query_id),
        )
        self._session_manager.save_session(query_id, session)
        return command_response

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
