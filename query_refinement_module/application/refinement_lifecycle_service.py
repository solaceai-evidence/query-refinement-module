"""Lifecycle and synthesis workflows for refinement sessions."""

from __future__ import annotations

import json
import logging
import time
from typing import Any, Dict, Optional

from query_refinement_module.api.exceptions import QueryRefinementException
from query_refinement_module.audit import audit_service
from query_refinement_module.core import UserCommand, is_user_command, parse_user_command
from query_refinement_module.db.crud import (
    create_followup,
    create_query,
    create_query_session,
    create_refinement_step,
    delete_refinement_steps_by_aspects,
    get_query_refinement_steps,
    mark_refinement_step_skipped,
    mark_refinement_step_user_ended_early,
    reset_refinement_step,
    save_query_refinement_response,
    update_refinement_step_final_value,
)
from query_refinement_module.db.models.audit_log import AuditEventType
from query_refinement_module.models.progress import ProgressStage
from query_refinement_module.schema import DimensionEvaluationResponse
from query_refinement_module.schema.prompt_builder import PromptBuilder
from query_refinement_module.schema.response import SearchExpansionInput

from .refinement_service_support import RefinementServiceSupport
from .refinement_workflow import (
    build_next_prompt,
    build_status_payload,
    find_db_step_for_aspect,
    get_active_prompt,
    is_session_ready_for_synthesis,
    persist_generated_question,
)


logger = logging.getLogger(__name__)


