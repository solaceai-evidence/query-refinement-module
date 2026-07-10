"""Utility workflows exposed by the refinement API."""

from __future__ import annotations

import logging
import time
from typing import Any, Dict

from query_refinement_module.api.exceptions import QueryRefinementException, ResourceNotFoundError, UnauthorizedError
from query_refinement_module.audit import audit_service
from query_refinement_module.db.crud import abandon_query_session, get_query, get_query_refinement_steps, get_query_session
from query_refinement_module.db.models.audit_log import AuditEventType
from query_refinement_module.models.progress import ProgressStage, ProgressStatus
from query_refinement_module.settings import LLMSettings

from .refinement_service_support import RefinementServiceSupport


logger = logging.getLogger(__name__)


class RefinementUtilityService:
    """Owns non-core refinement workflows exposed as auxiliary API endpoints."""

    def __init__(self, support: RefinementServiceSupport) -> None:
        self._support = support

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
        start_time = time.time()
        db_query = self._support.get_query_for_user(query_id=query_id, current_user=current_user)
        if not db_query.refined_query:
            raise QueryRefinementException(
                "Query has not been synthesized yet. Complete refinement and synthesis first.",
                status_code=400,
            )

        qa_payload = {"refined_query": db_query.refined_query}
        if forward_original_query:
            qa_payload["original_query"] = db_query.original_query

        if include_refinement_metadata:
            refinement_steps = get_query_refinement_steps(self._support.db, query_id=query_id)
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
            logger.error(
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
        logger.info(
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

        query = self._support.get_query_for_user(query_id=query_id, current_user=current_user)
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
        audit_logs = self._support.db.query(AuditLog).filter(
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
        query = get_query(self._support.db, query_id)
        if not query or query.session.user_id != current_user.id:
            raise ResourceNotFoundError("Query", query_id)

        session = self._support.session_manager.load_session(query_id)
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
            result = abandon_query_session(self._support.db, session_id, current_user.id)
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
                db=self._support.db,
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
        query = get_query(self._support.db, query_id)
        if not query:
            raise ResourceNotFoundError("Query", query_id)

        if query.session_id:
            query_session = get_query_session(self._support.db, query.session_id)
            if query_session and query_session.user_id != current_user.id:
                raise UnauthorizedError("Not authorized to view this query's progress")

        tracker = self._support.progress_tracker_factory()
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