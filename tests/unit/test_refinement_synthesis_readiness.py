from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from query_refinement_module.api.routes.refinement import (
    _is_session_ready_for_synthesis,
    _build_command_response,
    ForwardToQARequest,
)


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
