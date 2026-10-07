"""In-process bridge between the Chainlit UI and the persisted refinement workflow.

The Chainlit app calls the same ``RefinementApiService`` used by the REST API so
that chat sessions get the same access control, database persistence, audit
trail and session-state handling as API clients, without an HTTP hop.
"""

from __future__ import annotations

import logging
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Dict, Iterator, List, Optional

from query_refinement_module.api.config import get_settings
from query_refinement_module.api.dependencies import get_refinement_manager, get_session_manager
from query_refinement_module.api.exceptions import ResourceNotFoundError, UnauthorizedError
from query_refinement_module.api.refinement_schemas import SynthesizeQueryResponse
from query_refinement_module.audit import audit_service
from query_refinement_module.db.crud import (
    abandon_query_session,
    create_feedback,
    get_query_refinement_steps,
    get_user_framework_names,
    verify_user_password,
)
from query_refinement_module.db.models.audit_log import AuditEventType
from query_refinement_module.db.models.query import Query
from query_refinement_module.db.models.query_session import QuerySession
from query_refinement_module.db.models.user import User
from query_refinement_module.db.session import get_db_session
from query_refinement_module.schema.registry import list_frameworks
from query_refinement_module.tracing import generate_request_id, set_request_id

from .refinement_api_service import RefinementApiService


logger = logging.getLogger(__name__)

SOURCE = "chainlit"
EXPORT_VERSION = 1


def _new_request_id() -> str:
    request_id = generate_request_id()
    set_request_id(request_id)
    return request_id


