import pytest

from query_refinement_module.analyzers import LLMQueryAnalyzer
from query_refinement_module.interfaces import LLMCompletionResult, LLMProviderInterface


class DummyAspect:
    def __init__(self, aspect_id="aspect", name="Aspect", system_prompt="System", user_prompt="Prompt: {query}"):
        self.id = aspect_id
        self.name = name
        self._system_prompt = system_prompt
        self._user_prompt = user_prompt

    def get_system_prompt(self):
        return self._system_prompt

    def get_user_prompt(self, *, query):
        return self._user_prompt.format(query=query)


class RecordingProvider(LLMProviderInterface):
    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = []

    def complete(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        context = self._responses.pop(0)
        if isinstance(context, LLMCompletionResult):
            return context
        return LLMCompletionResult(context=context, model="stub")

    def get_model_info(self, model):
        return {"model": model}


def build_analyzer(responses, **kwargs):
    provider = RecordingProvider(responses)
    analyzer = LLMQueryAnalyzer(provider, **kwargs)
    return analyzer, provider


def test_analyze_aspect_with_valid_payload():
    payload = '{"needs_refinement": false, "explanation": "clear"}'
    analyzer, provider = build_analyzer([payload], temperature=0.2, completion_kwargs={"top_p": 0.9})
    aspect = DummyAspect()

    result = analyzer.analyze_aspect("query", aspect)

    assert not result.needs_refinement
    assert result.explanation == "clear"
    assert result.suggested_question is None

    _, kwargs = provider.calls[0]
    assert kwargs["temperature"] == 0.2
    assert kwargs["top_p"] == 0.9


def test_analyze_aspect_requires_provider():
    analyzer = LLMQueryAnalyzer(llm_provider=None)
    with pytest.raises(ValueError):
        analyzer.analyze_aspect("query", DummyAspect())


def test_analyze_aspect_accepts_override_provider():
    override = RecordingProvider(['{"needs_refinement": true, "explanation": "details", "suggested_question": "Q"}'])
    analyzer = LLMQueryAnalyzer(llm_provider=None)
    aspect = DummyAspect()

    result = analyzer.analyze_aspect("query", aspect, llm_provider=override)

    assert result.needs_refinement
    assert result.explanation == "details"
    assert result.suggested_question == "Q"


def test_analyze_aspect_handles_missing_payload():
    analyzer, _ = build_analyzer(["   "])
    aspect = DummyAspect(name="Population")

    result = analyzer.analyze_aspect("query", aspect)

    assert result.needs_refinement
    assert "Unable to parse" in result.explanation
    assert result.suggested_question == "Population"


def test_analyze_aspect_missing_required_field():
    analyzer, _ = build_analyzer(['{"explanation": "oops"}'])
    aspect = DummyAspect(name="Intervention")

    result = analyzer.analyze_aspect("query", aspect)

    assert result.needs_refinement
    assert "missing required" in result.explanation
    assert result.suggested_question == "Intervention"


def test_analyze_aspect_missing_suggested_question():
    analyzer, _ = build_analyzer(['{"needs_refinement": true, "explanation": "", "suggested_question": ""}'])
    aspect = DummyAspect(name="Outcome")

    result = analyzer.analyze_aspect("query", aspect)

    assert result.needs_refinement
    assert result.suggested_question == "Outcome"


def test_build_prompt_with_dependency_context():
    analyzer, _ = build_analyzer(["{}"])
    aspect = DummyAspect(user_prompt="Question for {query}")

    prompt = analyzer._build_prompt(
        "original",
        aspect,
        dependency_context={"b": "B", "a": "A"},
    )

    assert "Dependency context:" in prompt
    assert "- a: A" in prompt.splitlines()[1]
    assert "- b: B" in prompt.splitlines()[2]
    assert "Question for original" in prompt


def test_coerce_bool_handles_various_types():
    analyzer, _ = build_analyzer(["{}"])
    assert analyzer._coerce_bool(True) is True
    assert analyzer._coerce_bool(0) is False
    assert analyzer._coerce_bool(2) is True
    assert analyzer._coerce_bool("yes") is True
    assert analyzer._coerce_bool("no") is False
    assert analyzer._coerce_bool(None) is True


def test_parse_payload_with_code_fence():
    analyzer, _ = build_analyzer(["{}"])
    raw = "```json\n{\"needs_refinement\": false}\n```"
    parsed = analyzer._parse_payload(raw)
    assert parsed == {"needs_refinement": False}


def test_parse_payload_with_embedded_json():
    analyzer, _ = build_analyzer(["{}"])
    raw = "The answer is: {\"needs_refinement\": true, \"explanation\": \"details\"}."
    parsed = analyzer._parse_payload(raw)
    assert parsed["needs_refinement"] is True
    assert parsed["explanation"] == "details"


def test_parse_payload_returns_none_for_invalid():
    analyzer, _ = build_analyzer(["{}"])
    assert analyzer._parse_payload("not json") is None


def test_strip_code_fence_removes_wrappers():
    analyzer, _ = build_analyzer(["{}"])
    payload = "```\nline1\nline2\n```"
    assert analyzer._strip_code_fence(payload) == "line1\nline2"
    assert analyzer._strip_code_fence("plain") == "plain"