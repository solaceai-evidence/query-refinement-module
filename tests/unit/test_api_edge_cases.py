"""
Regression tests for critical API integration edge cases.

Covers:
- /ready endpoint is exempt from rate limiting
- Synthesis guard (409) blocks premature /synthesize
- ForwardToQA URL validation
- Register.jsx username rules are consistent with backend schema
"""
import re
from pathlib import Path

import pytest
from pydantic import ValidationError

ROOT = Path(__file__).resolve().parents[2]


# ---------------------------------------------------------------------------
# 1. Backend: /ready endpoint is exempt from the rate limiter
# ---------------------------------------------------------------------------

MAIN_FILE = ROOT / "query_refinement_module" / "api" / "main.py"


def test_ready_endpoint_in_rate_limiter_exempt_paths():
    """/ready must appear in exempt_paths so health probes are never rate-limited."""
    source = MAIN_FILE.read_text(encoding="utf-8")
    # Find the exempt_paths= kwarg line
    match = re.search(r'exempt_paths=\[([^\]]+)\]', source)
    assert match, "Could not find exempt_paths= in main.py"
    paths_str = match.group(1)
    assert '"/ready"' in paths_str or "'/ready'" in paths_str, (
        "/ready should be in the rate-limiter exempt_paths list"
    )


# ---------------------------------------------------------------------------
# 3. Synthesis guard: _is_session_ready_for_synthesis correctness
# ---------------------------------------------------------------------------

from query_refinement_module.api.routes.refinement import (
    _is_session_ready_for_synthesis,
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


def test_synthesis_guard_none_session():
    assert _is_session_ready_for_synthesis(None) is False


def test_synthesis_guard_incomplete_session():
    session = _FakeSession(synthesis_requested=False, complete=False)
    assert _is_session_ready_for_synthesis(session) is False


def test_synthesis_guard_synthesis_requested():
    session = _FakeSession(synthesis_requested=True, complete=False)
    assert _is_session_ready_for_synthesis(session) is True


def test_synthesis_guard_all_complete():
    session = _FakeSession(synthesis_requested=False, complete=True)
    assert _is_session_ready_for_synthesis(session) is True


# ---------------------------------------------------------------------------
# 4. ForwardToQARequest validates URL scheme
# ---------------------------------------------------------------------------

def test_forward_to_qa_invalid_url_raises():
    with pytest.raises(ValidationError):
        ForwardToQARequest(qa_system_url="not-a-url")


def test_forward_to_qa_ftp_url_raises():
    with pytest.raises(ValidationError):
        ForwardToQARequest(qa_system_url="ftp://example.com/qa")


def test_forward_to_qa_valid_https_url():
    req = ForwardToQARequest(qa_system_url="https://qa.example.com/api")
    assert req is not None


def test_forward_to_qa_valid_http_url():
    req = ForwardToQARequest(qa_system_url="http://external-qa.example.com/qa")
    assert req is not None


# ---------------------------------------------------------------------------
# 5. CommandResponse.synthesis_ready is always a bool (no None)
# ---------------------------------------------------------------------------

from query_refinement_module.api.routes.refinement import CommandResponse


def test_command_response_synthesis_ready_defaults_to_false():
    resp = CommandResponse(command_type="status", success=True, message="ok")
    assert resp.synthesis_ready is False
    assert isinstance(resp.synthesis_ready, bool)


def test_command_response_synthesis_ready_cannot_be_none():
    """synthesis_ready is a strict bool field; passing None must be rejected by Pydantic."""
    with pytest.raises(ValidationError):
        CommandResponse(command_type="status", success=True, message="ok", synthesis_ready=None)


# ---------------------------------------------------------------------------
# 6. Frontend: isSynthesizingRef guard exists in Refinement.jsx
# ---------------------------------------------------------------------------

REFINEMENT_JSX = ROOT / "frontend" / "src" / "pages" / "Refinement.jsx"


def test_synthesis_inflight_guard_present():
    """isSynthesizingRef guard must be present and checked in handleSynthesis."""
    source = REFINEMENT_JSX.read_text(encoding="utf-8")
    assert "isSynthesizingRef" in source, (
        "isSynthesizingRef in-flight guard is missing from Refinement.jsx"
    )
    assert "isSynthesizingRef.current = true" in source, (
        "isSynthesizingRef.current = true must be set before the synthesis call"
    )
    assert "isSynthesizingRef.current = false" in source, (
        "isSynthesizingRef.current must be reset in finally block"
    )


# ---------------------------------------------------------------------------
# 7. Frontend: window.confirm must not appear for force_required flow
# ---------------------------------------------------------------------------

def test_window_confirm_removed_from_force_required_flow():
    """window.confirm() is a blocking browser dialog; it must not be used for force_required."""
    source = REFINEMENT_JSX.read_text(encoding="utf-8")
    assert "window.confirm(" not in source, (
        "window.confirm() is a browser-blocking dialog and must be replaced "
        "with the ConfirmationDialog component."
    )


# ---------------------------------------------------------------------------
# 8. Frontend: 409 handling present in handleRefinementError
# ---------------------------------------------------------------------------

def test_409_handled_in_refinement_error():
    source = REFINEMENT_JSX.read_text(encoding="utf-8")
    assert "status === 409" in source, (
        "handleRefinementError should explicitly handle HTTP 409 (Conflict) "
        "so premature-synthesis errors show a user-friendly message."
    )