class RefinementLifecycleService:
    """Owns session lifecycle, command handling, and synthesis orchestration."""

    def __init__(self, support: RefinementServiceSupport) -> None:
        self._support = support

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
        self._support.require_start_permissions(current_user=current_user, framework_name=framework_name)

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

        framework = self._support.get_framework_or_raise(framework_name)
        session = await self._support.initialize_session(original_query=original_query, framework=framework)

        db_session = create_query_session(self._support.db, user_id=current_user.id, framework_name=framework_name)
        db_query = create_query(self._support.db, session_id=db_session.id, original_query=original_query)

        tracker = self._support.progress_tracker_factory()
        try:
            await tracker.create(
                query_id=str(db_query.id),
                initial_stage=ProgressStage.EXTRACTING_ASPECTS,
                initial_message=f"Analyzing query structure with {framework_name} framework...",
            )
        except Exception as exc:  # pragma: no cover
            logger.error("Failed to create progress tracking: %s", exc, exc_info=True)

        for step in session.steps:
            create_refinement_step(
                self._support.db,
                query_id=db_query.id,
                aspect_name=step.refinement_aspect.name,
                aspect_id=step.refinement_aspect.id,
            )

        if skip_refinement:
            for step in session.steps:
                step.is_complete = True
                step.was_skipped = True
            session.synthesis_requested = True

            db_steps = get_query_refinement_steps(self._support.db, db_query.id)
            for db_step in db_steps:
                mark_refinement_step_skipped(self._support.db, db_step.id)

            self._support.session_manager.save_session(db_query.id, session)
            await self._support.progress_fn(
                query_id=str(db_query.id),
                stage=ProgressStage.SUGGESTIONS_READY,
                message="All refinements skipped, proceeding to synthesis",
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

        await self._support.progress_fn(
            query_id=str(db_query.id),
            stage=ProgressStage.ASPECTS_EXTRACTED,
            message=f"Identified {len(session.steps)} aspects to refine",
            aspects_count=len(session.steps),
            details={"framework": framework_name},
        )
        await self._support.progress_fn(
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

        db_steps = get_query_refinement_steps(self._support.db, db_query.id)
        next_prompt = await build_next_prompt(self._support.manager, session, db=self._support.db, db_steps=db_steps)
        persist_generated_question(self._support.db, db_steps, next_prompt)
        ready_for_synthesis = next_prompt is None and session.is_complete()

        if next_prompt:
            suggestions_count = len([step for step in session.steps if not step.is_complete])
            await self._support.progress_fn(
                query_id=str(db_query.id),
                stage=ProgressStage.SUGGESTIONS_READY,
                message="Refinement suggestions ready",
                suggestions_count=suggestions_count,
            )
            await self._support.progress_fn(
                query_id=str(db_query.id),
                stage=ProgressStage.WAITING_FOR_USER,
                message=f"Waiting for your input on '{next_prompt.get('name', 'aspect')}'",
                details={"current_aspect": next_prompt.get("name")},
            )
        elif ready_for_synthesis:
            await self._support.progress_fn(
                query_id=str(db_query.id),
                stage=ProgressStage.SUGGESTIONS_READY,
                message="All aspects refined, ready for synthesis",
            )

        self._support.session_manager.save_session(db_query.id, session)

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
        db_query = self._support.get_query_for_user(query_id=query_id, current_user=current_user)

        framework_name = db_query.session.framework_name
        if not framework_name:
            raise QueryRefinementException("Framework name not found for session", status_code=400)
        framework = self._support.get_framework_or_raise(framework_name)

        try:
            async with self._support.session_manager.session_lock(query_id):
                session = self._support.session_manager.load_session(query_id, framework)
                if not session:
                    session = await self._support.reconstruct_session_from_db(
                        query_id=query_id,
                        db_query=db_query,
                        framework=framework,
                    )

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

    async def get_status_payload(self, *, query_id: int, current_user, request_id: str) -> Dict[str, Any]:
        start_time = time.time()
        db_query = self._support.get_query_for_user(query_id=query_id, current_user=current_user)
        if db_query.refined_query and db_query.refined_query.strip():
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

        framework = self._support.get_framework_or_raise(framework_name)
        session = await self._support.load_or_reconstruct_session(query_id=query_id, db_query=db_query, framework=framework)
        summary = self._support.manager.get_initialization_summary(session)
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
        db_query = self._support.get_query_for_user(query_id=query_id, current_user=current_user)

        framework_name = db_query.session.framework_name
        if not framework_name:
            raise QueryRefinementException("Framework name not found for session", status_code=400)
        framework = self._support.get_framework_or_raise(framework_name)

        try:
            async with self._support.session_manager.session_lock(query_id):
                session = self._support.session_manager.load_session(query_id, framework)
                if not session:
                    session = await self._support.reconstruct_session_from_db(
                        query_id=query_id,
                        db_query=db_query,
                        framework=framework,
                    )
                    db_steps = get_query_refinement_steps(self._support.db, query_id)
                else:
                    db_steps = get_query_refinement_steps(self._support.db, query_id)

                if not session.synthesis_requested and get_active_prompt(session) is None:
                    next_prompt = await build_next_prompt(self._support.manager, session, db=self._support.db, db_steps=db_steps)
                    persist_generated_question(self._support.db, db_steps, next_prompt)

                self._support.session_manager.save_session(query_id, session)
        except RuntimeError as exc:
            logger.warning("Could not acquire session lock for query %d during resume: %s", query_id, exc)
            raise QueryRefinementException(
                "Session is temporarily locked by another request. Please retry in a moment.",
                status_code=503,
            ) from exc

        summary = self._support.manager.get_initialization_summary(session)
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

        db_query = self._support.get_query_for_user(query_id=query_id, current_user=current_user)
        framework_name = db_query.session.framework_name
        if not framework_name:
            raise QueryRefinementException("Framework name not found for session", status_code=400)
        framework = self._support.get_framework_or_raise(framework_name)

        try:
            async with self._support.session_manager.session_lock(query_id):
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

    async def _submit_answer_locked(self, *, query_id: int, answer: str, force: bool, http_request, current_user, db_query, framework, request_id: str, start_time: float, is_command: bool) -> Any:
        session = self._support.session_manager.load_session(query_id, framework)
        if not session:
            session = await self._support.reconstruct_session_from_db(
                query_id=query_id,
                db_query=db_query,
                framework=framework,
            )
            self._support.session_manager.save_session(query_id, session)

        user_input = answer.strip()
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

        await self._support.progress_fn(
            query_id=str(query_id),
            stage=ProgressStage.USER_REFINING,
            message=f"Processing your input for '{active_step.refinement_aspect.name}'...",
            details={"aspect": active_step.refinement_aspect.name},
        )

        try:
            tracker = self._support.progress_tracker_factory()
            await tracker.increment_llm_calls(str(query_id))
            analysis_result = await self._support.manager.get_analysis_prompts(
                session=session,
                aspect_id=active_step.refinement_aspect.id,
                mode="followup",
            )
            analysis_status = self._support.manager.process_analysis_result(
                session=session,
                aspect_id=active_step.refinement_aspect.id,
                result=analysis_result,
            )
        except ConnectionError as exc:
            raise QueryRefinementException(f"Unable to connect to LLM service: {str(exc)}", status_code=503) from exc
        except TimeoutError as exc:
            raise QueryRefinementException(f"LLM service request timed out: {str(exc)}", status_code=504) from exc
        except Exception as exc:
            raise QueryRefinementException(f"Failed to process answer: {str(exc)}", status_code=500) from exc

        db_steps = get_query_refinement_steps(self._support.db, query_id)
        db_step = find_db_step_for_aspect(db_steps, active_step.refinement_aspect)
        if not db_step:
            db_step = create_refinement_step(
                self._support.db,
                query_id=query_id,
                aspect_name=active_step.refinement_aspect.name,
                aspect_id=active_step.refinement_aspect.id,
            )

        db_followup = create_followup(
            self._support.db,
            refinement_step_id=db_step.id,
            question=active_step.follow_up_question or active_step.refinement_aspect.name,
            answer=user_input,
        )
        followup_id = db_followup.id
        is_complete = analysis_status.get("complete", False)

        if is_complete and active_step.normalized_value:
            update_refinement_step_final_value(
                self._support.db,
                step_id=db_step.id,
                final_value=active_step.normalized_value_as_str,
                is_complete=True,
                was_skipped=False,
                user_ended_early=False,
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
            next_prompt = await build_next_prompt(self._support.manager, session, db=self._support.db, db_steps=db_steps)
            persist_generated_question(self._support.db, db_steps, next_prompt)

        self._support.session_manager.save_session(query_id, session)
        ready_for_synthesis = next_prompt is None and session.is_complete()

        return {
            "refinement_step_id": db_step.id,
            "followup_id": followup_id,
            "is_complete": is_complete,
            "next_prompt": next_prompt,
            "ready_for_synthesis": ready_for_synthesis,
        }

    async def _handle_command(self, *, query_id: int, user_input: str, force: bool, http_request, current_user, session) -> Any:
        cmd_result = parse_user_command(user_input)

        if not cmd_result.is_valid:
            return await self._build_command_response_payload(
                command_type=cmd_result.command.value,
                payload={"success": False, "message": cmd_result.error_message or "Invalid command"},
                session=session,
                force_confirmation_needed=False,
                query_id=query_id,
            )

        pre_command_active_step = session.get_active_step()
        command_payload = session.handle_command(cmd_result)
        command_type = cmd_result.command.value

        force_confirmation_needed = False
        if not force and command_type in {UserCommand.BACK.value, UserCommand.PREVIOUS.value, UserCommand.RESTART.value}:
            invalidated = command_payload.get("invalidated", [])
            if invalidated and command_payload.get("success", False):
                force_confirmation_needed = True
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
            db=self._support.db,
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
        self._support.session_manager.save_session(query_id, session)
        return command_response

    async def _build_command_response_payload(self, *, command_type: str, payload: Dict[str, Any], session, force_confirmation_needed: bool = False, query_id: Optional[int] = None) -> Dict[str, Any]:
        response: Dict[str, Any] = {
            "command_type": command_type,
            "success": payload.get("success", False),
            "message": payload.get("message", ""),
            "next_prompt": None,
            "invalidated_aspects": None,
            "synthesis_ready": False,
            "step_summary": None,
            "step_list": None,
            "force_required": None,
        }

        db_steps = get_query_refinement_steps(self._support.db, query_id) if query_id is not None else []

        if not response["success"] or force_confirmation_needed:
            response["next_prompt"] = get_active_prompt(session) or await build_next_prompt(
                self._support.manager,
                session,
                db=self._support.db,
                db_steps=db_steps,
            )
            persist_generated_question(self._support.db, db_steps, response["next_prompt"])
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
            response["next_prompt"] = await build_next_prompt(self._support.manager, session, db=self._support.db, db_steps=db_steps)
            persist_generated_question(self._support.db, db_steps, response["next_prompt"])
        elif command_type in {UserCommand.BACK.value, UserCommand.PREVIOUS.value, UserCommand.RESTART.value}:
            response["invalidated_aspects"] = payload.get("invalidated", [])
            if command_type in {UserCommand.BACK.value, UserCommand.RESTART.value}:
                await self._ensure_reopened_step_question(session=session)
            response["next_prompt"] = await build_next_prompt(self._support.manager, session, db=self._support.db, db_steps=db_steps)
            persist_generated_question(self._support.db, db_steps, response["next_prompt"])
        elif command_type in {UserCommand.SKIP.value, UserCommand.DONE.value}:
            response["next_prompt"] = await build_next_prompt(self._support.manager, session, db=self._support.db, db_steps=db_steps)
            persist_generated_question(self._support.db, db_steps, response["next_prompt"])
            if response["next_prompt"] is None and session.is_complete():
                response["synthesis_ready"] = True

        if not response["synthesis_ready"]:
            response["synthesis_ready"] = is_session_ready_for_synthesis(session)

        return response

    async def _ensure_reopened_step_question(self, *, session) -> None:
        reopened_step = session.get_active_step()
        if not reopened_step or reopened_step.follow_up_question:
            return

        prompt_builder = PromptBuilder()
        aspect = reopened_step.refinement_aspect

        try:
            messages = prompt_builder.build_refinement_messages(
                dimension=aspect,
                query=session.original_query,
                conversation_history=[],
                dependency_context=session.get_dependency_context(aspect.id),
                completed_context=session.get_completed_context(aspect.id),
                terminal_reinforcement_threshold=getattr(self._support.manager, "terminal_reinforcement_threshold", 3),
            )
            if messages and messages[-1].get("role") == "user":
                messages[-1]["content"] += (
                    "\n\nCRITICAL: The user has navigated back to review this dimension from scratch. "
                    "The dimension has been completely reset with no previous values. You MUST ask a "
                    "clarifying question as if this is the very first time asking about this dimension. "
                    "Do NOT assume anything is already clear - treat this as a fresh initial question."
                )

            llm_result = await self._support.manager.llm_provider.complete_async(
                messages=messages,
                temperature=0.0,
                response_format=DimensionEvaluationResponse,
                cache_system_prompt=True,
            )
            generated_question = self._extract_generated_question(llm_result.context)
            if generated_question:
                reopened_step.follow_up_question = generated_question
                return
        except Exception:
            pass

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

    async def _run_synthesis(self, *, session, db_query, current_user, query_id: int, request_id: str, include_expansion: bool = False) -> Dict[str, Any]:
        tracker = self._support.progress_tracker_factory()

        await self._support.progress_fn(
            query_id=str(query_id),
            stage=ProgressStage.SYNTHESIZING,
            message="Synthesizing final refined query...",
            details={"framework": db_query.session.framework_name},
        )

        try:
            await tracker.increment_llm_calls(str(query_id))
            synthesis_result = await self._support.manager.synthesize_refined_query(session)
        except Exception as exc:
            await self._support.progress_fn(
                query_id=str(query_id),
                stage=ProgressStage.FAILED,
                message="Synthesis failed",
                error=str(exc),
            )
            raise QueryRefinementException(f"Failed to synthesize query: {str(exc)}", status_code=500) from exc

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
            raise QueryRefinementException("Synthesis produced empty result. Please try again.", status_code=500)

        settings = self._support.settings_factory()
        if settings.enforce_workflow_limit and not current_user.is_superuser:
            current_user.has_completed_workflow = True

        save_query_refinement_response(
            self._support.db,
            query_id,
            {
                "clarified_query": clarified_query,
                "dimensions_specifications": structured_output.get("dimensions_specifications") if structured_output else synthesis_result.get("dimensions_specifications"),
                "search_optimized": structured_output.get("search_optimized") if structured_output else synthesis_result.get("search_optimized"),
                "search_filters": structured_output.get("search_filters") if structured_output else synthesis_result.get("search_filters"),
                "terminology": structured_output.get("terminology") if structured_output else synthesis_result.get("terminology"),
                "metadata": synthesis_result.get("metadata"),
                "processing_log": synthesis_result.get("processing_log"),
            },
        )

        await self._support.progress_fn(query_id=str(query_id), stage=ProgressStage.SYNTHESIS_COMPLETE, message="Synthesis completed successfully")
        self._support.session_manager.delete_session(query_id)
        await self._support.progress_fn(query_id=str(query_id), stage=ProgressStage.COMPLETED, message="Refinement completed successfully")

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
                    exp_result, exp_meta = await self._support.manager.generate_search_expansion_levels(search_input=exp_input)
                    expansion_levels = [level.model_dump(by_alias=True) for level in exp_result.levels]
                    expansion_metadata = {
                        "geography_broadening_strategy": exp_result.geography_broadening_strategy,
                        "recommended_starting_level": exp_result.recommended_starting_level,
                        "recommendation_rationale": exp_result.recommendation_rationale,
                        **exp_meta,
                    }
                except Exception:
                    pass

        return {
            "query_id": query_id,
            "clarified_query": clarified_query,
            "integrated_statement": clarified_query,
            "used_llm": synthesis_result.get("used_llm", False),
            "structured_output": structured_output,
            "expansion_levels": expansion_levels,
            "expansion_metadata": expansion_metadata,
        }

    def _extract_structured_output_from_query_string(self, *, clarified_query: str, request_id: str) -> tuple[Optional[Dict[str, Any]], str]:
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
        except (json.JSONDecodeError, ValueError):
            pass
        return structured_output, current_query

    async def _persist_command_side_effects(self, *, query_id: int, command_type: str, session, command_payload: Dict[str, Any], pre_command_active_step) -> None:
        if command_type not in {UserCommand.BACK.value, UserCommand.PREVIOUS.value, UserCommand.RESTART.value, UserCommand.SKIP.value, UserCommand.DONE.value, UserCommand.SUBMIT.value}:
            return

        if command_type in {UserCommand.BACK.value, UserCommand.PREVIOUS.value, UserCommand.RESTART.value}:
            cleared_aspects = command_payload.get("cleared_aspects", [])
            if cleared_aspects:
                delete_refinement_steps_by_aspects(self._support.db, query_id=query_id, aspect_names=cleared_aspects)

            if command_type in {UserCommand.BACK.value, UserCommand.PREVIOUS.value}:
                reopened_step = session.get_active_step()
                if reopened_step:
                    db_steps = get_query_refinement_steps(self._support.db, query_id)
                    db_step = find_db_step_for_aspect(db_steps, reopened_step.refinement_aspect)
                    if db_step:
                        reset_refinement_step(self._support.db, step_id=db_step.id, clear_followup_history=True)

        if command_type == UserCommand.CLEAR.value:
            active_step = session.get_active_step()
            if active_step:
                db_steps = get_query_refinement_steps(self._support.db, query_id)
                db_step = find_db_step_for_aspect(db_steps, active_step.refinement_aspect)
                if db_step:
                    reset_refinement_step(self._support.db, step_id=db_step.id, clear_followup_history=True)

        if command_type in {UserCommand.SKIP.value, UserCommand.DONE.value}:
            command_step = pre_command_active_step or command_payload.get("step")
            if command_step and command_step.is_complete:
                db_steps = get_query_refinement_steps(self._support.db, query_id)
                db_step = find_db_step_for_aspect(db_steps, command_step.refinement_aspect)
                if db_step:
                    if command_type == UserCommand.SKIP.value:
                        mark_refinement_step_skipped(self._support.db, db_step.id)
                    else:
                        mark_refinement_step_user_ended_early(
                            self._support.db,
                            step_id=db_step.id,
                            final_value=command_step.normalized_value_as_str if command_step.normalized_value_as_str else None,
                        )

        self._support.session_manager.save_session(query_id, session)