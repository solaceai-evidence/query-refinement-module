import pytest
from query_refinement_module.core import (
    QueryRefinementManager,
    QueryRefinementSession,
    QueryAspectRefiner,
)
from query_refinement_module.schema import RefinementAspect
from query_refinement_module.interfaces import AspectAnalysisResult, LLMProviderInterface, QueryAnalyzerInterface

class DummyLLMProvider(LLMProviderInterface):
    def __init__(self, responses):
        self.responses = responses
        self.calls = []
    def complete(self, user_prompt, system_prompt=None, **kwargs):
        self.calls.append((user_prompt, system_prompt))
        response = self.responses.pop(0)
        # Return the raw JSON string, not a parsed dict
        return type('LLMCompletionResult', (), {"context": response})()
    def get_model_info(self, model=None):
        return {}

class DummyAnalyzer(QueryAnalyzerInterface):
    def __init__(self, results):
        self.results = results
    def analyze_aspect(self, query, aspect, dependency_context=None, llm_provider=None):
        return self.results[aspect.id]

def make_aspect(id="aspect", allow_follow_up=True, max_follow_ups=2):
    return RefinementAspect(
        id=id,
        aspect_name="Test Aspect",
        aspect_description="desc",
        refinement_instructions="Analyze {query}",
        allow_follow_up=allow_follow_up,
        max_follow_ups=max_follow_ups,
    )

def test_followup_loop_stops_on_is_complete():
    aspect = make_aspect()
    # Updated: Include dynamic value field (aspect.id)
    responses = [
        '{"is_complete": false, "confidence": 0.5, "reasoning": "Needs more", "refinement_aspect_value": "", "next_question": "Clarify?"}',
        '{"is_complete": true, "confidence": 0.9, "reasoning": "Clear", "refinement_aspect_value": "Clear value", "next_question": null}',
    ]
    llm = DummyLLMProvider(responses)
    analyzer = DummyAnalyzer({"aspect": AspectAnalysisResult(needs_refinement=True, explanation="", clarifying_question="Q")})
    manager = QueryRefinementManager(llm, analyzer)
    session = QueryRefinementSession("query")
    step = session.add_step(aspect)
    result = manager.run_followup_until_clear(session)
    assert result["is_complete"]
    # Check that aspect value was captured
    assert step.refinement_aspect_value is not None
    assert result["rounds"] >= 1  # At least one round completed
    assert len(step.follow_up_history) >= 1  # At least one follow-up recorded

def test_followup_loop_respects_max_rounds():
    aspect = make_aspect(max_follow_ups=1)
    # Updated: Include dynamic value field (aspect.id)
    responses = [
        '{"is_complete": false, "confidence": 0.5, "reasoning": "Needs more", "refinement_aspect_value": "partial value", "next_question": "Clarify?"}',
        '{"is_complete": false, "confidence": 0.5, "reasoning": "Needs more", "refinement_aspect_value": "partial value", "next_question": "Clarify?"}',  # retry
        '{"is_complete": false, "confidence": 0.5, "reasoning": "Needs more", "refinement_aspect_value": "partial value", "next_question": "Clarify?"}',  # retry
    ]
    llm = DummyLLMProvider(responses)
    analyzer = DummyAnalyzer({"aspect": AspectAnalysisResult(needs_refinement=True, explanation="", clarifying_question="Q")})
    manager = QueryRefinementManager(llm, analyzer)
    session = QueryRefinementSession("query")
    step = session.add_step(aspect)
    result = manager.run_followup_until_clear(session)
    assert not result["is_complete"]
    assert result["rounds"] <= 1  # Respects max_follow_ups limit
    assert len(step.follow_up_history) <= 1  # Limited follow-ups

def test_followup_loop_handles_llm_error():
    aspect = make_aspect()
    responses = [Exception("LLM error")]
    class ErrorLLMProvider(DummyLLMProvider):
        def complete(self, user_prompt, system_prompt=None, **kwargs):
            raise Exception("LLM error")
    llm = ErrorLLMProvider(responses)
    analyzer = DummyAnalyzer({"aspect": AspectAnalysisResult(needs_refinement=True, explanation="", clarifying_question="Q")})
    manager = QueryRefinementManager(llm, analyzer)
    session = QueryRefinementSession("query")
    step = session.add_step(aspect)
    # Should mark step complete and add error to history
    result = manager.run_followup_until_clear(session)
    assert result["is_complete"]
    assert "Validation error" in step.follow_up_history[-1]["response"]

def test_followup_loop_respects_user_command_skip(monkeypatch):
    aspect = make_aspect()
    responses = [
        '{"is_complete": false, "followup_question": "Clarify?", "reasoning": "Needs more"}'
    ]
    llm = DummyLLMProvider(responses)
    analyzer = DummyAnalyzer({"aspect": AspectAnalysisResult(needs_refinement=True, explanation="", clarifying_question="Q")})
    manager = QueryRefinementManager(llm, analyzer)
    session = QueryRefinementSession("query")
    step = session.add_step(aspect)
    # Simulate user command by marking step complete before loop
    step.is_complete = True
    result = manager.run_followup_until_clear(session)
    assert result["is_complete"]
    assert result["rounds"] == 0
