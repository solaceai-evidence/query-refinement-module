from __future__ import annotations

import pytest

from query_refinement_module.interfaces import (
    AspectAnalysisResult,
    LLMCompletionResult,
    LLMProviderInterface,
    QueryAnalyzerInterface,
    SessionStorageInterface,
    TracingProviderInterface,
)
from query_refinement_module.schema import RefinementAspect


def make_aspect(aspect_id: str = "aspect", name: str = "Aspect") -> RefinementAspect:
    return RefinementAspect(
        id=aspect_id,
        name=name,
        description=f"Description for {name}",
        analysis_prompt="Analyze {query}",
        depends_on=[],
    )


def test_llm_completion_result_initializes_metadata_independently():
    first = LLMCompletionResult(context="", model="demo")
    first.metadata["seen"] = True

    second = LLMCompletionResult(context="", model="demo")
    assert second.metadata == {}


def test_llm_provider_interface_methods_raise_notimplemented():
    class DummyLLM(LLMProviderInterface):
        def complete(self, *args, **kwargs):
            return super().complete(*args, **kwargs)

        def get_model_info(self, model):
            return super().get_model_info(model)

    provider = DummyLLM()

    with pytest.raises(NotImplementedError):
        provider.complete("prompt")

    with pytest.raises(NotImplementedError):
        provider.get_model_info("model")


def test_query_analyzer_batch_analyze_falls_back_to_sequential():
    class RecordingAnalyzer(QueryAnalyzerInterface):
        def __init__(self):
            self.calls = []

        def analyze_aspect(self, query, aspect, dependency_context=None, llm_provider=None):
            self.calls.append((query, aspect.id))
            return AspectAnalysisResult(needs_refinement=False, explanation="")

    analyzer = RecordingAnalyzer()
    aspects = [make_aspect("a"), make_aspect("b")]

    results = analyzer.batch_analyze("query", aspects)

    assert set(results.keys()) == {"a", "b"}
    assert analyzer.calls == [("query", "a"), ("query", "b")]


def test_tracing_provider_interface_methods_raise_notimplemented():
    class DummyTracer(TracingProviderInterface):
        def trace_operation(self, *args, **kwargs):
            return super().trace_operation(*args, **kwargs)

        def log_event(self, *args, **kwargs):
            return super().log_event(*args, **kwargs)

        def is_enabled(self):
            return super().is_enabled()

    tracer = DummyTracer()

    with pytest.raises(NotImplementedError):
        tracer.trace_operation("op")

    with pytest.raises(NotImplementedError):
        tracer.log_event("event")

    with pytest.raises(NotImplementedError):
        tracer.is_enabled()


def test_session_storage_interface_cannot_be_instantiated():
    with pytest.raises(TypeError):
        SessionStorageInterface()