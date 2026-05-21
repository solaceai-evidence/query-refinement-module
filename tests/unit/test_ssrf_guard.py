"""Tests for SSRF guard validators on ForwardToQARequest (ISSUE-01)."""
import pytest
from pydantic import ValidationError

# ForwardToQARequest is defined in the routes module, not imported from a
# models module, so we import it directly from its definition file.
from query_refinement_module.api.routes.refinement import ForwardToQARequest


def _make_valid() -> dict:
    return {"qa_system_url": "https://external.example.com/qa"}


# ── _no_private_url ────────────────────────────────────────────────────────────

def test_public_url_is_accepted():
    req = ForwardToQARequest(**_make_valid())
    assert req is not None


def test_localhost_is_rejected():
    with pytest.raises(ValidationError, match="loopback"):
        ForwardToQARequest(qa_system_url="http://localhost/qa")


def test_loopback_ip_is_rejected():
    with pytest.raises(ValidationError, match="Private or internal"):
        ForwardToQARequest(qa_system_url="http://127.0.0.1/qa")


def test_private_ip_class_a_is_rejected():
    with pytest.raises(ValidationError, match="Private or internal"):
        ForwardToQARequest(qa_system_url="http://10.0.0.1/qa")


def test_private_ip_class_b_is_rejected():
    with pytest.raises(ValidationError, match="Private or internal"):
        ForwardToQARequest(qa_system_url="http://172.16.0.1/qa")


def test_private_ip_class_c_is_rejected():
    with pytest.raises(ValidationError, match="Private or internal"):
        ForwardToQARequest(qa_system_url="http://192.168.1.1/qa")


def test_zero_dot_zero_is_rejected():
    with pytest.raises(ValidationError, match="loopback|Internal"):
        ForwardToQARequest(qa_system_url="http://0.0.0.0/qa")


# ── _safe_auth_headers ─────────────────────────────────────────────────────────

def test_authorization_header_is_accepted():
    req = ForwardToQARequest(
        **_make_valid(),
        qa_system_auth={"Authorization": "Bearer token"},
    )
    assert req.qa_system_auth == {"Authorization": "Bearer token"}


def test_host_header_is_rejected():
    with pytest.raises(ValidationError, match="not permitted"):
        ForwardToQARequest(
            **_make_valid(),
            qa_system_auth={"Host": "evil.attacker.com"},
        )


def test_connection_header_is_rejected():
    with pytest.raises(ValidationError, match="not permitted"):
        ForwardToQARequest(
            **_make_valid(),
            qa_system_auth={"Connection": "keep-alive"},
        )


def test_content_length_header_is_rejected():
    with pytest.raises(ValidationError, match="not permitted"):
        ForwardToQARequest(
            **_make_valid(),
            qa_system_auth={"Content-Length": "0"},
        )


def test_none_auth_is_accepted():
    req = ForwardToQARequest(**_make_valid(), qa_system_auth=None)
    assert req.qa_system_auth is None
