import json
import logging
from pathlib import Path

import pytest

import query_refinement_module.providers as providers
from query_refinement_module.interfaces import LLMCompletionResult
from query_refinement_module.providers import (
    ConsoleTracing,
    FileTracingProvider,
    InMemorySessionStorage,
    LiteLLMProvider,
    NoOpTracingProvider,
    RedisSessionStorage,
    TraceEventEmitter,
)
from query_refinement_module.logging_utils import configure_file_logging


def test_trace_event_emitter_ignores_missing_provider():
    """TraceEventEmitter handles None provider gracefully."""
    emitter = TraceEventEmitter(None)
    emitter.emit("event")  # Should not raise


def test_trace_event_emitter_logs_when_enabled():
    class RecordingProvider:
        def __init__(self):
            self.events = []

        def is_enabled(self):
            return True

        def log_event(self, event_name, level="info", metadata=None):
            self.events.append((event_name, level, metadata))

    provider = RecordingProvider()
    emitter = TraceEventEmitter(provider)
    emitter.emit("refine", level="warning", metadata={"step": 1})

    assert provider.events == [("refine", "warning", {"step": 1})]


def test_trace_event_emitter_swallows_provider_errors():
    class FailingProvider:
        def is_enabled(self):
            return True

        def log_event(self, *args, **kwargs):
            raise RuntimeError("boom")

    emitter = TraceEventEmitter(FailingProvider())
    emitter.emit("refine")


def test_noop_tracing_provider_behaviour():
    tracer = NoOpTracingProvider()
    with tracer.trace_operation("noop"):
        pass

    tracer.log_event("event")
    assert not tracer.is_enabled()


def test_console_tracing_outputs(capsys):
    tracer = ConsoleTracing()
    with tracer.trace_operation("task", operation_type="step", metadata={"id": "1"}):
        pass

    out = capsys.readouterr().out
    assert "[TRACE START] STEP: task" in out
    assert "[TRACE END] STEP: task - SUCCESS" in out

    with pytest.raises(RuntimeError):
        with tracer.trace_operation("fail"):
            raise RuntimeError("failure")

    err_output = capsys.readouterr().out
    assert "ERROR" in err_output


def test_inmemory_session_storage_crud():
    storage = InMemorySessionStorage()
    session_id = "abc"
    payload = {"data": 1}

    storage.save_session(session_id, payload)
    assert storage.session_exists(session_id)
    assert storage.load_session(session_id) == payload

    storage.delete_session(session_id)
    assert not storage.session_exists(session_id)
    with pytest.raises(KeyError):
        storage.load_session(session_id)


def test_redis_session_storage_requires_dependency(monkeypatch):
    import query_refinement_module.providers.storage as storage_module
    monkeypatch.setattr(storage_module, "redis", None)
    with pytest.raises(RuntimeError):
        RedisSessionStorage(client=object())


def test_redis_session_storage_basic_operations(monkeypatch):
    import query_refinement_module.providers.storage as storage_module
    
    class StubRedisModule:
        pass

    class StubClient:
        def __init__(self):
            self.store = {}

        def set(self, key, value):
            self.store[key] = value

        def get(self, key):
            return self.store.get(key)

        def delete(self, key):
            self.store.pop(key, None)

        def exists(self, key):
            return key in self.store

    monkeypatch.setattr(storage_module, "redis", StubRedisModule())
    client = StubClient()
    storage = RedisSessionStorage(client, namespace="ns")

    session_id = "xyz"
    payload = {"value": 42}
    storage.save_session(session_id, payload)

    key = "ns:xyz"
    assert client.store[key] == json.dumps(payload)
    assert storage.session_exists(session_id)
    assert storage.load_session(session_id) == payload

    storage.delete_session(session_id)
    assert not storage.session_exists(session_id)
    with pytest.raises(KeyError):
        storage.load_session(session_id)


def test_litellm_provider_requires_dependency(monkeypatch):
    import query_refinement_module.providers.llm as llm_module
    monkeypatch.setattr(llm_module, "litellm", None)
    with pytest.raises(RuntimeError):
        LiteLLMProvider(default_model="demo")


def test_litellm_provider_completion_and_model_info(monkeypatch):
    import query_refinement_module.providers.llm as llm_module
    
    class StubLiteLLM:
        def __init__(self):
            self.calls = []

        def completion(self, **kwargs):
            self.calls.append(kwargs)
            return {
                "choices": [{"message": {"content": "refined"}}],
                "usage": {"total_tokens": 12},
                "id": "resp-1",
            }

        def get_model_cost(self, model):
            return {"model": model, "cost": 0.01}

    stub = StubLiteLLM()
    monkeypatch.setattr(llm_module, "litellm", stub)

    provider = LiteLLMProvider(
        default_model="default",
        default_completion_kwargs={"top_p": 0.8},
    )

    result = provider.complete(
        user_prompt="Question?",
        system_prompt="System",
        model="override",
        temperature=0.3,
        max_tokens=100,
        extra="value",
    )

    assert isinstance(result, LLMCompletionResult)
    assert result.context == "refined"
    assert result.metadata["provider"] == "litellm"

    call = stub.calls[0]
    assert call["model"] == "override"
    assert call["messages"][0] == {"role": "system", "content": "System"}
    assert call["messages"][1] == {"role": "user", "content": "Question?"}
    assert call["temperature"] == 0.3
    assert call["extra"] == "value"
    assert call["max_tokens"] == 100

    info = provider.get_model_info("demo")
    assert info["model"] == "demo"
    assert info["provider"] == "litellm"
    assert info["pricing"] == {"model": "demo", "cost": 0.01}