class ChainlitRefinementAdapter:
    """Thin facade over ``RefinementApiService`` bound to one DB session."""

    def __init__(self, db, *, manager=None, session_manager=None, settings_factory=None) -> None:
        self.db = db
        self._settings_factory = settings_factory or get_settings
        self._service = RefinementApiService(
            manager=manager or get_refinement_manager(),
            db=db,
            session_manager=session_manager or get_session_manager(),
            settings_factory=self._settings_factory,
        )

    @classmethod
    @contextmanager
    def open(cls) -> Iterator["ChainlitRefinementAdapter"]:
        """Open an adapter with a fresh DB session that commits on success."""
        with get_db_session() as db:
            yield cls(db)

    # ------------------------------------------------------------------
    # Identity and access
    # ------------------------------------------------------------------

    def authenticate(self, identifier: str, password: str) -> Optional[User]:
        user = verify_user_password(self.db, identifier=identifier, password=password)
        if user is None:
            audit_service.log_from_request(
                db=self.db,
                request=None,
                event_type=AuditEventType.LOGIN_FAILURE,
                severity="warning",
                resource_type="user",
                action=f"Failed login attempt for: {identifier}",
                status="failure",
                details={"identifier": identifier, "reason": "invalid_credentials", "client": SOURCE},
            )
            return None
        audit_service.log_from_request(
            db=self.db,
            request=None,
            event_type=AuditEventType.LOGIN_SUCCESS,
            user=user,
            resource_type="user",
            resource_id=str(user.id),
            action=f"User logged in: {user.username}",
            details={"client": SOURCE},
        )
        return user

    def get_user(self, user_id: int) -> User:
        user = self.db.get(User, user_id)
        if user is None:
            raise UnauthorizedError("Your account no longer exists. Please log in again.")
        return user

    def list_frameworks(self, user: User) -> List[str]:
        names = sorted(list_frameworks())
        if user.is_superuser:
            return names
        allowed = set(get_user_framework_names(self.db, user.id))
        return [name for name in names if name in allowed]

    def workflow_limit_reached(self, user: User) -> bool:
        settings = self._settings_factory()
        return bool(settings.enforce_workflow_limit and not user.is_superuser and user.has_completed_workflow)

    # ------------------------------------------------------------------
    # Workflow
    # ------------------------------------------------------------------

    def find_resumable_query(self, user: User) -> Optional[Dict[str, Any]]:
        """Return the user's most recent unfinished query, if any."""
        row = (
            self.db.query(Query, QuerySession)
            .join(QuerySession, Query.session_id == QuerySession.id)
            .filter(
                QuerySession.user_id == user.id,
                QuerySession.status == "active",
                Query.refined_query.is_(None),
            )
            .order_by(Query.created_at.desc())
            .first()
        )
        if row is None:
            return None
        query, session = row
        return {
            "query_id": query.id,
            "session_id": session.id,
            "framework_name": session.framework_name,
            "original_query": query.original_query,
            "started_at": session.started_at,
        }

    async def start(self, user: User, *, framework_name: str, original_query: str) -> Dict[str, Any]:
        return await self._service.start_workflow(
            original_query=original_query,
            framework_name=framework_name,
            source=SOURCE,
            skip_refinement=False,
            current_user=user,
            request_id=_new_request_id(),
        )

    async def submit(self, user: User, *, query_id: int, text: str, force: bool = False) -> Dict[str, Any]:
        return await self._service.submit_answer(
            query_id=query_id,
            answer=text,
            force=force,
            current_user=user,
            http_request=None,
            request_id=_new_request_id(),
        )

    async def status(self, user: User, *, query_id: int) -> Dict[str, Any]:
        return await self._service.get_status_payload(
            query_id=query_id,
            current_user=user,
            request_id=_new_request_id(),
        )

    async def resume(self, user: User, *, query_id: int) -> Dict[str, Any]:
        return await self._service.resume_workflow(
            query_id=query_id,
            current_user=user,
            request_id=_new_request_id(),
        )

    async def synthesize(self, user: User, *, query_id: int) -> Dict[str, Any]:
        payload = await self._service.synthesize_workflow(
            query_id=query_id,
            include_expansion=True,
            current_user=user,
            request_id=_new_request_id(),
        )
        # Normalise pydantic objects inside structured_output into plain JSON
        return SynthesizeQueryResponse(**payload).model_dump(mode="json")

    async def abandon(self, user: User, *, session_id: int) -> Dict[str, Any]:
        return await self._service.abandon_session_workflow(
            session_id=session_id,
            current_user=user,
            http_request=None,
            request_id=_new_request_id(),
        )

    # ------------------------------------------------------------------
    # Export and feedback
    # ------------------------------------------------------------------

    def _get_owned_query(self, user: User, query_id: int) -> Query:
        query = self.db.get(Query, query_id)
        if query is None or query.session.user_id != user.id:
            raise ResourceNotFoundError("Query", query_id)
        return query

    def build_trace(self, user: User, *, query_id: int) -> List[Dict[str, Any]]:
        """Per-dimension record of what was asked, answered and accepted."""
        self._get_owned_query(user, query_id)
        trace = []
        for step in get_query_refinement_steps(self.db, query_id):
            trace.append(
                {
                    "aspect_id": step.aspect_id,
                    "aspect_name": step.aspect_name,
                    "final_value": step.final_value,
                    "is_complete": step.is_complete,
                    "was_skipped": step.was_skipped,
                    "user_ended_early": step.user_ended_early,
                    "turns": [
                        {
                            "question": followup.question,
                            "answer": followup.answer,
                            "at": followup.created_at.isoformat() if followup.created_at else None,
                        }
                        for followup in sorted(step.followup_history, key=lambda item: item.id)
                    ],
                }
            )
        return trace

    def build_export(self, user: User, *, query_id: int, synthesis: Dict[str, Any]) -> Dict[str, Any]:
        query = self._get_owned_query(user, query_id)
        command_history = self._service.get_command_history_payload(
            query_id=query_id,
            limit=200,
            current_user=user,
        )
        return {
            "export_version": EXPORT_VERSION,
            "exported_at": datetime.now(timezone.utc).isoformat(),
            "source": SOURCE,
            "query_id": query_id,
            "framework": query.session.framework_name,
            "original_query": query.original_query,
            "synthesis": synthesis,
            "refinement_trace": self.build_trace(user, query_id=query_id),
            "superseded_answers": self.superseded_answers(query_id=query_id),
            "command_history": command_history.get("commands", command_history),
        }

    def superseded_answers(self, *, query_id: int) -> List[Dict[str, Any]]:
        """Answers replaced via /back, /restart or /clear, archived in the audit log."""
        from query_refinement_module.db.models.audit_log import AuditLog

        logs = (
            self.db.query(AuditLog)
            .filter(
                AuditLog.event_type == AuditEventType.REFINEMENT_STEP,
                AuditLog.resource_type == "query",
                AuditLog.resource_id == str(query_id),
            )
            .order_by(AuditLog.id)
            .all()
        )
        return [
            {"command": (log.details or {}).get("command"), "at": log.timestamp.isoformat() if log.timestamp else None,
             "dimensions": (log.details or {}).get("superseded", [])}
            for log in logs
        ]

    def save_feedback(
        self,
        user: User,
        *,
        query_id: int,
        rating: Optional[int],
        comments: Optional[str],
        metadata: Dict[str, Any],
        consent: bool,
    ) -> int:
        """Store survey feedback and consent, mirroring ``POST /feedback``."""
        query = self._get_owned_query(user, query_id)
        if self._settings_factory().enforce_workflow_limit and not user.is_superuser:
            user.has_completed_workflow = True
        if consent:
            query.consent_given = True
            query.consent_given_at = datetime.now(timezone.utc)
        self.db.commit()
        feedback = create_feedback(
            self.db,
            user_id=user.id,
            query_id=query_id,
            rating=rating,
            comments=comments,
            additional_metadata=metadata,
        )
        return feedback.id
