"""Tests for JWT auth utilities (PyJWT)."""
from datetime import timedelta

import pytest

from query_refinement_module.api.auth import create_access_token, decode_access_token


def test_create_access_token_returns_str():
    token = create_access_token({"sub": "testuser"})
    assert isinstance(token, str)
    assert len(token) > 0


def test_decode_access_token_round_trip():
    token = create_access_token({"sub": "testuser", "role": "admin"})
    payload = decode_access_token(token)
    assert payload is not None
    assert payload["sub"] == "testuser"
    assert payload["role"] == "admin"


def test_decode_access_token_contains_exp():
    token = create_access_token({"sub": "testuser"})
    payload = decode_access_token(token)
    assert payload is not None
    assert "exp" in payload


def test_decode_access_token_returns_none_for_garbage():
    assert decode_access_token("not.a.token") is None


def test_decode_access_token_returns_none_for_empty_string():
    assert decode_access_token("") is None


def test_decode_access_token_returns_none_for_expired_token():
    token = create_access_token({"sub": "testuser"}, expires_delta=timedelta(seconds=-1))
    assert decode_access_token(token) is None


def test_decode_access_token_returns_none_for_wrong_secret(monkeypatch):
    import query_refinement_module.api.auth as auth_module
    token = create_access_token({"sub": "testuser"})
    # Temporarily swap the secret used for decoding
    original_secret = auth_module.settings.secret_key
    monkeypatch.setattr(auth_module.settings, "secret_key", "totally-different-secret-key-32bytes!")
    assert decode_access_token(token) is None
