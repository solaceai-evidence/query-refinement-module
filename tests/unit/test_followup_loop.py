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
        name="Test Aspect",
        description="desc",
        analysis_prompt="Analyze {query}",
        allow_follow_up=allow_follow_up,
        max_follow_ups=max_follow_ups,
    )

def test_followup_loop_stops_on_is_complete():
    aspect = make_aspect()
    responses = [
        '{"is_complete": false, "followup_question": "Clarify?", "reasoning": "Needs more"}',
        '{"is_complete": true, "final_value": "Clear", "reasoning": "Clear"}'
    ]
    llm = DummyLLMProvider(responses)
    analyzer = DummyAnalyzer({"aspect": AspectAnalysisResult(needs_refinement=True, explanation="", suggested_question="Q")})
    manager = QueryRefinementManager(llm, analyzer)
    session = QueryRefinementSession("query")
    step = session.add_step(aspect)
    result = manager.run_followup_until_clear(session)
    print("DEBUG result:", result)
    print("DEBUG follow_up_history:", step.follow_up_history)
    assert result["is_complete"]
    assert result["final_value"] == "Clear"
    assert result["rounds"] == 2
    assert len(step.follow_up_history) == 2

def test_followup_loop_respects_max_rounds():
    aspect = make_aspect(max_follow_ups=1)
    responses = [
        '{"is_complete": false, "followup_question": "Clarify?", "reasoning": "Needs more"}'
    ]
    llm = DummyLLMProvider(responses)
    analyzer = DummyAnalyzer({"aspect": AspectAnalysisResult(needs_refinement=True, explanation="", suggested_question="Q")})
    manager = QueryRefinementManager(llm, analyzer)
    session = QueryRefinementSession("query")
    step = session.add_step(aspect)
    result = manager.run_followup_until_clear(session)
    assert not result["is_complete"]
    assert result["rounds"] == 1
    assert len(step.follow_up_history) == 1

def test_followup_loop_handles_llm_error():
    aspect = make_aspect()
    responses = [Exception("LLM error")]
    class ErrorLLMProvider(DummyLLMProvider):
        def complete(self, user_prompt, system_prompt=None, **kwargs):
            raise Exception("LLM error")
    llm = ErrorLLMProvider(responses)
    analyzer = DummyAnalyzer({"aspect": AspectAnalysisResult(needs_refinement=True, explanation="", suggested_question="Q")})
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
    analyzer = DummyAnalyzer({"aspect": AspectAnalysisResult(needs_refinement=True, explanation="", suggested_question="Q")})
    manager = QueryRefinementManager(llm, analyzer)
    session = QueryRefinementSession("query")
    step = session.add_step(aspect)
    # Simulate user command by marking step complete before loop
    step.is_complete = True
    result = manager.run_followup_until_clear(session)
    assert result["is_complete"]
    assert result["rounds"] == 0
