import pytest
from query_refinement_module.core import (
    QueryRefinementManager,
    RefinementSession,
    AspectRefinementState,
)
from query_refinement_module.schema import RefinementAspect
from query_refinement_module.interfaces import LLMProviderInterface

class DummyLLMProvider(LLMProviderInterface):
    def __init__(self, responses):
        self.responses = responses
        self.calls = []
    def complete(self, user_prompt="", system_prompt=None, messages=None, response_format=None, **kwargs):
        self.calls.append((user_prompt, system_prompt, messages))
        response = self.responses.pop(0)
        # Return the raw JSON string, not a parsed dict
        return type('LLMCompletionResult', (), {"context": response})()
    async def complete_async(self, user_prompt="", system_prompt=None, messages=None, response_format=None, **kwargs):
        """Async version that delegates to sync complete()"""
        return self.complete(user_prompt, system_prompt, messages, response_format, **kwargs)
    def get_model_info(self, model=None):
        return {}

def make_aspect(id="aspect", allow_follow_up=True, max_follow_ups=2):
    return RefinementAspect(
        id=id,
        name="Test Aspect",
        description="desc",
        specifications="Analyze {query}",
        allow_follow_up=allow_follow_up,
        max_follow_ups=max_follow_ups,
    )

@pytest.mark.asyncio
async def test_followup_loop_stops_on_is_complete():
    aspect = make_aspect()
    # Updated: Include all required fields (complete, current, question)
    responses = [
        '{"complete": false, "current": "", "question": "Clarify?"}',
        '{"complete": true, "current": "Clear value", "question": ""}',
    ]
    llm = DummyLLMProvider(responses)
    manager = QueryRefinementManager(llm)
    session = RefinementSession("query")
    step = session.add_step(aspect)
    result = await manager.run_followup_until_clear(session)
    assert result["is_complete"]
    # Check that aspect value was captured
    assert step.normalized_value is not None
    assert result["rounds"] >= 1  # At least one round completed
    assert len(step.conversation_history) >= 1  # At least one follow-up recorded

@pytest.mark.asyncio
async def test_followup_loop_respects_max_rounds():
    aspect = make_aspect(max_follow_ups=1)
    # Updated: Include all required fields
    responses = [
        '{"complete": false, "current": "", "question": "Clarify?"}',
        '{"complete": false, "current": "", "question": "Clarify?"}',  # retry
        '{"complete": false, "current": "", "question": "Clarify?"}',  # retry
    ]
    llm = DummyLLMProvider(responses)
    manager = QueryRefinementManager(llm)
    session = RefinementSession("query")
    step = session.add_step(aspect)
    result = await manager.run_followup_until_clear(session)
    assert not result["is_complete"]
    assert result["rounds"] <= 1  # Respects max_follow_ups limit
    assert len(step.conversation_history) <= 1  # Limited follow-ups

@pytest.mark.asyncio
async def test_followup_loop_handles_llm_error():
    aspect = make_aspect()
    responses = [Exception("LLM error")]
    class ErrorLLMProvider(DummyLLMProvider):
        def complete(self, user_prompt="", system_prompt=None, messages=None, response_format=None, **kwargs):
            raise Exception("LLM error")
    llm = ErrorLLMProvider(responses)
    manager = QueryRefinementManager(llm)
    session = RefinementSession("query")
    step = session.add_step(aspect)
    # Should mark step complete and add error to history
    result = await manager.run_followup_until_clear(session)
    assert result["is_complete"]
    assert "Validation error" in step.conversation_history[-1]["response"]

@pytest.mark.asyncio
async def test_followup_loop_respects_user_command_skip(monkeypatch):
    aspect = make_aspect()
    responses = [
        '{"is_complete": false, "followup_question": "Clarify?", "reasoning": "Needs more"}'
    ]
    llm = DummyLLMProvider(responses)
    manager = QueryRefinementManager(llm)
    session = RefinementSession("query")
    step = session.add_step(aspect)
    # Simulate user command by marking step complete before loop
    step.is_complete = True
    result = await manager.run_followup_until_clear(session)
    assert result["is_complete"]
    assert result["rounds"] == 0
