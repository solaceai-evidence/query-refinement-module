import textwrap

from query_refinement_module.core import QueryRefinementManager, parse_user_command
from query_refinement_module.interfaces import (
    AspectAnalysisResult,
    LLMCompletionResult,
    LLMProviderInterface,
    QueryAnalyzerInterface,
)
from query_refinement_module.schema import registry


class StubProvider(LLMProviderInterface):
    def __init__(self, response_text: str = "Refined Query") -> None:
        self.response_text = response_text
        self.calls = []

    def complete(
        self,
        user_prompt: str,
        system_prompt: str | None = None,
        model: str | None = None,
        temperature: float = 0.0,
        max_tokens: int | None = None,
        **kwargs,
    ) -> LLMCompletionResult:
        self.calls.append(
            {
                "user_prompt": user_prompt,
                "system_prompt": system_prompt,
                "temperature": temperature,
                "max_tokens": max_tokens,
            }
        )
        return LLMCompletionResult(
            context=self.response_text,
            model=model or "stub-model",
        )

    def get_model_info(self, model: str):  # pragma: no cover - not used in tests
        return {"model": model}


class StubAnalyzer(QueryAnalyzerInterface):
    def analyze_aspect(self, query, aspect, dependency_context=None, llm_provider=None):
        return AspectAnalysisResult(
            needs_refinement=False,
            explanation="This aspect is already clear",
            clarifying_question=None,
        )


class NeedsRefinementAnalyzer(QueryAnalyzerInterface):
    def analyze_aspect(self, query, aspect, dependency_context=None, llm_provider=None):
        return AspectAnalysisResult(
            needs_refinement=True,
            explanation="Population details missing",
            clarifying_question="Which population are you studying?",
        )


def _write_framework(tmp_path):
    yaml_content = textwrap.dedent(
        """
        demo:
          - id: aspect_a
            aspect_name: Aspect A
            aspect_description: First aspect
            evaluation_instructions: Analyze the query
        """
    )
    path = tmp_path / "framework.yaml"
    path.write_text(yaml_content, encoding="utf-8")
    return path


def test_initialize_stores_initial_summary(monkeypatch, tmp_path):
    framework_path = _write_framework(tmp_path)
    monkeypatch.setenv("REFINEMENT_FRAMEWORK_PATH", str(framework_path))
    registry.reload_from_env(raise_on_error=True)

    provider = StubProvider()
    analyzer = StubAnalyzer()
    manager = QueryRefinementManager(provider, analyzer)

    session = manager.initialize("Original question", registry.get_framework("demo"))

    step = session.steps[0]
    assert step.refinement_aspect_value == "This aspect is already clear"

    synthesis = manager.synthesize_refined_query(session)
    assert synthesis["refined_query"] == "Refined Query"
    assert synthesis["baseline_summaries"] == [("Aspect A", "This aspect is already clear")]
    assert provider.calls, "Provider should be invoked for synthesis"

    user_prompt = provider.calls[0]["user_prompt"]
    # Check that the synthesis prompt contains the aspect details
    assert "Aspect A" in user_prompt
    assert "This aspect is already clear" in user_prompt


def test_skip_does_not_trigger_synthesis(monkeypatch, tmp_path):
    framework_path = _write_framework(tmp_path)
    monkeypatch.setenv("REFINEMENT_FRAMEWORK_PATH", str(framework_path))
    registry.reload_from_env(raise_on_error=True)

    provider = StubProvider()
    analyzer = NeedsRefinementAnalyzer()
    manager = QueryRefinementManager(provider, analyzer)

    session = manager.initialize("Original question", registry.get_framework("demo"))

    # Simulate user skipping the only refinement aspect
    command = parse_user_command("/skip")
    session.handle_command(command)

    synthesis = manager.synthesize_refined_query(session)

    assert synthesis["refined_query"] == "Original question"
    assert synthesis["used_llm"] is False
    assert synthesis["clarifications"] == []
    assert synthesis["baseline_summaries"] == []
    assert provider.calls == []
