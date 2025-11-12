import pickle

import pytest

import query_refinement_module.providers as providers
from query_refinement_module.interfaces import LLMCompletionResult
from query_refinement_module.providers import (
    ConsoleTracing,
    InMemorySessionStorage,
    LiteLLMProvider,
    NoOpTracingProvider,
    RedisSessionStorage,
    TraceEventEmitter,
)


def test_trace_event_emitter_ignores_missing_provider():
    emitter = TraceEventEmitter(None)
    emitter.emit("event")

    class Incomplete:
        pass

    emitter = TraceEventEmitter(Incomplete())
    emitter.emit("event")


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
    monkeypatch.setattr(providers, "redis", None)
    with pytest.raises(RuntimeError):
        RedisSessionStorage(client=object())


def test_redis_session_storage_basic_operations(monkeypatch):
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

    monkeypatch.setattr(providers, "redis", StubRedisModule())
    client = StubClient()
    storage = RedisSessionStorage(client, namespace="ns")

    session_id = "xyz"
    payload = {"value": 42}
    storage.save_session(session_id, payload)

    key = "ns:xyz"
    assert client.store[key] == pickle.dumps(payload, protocol=pickle.HIGHEST_PROTOCOL)
    assert storage.session_exists(session_id)
    assert storage.load_session(session_id) == payload

    storage.delete_session(session_id)
    assert not storage.session_exists(session_id)
    with pytest.raises(KeyError):
        storage.load_session(session_id)


def test_litellm_provider_requires_dependency(monkeypatch):
    monkeypatch.setattr(providers, "litellm", None)
    with pytest.raises(RuntimeError):
        LiteLLMProvider(default_model="demo")


def test_litellm_provider_completion_and_model_info(monkeypatch):
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
    monkeypatch.setattr(providers, "litellm", stub)

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