"""Command side effects: /status counts and archive-before-delete traceability."""

from types import SimpleNamespace

import pytest

from query_refinement_module.application.refinement_api_service import RefinementApiService
from query_refinement_module.core import parse_user_command
from query_refinement_module.db.crud import (
    create_followup,
    create_query,
    create_query_session,
    create_refinement_step,
    create_user,
    get_query_refinement_steps,
)
from query_refinement_module.db.models.audit_log import AuditLog
from query_refinement_module.schema.models import RefinementAspect
from query_refinement_module.session_models import RefinementSession


def _session(*ids):
    session = RefinementSession(original_query="q")
    aspects = [RefinementAspect(id=i, name=i.title(), description=i) for i in ids]
    session._complete_framework = aspects
    for aspect in aspects:
        session.add_step(aspect)
    return session


def test_status_reports_remaining_dimensions():
    session = _session("population", "intervention", "outcome")
    session.steps[0].is_complete = True

    payload = session.handle_command(parse_user_command("/status"))

    assert payload["summary"]["pending_steps"] == 2
    assert "(2 remaining)" in payload["message"]


@pytest.mark.asyncio
async def test_clear_archives_answers_before_resetting_step(test_db_session):
    db = test_db_session
    user = create_user(db, username="u", password="pass-1234")
    query = create_query(db, session_id=create_query_session(db, user_id=user.id, framework_name="f").id, original_query="q")
    db_step = create_refinement_step(db, query_id=query.id, aspect_name="Population", aspect_id="population")
    create_followup(db, refinement_step_id=db_step.id, question="Which adults?", answer="Adults over 40")

    session = _session("population")
    service = RefinementApiService(
        manager=SimpleNamespace(),
        db=db,
        session_manager=SimpleNamespace(save_session=lambda *a, **k: None),
        settings_factory=lambda: SimpleNamespace(enforce_workflow_limit=False),
    )

    await service._persist_command_side_effects(
        query_id=query.id,
        command_type="clear",
        session=session,
        command_payload={"success": True},
        pre_command_active_step=session.steps[0],
    )

    assert get_query_refinement_steps(db, query.id)[0].followup_history == []
    archive = db.query(AuditLog).filter(AuditLog.event_type == "refinement.step").one()
    turns = archive.details["superseded"][0]["turns"]
    assert turns[0]["question"] == "Which adults?"
    assert turns[0]["answer"] == "Adults over 40"


def test_accumulate_metadata_tolerates_missing_usage():
    from query_refinement_module.core import QueryRefinementManager

    combined = QueryRefinementManager._accumulate_metadata({"prompt_tokens": None, "total_tokens": 5}, {"prompt_tokens": 3, "total_tokens": None})
    assert combined["prompt_tokens"] == 3
    assert combined["total_tokens"] == 5