def test_file_tracing_provider_writes_json(tmp_path):
    trace_dir = tmp_path / "logs"
    tracer = FileTracingProvider(str(trace_dir))

    with tracer.trace_operation("initialise", metadata={"step": 1}):
        pass

    tracer.log_event("step_ready", metadata={"aspect": "population"})

    operations_path = trace_dir / "trace_operations.log"
    events_path = trace_dir / "trace_events.log"

    assert operations_path.exists()
    assert events_path.exists()

    operations = [json.loads(line) for line in operations_path.read_text().splitlines() if line]
    events = [json.loads(line) for line in events_path.read_text().splitlines() if line]

    assert operations[0]["event"] == "start"
    assert operations[1]["status"] == "success"
    assert events[0]["event"] == "step_ready"


def test_file_tracing_provider_includes_trace_context(tmp_path):
    """FileTracingProvider embeds request_id/trace_id from ContextVars into every record."""
    from query_refinement_module.tracing import set_request_id, set_trace_id, clear_trace_context

    set_request_id("abc12345")
    set_trace_id("trace-uuid-test")
    try:
        trace_dir = tmp_path / "logs_ctx"
        tracer = FileTracingProvider(str(trace_dir))

        with tracer.trace_operation("op_with_context"):
            pass

        tracer.log_event("event_with_context", metadata={"x": 1})
    finally:
        clear_trace_context()

    operations = [
        json.loads(line)
        for line in (trace_dir / "trace_operations.log").read_text().splitlines()
        if line
    ]
    events = [
        json.loads(line)
        for line in (trace_dir / "trace_events.log").read_text().splitlines()
        if line
    ]

    for record in operations + events:
        assert record.get("request_id") == "abc12345"
        assert record.get("trace_id") == "trace-uuid-test"


def test_file_tracing_provider_omits_trace_context_when_not_set(tmp_path):
    """FileTracingProvider omits request_id/trace_id keys when ContextVars are unset."""
    from query_refinement_module.tracing import clear_trace_context

    clear_trace_context()

    trace_dir = tmp_path / "logs_no_ctx"
    tracer = FileTracingProvider(str(trace_dir))

    with tracer.trace_operation("op_no_context"):
        pass

    tracer.log_event("event_no_context")

    operations = [
        json.loads(line)
        for line in (trace_dir / "trace_operations.log").read_text().splitlines()
        if line
    ]
    events = [
        json.loads(line)
        for line in (trace_dir / "trace_events.log").read_text().splitlines()
        if line
    ]

    for record in operations + events:
        assert "request_id" not in record
        assert "trace_id" not in record


def test_configure_file_logging_creates_directory(tmp_path):
    root_logger = logging.getLogger()
    original_handlers = list(root_logger.handlers)
    try:
        log_path = configure_file_logging(str(tmp_path / "log"), filename="app.log")
        logging.getLogger("query_refinement_module.tests").info("hello")
        for handler in root_logger.handlers:
            handler.flush()
        assert log_path.exists()
        contents = log_path.read_text()
        assert "hello" in contents
    finally:
        for handler in list(root_logger.handlers):
            if handler not in original_handlers:
                handler.close()
                root_logger.removeHandler(handler)
        for handler in original_handlers:
            if handler not in root_logger.handlers:
                root_logger.addHandler(handler)


# ---------------------------------------------------------------------------
# Constrained decoding (vLLM guided_json) tests
# ---------------------------------------------------------------------------

import pytest
from unittest.mock import AsyncMock, patch

from query_refinement_module.schema.response import (
    DimensionEvaluationResponse,
    QueryRefinementResponse,
    SearchOptimized,
    KeywordSearch,
    SearchTerms,
    SearchFilters,
    Terminology,
)


def _make_qrr() -> QueryRefinementResponse:
    """Minimal valid QueryRefinementResponse for testing."""
    return QueryRefinementResponse(**{
        "synthesized_statement": "Refined query for testing",
        "refined_dimensions": {"population": "adults"},
        "search_optimized": {
            "semantic": "adults health outcomes",
            "keyword": {
                "structured": "adults AND health",
                "phrases": ["health outcomes"],
                "terms": {"required": ["adults"], "optional": [], "excluded": []},
            },
        },
        "search_filters": {
            "publication_years": "",
            "venues": [],
            "authors": [],
            "publication_types": [],
            "fields_of_study": [],
        },
        "terminology": {"synonyms": {}, "colloquial": []},
    })


