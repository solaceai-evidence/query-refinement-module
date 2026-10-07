"""Regression tests for API hardening: model override allow-list and QA handoff."""

from types import SimpleNamespace

import httpx
import pytest

import query_refinement_module.application.refinement_api_service as service_module
import query_refinement_module.application.refinement_utility_service as utility_module
from query_refinement_module.api.exceptions import QueryRefinementException
from query_refinement_module.application.refinement_api_service import RefinementApiService


class _User:
    def __init__(self, user_id=1):
        self.id = user_id
        self.is_superuser = False
        self.has_completed_workflow = False


def _service(manager):
    return RefinementApiService(
        manager=manager,
        db=object(),
        session_manager=None,
        settings_factory=lambda: SimpleNamespace(enforce_workflow_limit=False),
    )


@pytest.mark.asyncio
async def test_model_override_rejects_unlisted_model(monkeypatch):
    monkeypatch.delenv("LLM_ALLOWED_MODEL_OVERRIDES", raising=False)
    manager = SimpleNamespace(llm_provider=SimpleNamespace(_default_model="configured-model"))

    with pytest.raises(QueryRefinementException) as exc_info:
        await _service(manager).represent_workflow(
            statement="Adults with COPD receiving pulmonary rehabilitation.",
            model="some-expensive-model",
            current_user=_User(),
            request_id="req-1",
        )

    assert exc_info.value.status_code == 400


@pytest.mark.asyncio
async def test_model_override_allows_env_listed_model(monkeypatch):
    monkeypatch.setenv("LLM_ALLOWED_MODEL_OVERRIDES", "other-model, second-model")
    seen = {}

    async def _run_semantic_representation(statement, model=None):
        seen["model"] = model
        raise RuntimeError("stop after override check")

    manager = SimpleNamespace(
        llm_provider=SimpleNamespace(_default_model="configured-model"),
        _run_semantic_representation=_run_semantic_representation,
    )

    with pytest.raises(QueryRefinementException):
        await _service(manager).represent_workflow(
            statement="Adults with COPD receiving pulmonary rehabilitation.",
            model="second-model",
            current_user=_User(),
            request_id="req-2",
        )

    assert seen["model"] == "second-model"


def _synthesized_query(user):
    return SimpleNamespace(
        id=9,
        original_query="exercise for copd",
        refined_query="Adults with COPD receiving pulmonary rehabilitation.",
        dimensions_specifications={"population": "Adults with COPD"},
        search_optimized={"semantic": "s", "keyword": {"structured": "(copd) AND (rehabilitation)"}},
        search_filters={"publication_years": "2015-2025"},
        search_expansion_levels=None,
        session=SimpleNamespace(user_id=user.id, framework_name="pico_advanced"),
    )


@pytest.mark.asyncio
async def test_forward_to_qa_includes_structured_output_and_step_status(monkeypatch):
    user = _User()
    steps = [
        SimpleNamespace(aspect_id="population", is_complete=True, was_skipped=False),
        SimpleNamespace(aspect_id="comparator", is_complete=False, was_skipped=True),
    ]
    monkeypatch.setattr(service_module, "get_query", lambda db, query_id: _synthesized_query(user))
    monkeypatch.setattr(utility_module, "get_query_refinement_steps", lambda db, query_id: steps)

    async def _public(url):
        return None

    monkeypatch.setattr(utility_module, "_ensure_public_host", _public)

    captured = {}

    def _handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = request.read()
        return httpx.Response(200, json={"answer": "ok"})

    real_client = httpx.AsyncClient
    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kwargs: real_client(transport=httpx.MockTransport(_handler), **kwargs),
    )

    payload = await _service(SimpleNamespace()).forward_to_qa_workflow(
        query_id=9,
        qa_system_url="https://qa.example.com/api",
        qa_system_auth=None,
        timeout_seconds=10,
        include_refinement_metadata=True,
        forward_original_query=False,
        current_user=user,
        request_id="req-3",
    )

    assert payload["qa_system_status_code"] == 200
    assert payload["refinement_metadata"]["dimensions_refined"] == ["population"]
    assert payload["refinement_metadata"]["dimensions_skipped"] == ["comparator"]
    assert b"structured_output" in captured["body"]


@pytest.mark.asyncio
async def test_ensure_public_host_rejects_hostname_resolving_to_private_ip(monkeypatch):
    class _Loop:
        async def getaddrinfo(self, host, port, type=0):
            return [(None, None, None, "", ("10.1.2.3", 0))]

    monkeypatch.setattr(utility_module.asyncio, "get_running_loop", lambda: _Loop())

    with pytest.raises(QueryRefinementException) as exc_info:
        await utility_module._ensure_public_host("https://internal.example.com/qa")

    assert exc_info.value.status_code == 400
