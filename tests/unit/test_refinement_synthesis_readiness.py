from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from query_refinement_module.api.routes import refinement as refinement_routes
from query_refinement_module.api.routes.refinement import (
    _is_session_ready_for_synthesis,
    _build_command_response,
    ForwardToQARequest,
)
from query_refinement_module.db.crud import create_query, create_query_session, create_user


class _FakeSession:
    def __init__(self, synthesis_requested: bool, complete: bool):
        self.synthesis_requested = synthesis_requested
        self._complete = complete

    def is_complete(self):
        return self._complete

    def get_active_step(self):
        return None


def test_is_session_ready_for_synthesis_false_for_none_session():
    assert _is_session_ready_for_synthesis(None) is False


def test_is_session_ready_for_synthesis_true_when_submit_requested():
    session = _FakeSession(synthesis_requested=True, complete=False)
    assert _is_session_ready_for_synthesis(session) is True


def test_is_session_ready_for_synthesis_true_when_complete():
    session = _FakeSession(synthesis_requested=False, complete=True)
    assert _is_session_ready_for_synthesis(session) is True


@pytest.mark.asyncio
async def test_status_command_response_sets_explicit_synthesis_ready_false_when_not_ready():
    session = _FakeSession(synthesis_requested=False, complete=False)

    response = await _build_command_response(
        manager=None,
        command_type="status",
        payload={"success": True, "message": "ok", "summary": {"completed": 1}},
        session=session,
        force_confirmation_needed=False,
        db=None,
        query_id=1,
        db_steps=[],
    )

    assert response.success is True
    assert response.command_type == "status"
    assert response.synthesis_ready is False


@pytest.mark.asyncio
async def test_status_command_response_sets_synthesis_ready_true_when_ready():
    session = _FakeSession(synthesis_requested=True, complete=False)

    response = await _build_command_response(
        manager=None,
        command_type="status",
        payload={"success": True, "message": "ok", "summary": {"completed": 6}},
        session=session,
        force_confirmation_needed=False,
        db=None,
        query_id=1,
        db_steps=[],
    )

    assert response.synthesis_ready is True


def test_forward_to_qa_request_rejects_invalid_url():
    with pytest.raises(ValidationError):
        ForwardToQARequest(qa_system_url="not-a-url")


class _FakeTracker:
    def __init__(self):
        self.calls = []

    async def increment_llm_calls(self, query_id: str):
        self.calls.append(query_id)


class _FakeSessionManager:
    def __init__(self):
        self.deleted = []

    def delete_session(self, query_id: int):
        self.deleted.append(query_id)


class _FakeManager:
    async def synthesize_refined_query(self, session):
        return {
            "integrated_statement": "Adults with COPD receiving pulmonary rehab.",
            "dimensions_specifications": {"population": "Adults with COPD"},
            "search_optimized": {"semantic": "pulmonary rehabilitation for COPD adults"},
            "search_filters": {"publication_types": ["Systematic review"]},
            "terminology": {"synonyms": {"COPD": ["chronic obstructive pulmonary disease"]}},
            "metadata": {"total_tokens": 1234},
            "processing_log": {"preserved": ["population"]},
            "used_llm": True,
        }


@pytest.mark.asyncio
async def test_run_synthesis_persists_full_response_payload(test_db_session, monkeypatch):
    tracker = _FakeTracker()
    session_manager = _FakeSessionManager()
    progress_updates = []

    async def _track_progress(**kwargs):
        progress_updates.append(kwargs)

    monkeypatch.setattr(refinement_routes, "get_progress_tracker", lambda: tracker)
    monkeypatch.setattr(refinement_routes, "track_progress", _track_progress)
    monkeypatch.setattr(
        refinement_routes,
        "get_settings",
        lambda: SimpleNamespace(enforce_workflow_limit=True),
    )

    import query_refinement_module.services.webhook_service as webhook_service

    monkeypatch.setattr(webhook_service, "dispatch_webhook_event_async", lambda *args, **kwargs: None)
    monkeypatch.setattr(webhook_service, "build_synthesis_started_payload", lambda **kwargs: {})
    monkeypatch.setattr(webhook_service, "build_synthesis_complete_payload", lambda **kwargs: {})

    user = create_user(
        test_db_session,
        username="synth_user",
        password="TestPass123!",
        email="synth@test.com",
        name="Synth User",
    )
    db_session = create_query_session(test_db_session, user_id=user.id, framework_name="pico_advanced")
    db_query = create_query(
        test_db_session,
        session_id=db_session.id,
        original_query="effects of pulmonary rehabilitation in COPD",
    )

    response = await refinement_routes._run_synthesis(
        manager=_FakeManager(),
        session=SimpleNamespace(),
        db=test_db_session,
        db_query=db_query,
        current_user=user,
        session_manager=session_manager,
        query_id=db_query.id,
        request_id="req-test",
    )

    test_db_session.refresh(user)
    test_db_session.refresh(db_query)

    assert response.integrated_statement == "Adults with COPD receiving pulmonary rehab."
    assert response.structured_output == {
        "dimensions_specifications": {"population": "Adults with COPD"},
        "search_optimized": {"semantic": "pulmonary rehabilitation for COPD adults"},
        "search_filters": {"publication_types": ["Systematic review"]},
        "terminology": {"synonyms": {"COPD": ["chronic obstructive pulmonary disease"]}},
    }
    assert db_query.refined_query == "Adults with COPD receiving pulmonary rehab."
    assert db_query.synthesized_statement == "Adults with COPD receiving pulmonary rehab."
    assert db_query.refined_dimensions == {"population": "Adults with COPD"}
    assert db_query.search_optimized == {"semantic": "pulmonary rehabilitation for COPD adults"}
    assert db_query.search_filters == {"publication_types": ["Systematic review"]}
    assert db_query.terminology == {
        "synonyms": {"COPD": ["chronic obstructive pulmonary disease"]}
    }
    assert db_query.response_metadata == {"total_tokens": 1234}
    assert db_query.processing_log == {"preserved": ["population"]}
    assert db_query.completed_at is not None
    assert user.has_completed_workflow is True
    assert tracker.calls == [str(db_query.id)]
    assert session_manager.deleted == [db_query.id]
    assert any(update["stage"] == refinement_routes.ProgressStage.COMPLETED for update in progress_updates)