@pytest.mark.asyncio
async def test_litellm_provider_constrained_decoding_dimension():
    """Pydantic model + constrained_decoding=True → guided_json in extra_body, no response_format."""
    import query_refinement_module.providers.llm as llm_module

    dim_json = '{"complete": true, "current": "adults 18-65", "question": ""}'
    mock_response = {
        "choices": [{"message": {"content": dim_json}}],
        "usage": {"total_tokens": 42},
        "id": "dim-test-1",
    }

    with patch.object(llm_module, "litellm") as mock_litellm:
        mock_litellm.acompletion = AsyncMock(return_value=mock_response)

        provider = LiteLLMProvider(
            default_model="meta-llama/Llama-3.1-8B-Instruct",
            constrained_decoding=True,
            enable_circuit_breaker=False,
        )
        result = await provider.complete_async(
            user_prompt="Evaluate dimension",
            response_format=DimensionEvaluationResponse,
        )

    call_kwargs = mock_litellm.acompletion.call_args.kwargs
    assert "extra_body" in call_kwargs
    assert "guided_json" in call_kwargs["extra_body"]
    assert "properties" in call_kwargs["extra_body"]["guided_json"]
    assert "response_format" not in call_kwargs

    assert isinstance(result.context, DimensionEvaluationResponse)
    assert result.context.complete is True
    assert result.context.current == "adults 18-65"


@pytest.mark.asyncio
async def test_litellm_provider_constrained_decoding_synthesis():
    """QueryRefinementResponse + constrained_decoding=True → guided_json uses aliased schema keys."""
    import query_refinement_module.providers.llm as llm_module

    qrr = _make_qrr()
    mock_response = {
        "choices": [{"message": {"content": qrr.model_dump_json(by_alias=True)}}],
        "usage": {"total_tokens": 120},
        "id": "syn-test-1",
    }

    with patch.object(llm_module, "litellm") as mock_litellm:
        mock_litellm.acompletion = AsyncMock(return_value=mock_response)

        provider = LiteLLMProvider(
            default_model="meta-llama/Llama-3.1-8B-Instruct",
            constrained_decoding=True,
            enable_circuit_breaker=False,
        )
        result = await provider.complete_async(
            user_prompt="Synthesize",
            response_format=QueryRefinementResponse,
        )

    call_kwargs = mock_litellm.acompletion.call_args.kwargs
    guided = call_kwargs["extra_body"]["guided_json"]
    # Schema must use alias keys so it matches what the synthesis prompt instructs the LLM to produce
    props = guided.get("properties", guided.get("$defs", {}).get("QueryRefinementResponse", {}).get("properties", {}))
    assert "synthesized_statement" in props or any(
        "synthesized_statement" in str(v) for v in guided.values()
    ), "guided_json schema must use aliased field name 'synthesized_statement'"
    assert "response_format" not in call_kwargs

    assert isinstance(result.context, QueryRefinementResponse)
    assert result.context.integrated_statement == "Refined query for testing"


@pytest.mark.asyncio
async def test_litellm_provider_constrained_decoding_json_object_fallback():
    """constrained_decoding=True with {\"type\": \"json_object\"} dict falls back to response_format."""
    import query_refinement_module.providers.llm as llm_module

    mock_response = {
        "choices": [{"message": {"content": '{"answer": 42}'}}],
        "usage": {"total_tokens": 10},
        "id": "fallback-test-1",
    }

    with patch.object(llm_module, "litellm") as mock_litellm:
        mock_litellm.acompletion = AsyncMock(return_value=mock_response)

        provider = LiteLLMProvider(
            default_model="meta-llama/Llama-3.1-8B-Instruct",
            constrained_decoding=True,
            enable_circuit_breaker=False,
        )
        result = await provider.complete_async(
            user_prompt="Give me JSON",
            response_format={"type": "json_object"},
        )

    call_kwargs = mock_litellm.acompletion.call_args.kwargs
    assert call_kwargs["response_format"] == {"type": "json_object"}
    assert "extra_body" not in call_kwargs or "guided_json" not in call_kwargs.get("extra_body", {})


@pytest.mark.asyncio
async def test_litellm_provider_no_regression_constrained_decoding_off():
    """constrained_decoding=False (default) with Pydantic model uses standard litellm response_format path."""
    import query_refinement_module.providers.llm as llm_module

    mock_response = {
        "choices": [{"message": {"content": '{"complete": true, "current": "val", "question": ""}'}}],
        "usage": {"total_tokens": 20},
        "id": "no-reg-1",
    }

    with patch.object(llm_module, "litellm") as mock_litellm:
        mock_litellm.acompletion = AsyncMock(return_value=mock_response)

        provider = LiteLLMProvider(
            default_model="anthropic/claude-sonnet-4-6",
            constrained_decoding=False,
            enable_circuit_breaker=False,
        )
        await provider.complete_async(
            user_prompt="Evaluate",
            response_format=DimensionEvaluationResponse,
        )

    call_kwargs = mock_litellm.acompletion.call_args.kwargs
    assert call_kwargs["response_format"] is DimensionEvaluationResponse
    assert "extra_body" not in call_kwargs or "guided_json" not in call_kwargs.get("extra_body", {})