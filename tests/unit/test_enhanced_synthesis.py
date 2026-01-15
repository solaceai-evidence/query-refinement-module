"""
Unit tests for enhanced context synthesis and dependency management.

Tests verify:
1. Follow-up prompts include synthesis instructions
2. Dependency context includes name + description + value
3. refined_value is prioritized over final_response in dependencies
4. Synthesis produces clean, professional output
"""

import pytest
from query_refinement_module.core import (
    QueryAspectRefiner,
    QueryRefinementSession,
    QueryRefinementManager,
)
from query_refinement_module.interfaces import (
    AspectAnalysisResult,
    LLMCompletionResult,
    LLMProviderInterface,
    QueryAnalyzerInterface,
)
from query_refinement_module.schema import RefinementAspect
from typing import Any, Dict, Iterable, List, Optional


# ---------------------------------------------------------------------------
# Test Helpers
# ---------------------------------------------------------------------------

def make_aspect(
    *,
    aspect_id: str = "test",
    name: str = "Test Aspect",
    description: str = "Test description",
    analysis_prompt: str = "Analyze {query}",
    depends_on: Optional[List[str]] = None,
    allow_follow_up: bool = True,
    max_follow_ups: int = 3,
) -> RefinementAspect:
    return RefinementAspect(
        id=aspect_id,
        aspect_name=name,
        aspect_description=description,
        refinement_instructions=analysis_prompt,
        depends_on=depends_on or [],
        allow_follow_up=allow_follow_up,
        max_follow_ups=max_follow_ups,
    )


class DummyCompletionResult(LLMCompletionResult):
    pass


class StubLLMProvider(LLMProviderInterface):
    def __init__(self, responses: Iterable[Any]):
        self._responses = list(responses)
        self.calls: List[Dict[str, Any]] = []

    def complete(
        self,
        user_prompt: str,
        system_prompt: Optional[str] = None,
        model: Optional[str] = None,
        temperature: float = 0.0,
        max_tokens: Optional[int] = None,
        **kwargs,
    ) -> LLMCompletionResult:
        self.calls.append({
            "system_prompt": system_prompt,
            "user_prompt": user_prompt,
            "model": model,
            "temperature": temperature,
        })
        if not self._responses:
            raise RuntimeError("No more responses")
        item = self._responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return DummyCompletionResult(context=item, model="test")

    def get_model_info(self, model: str) -> Dict[str, Any]:
        return {}


class StubQueryAnalyzer(QueryAnalyzerInterface):
    def __init__(self, results: Dict[str, AspectAnalysisResult]):
        self._results = results

    def analyze_aspect(
        self,
        query: str,
        aspect: RefinementAspect,
        dependency_context: Optional[Dict[str, str]] = None,
        llm_provider: Optional[LLMProviderInterface] = None,
    ) -> AspectAnalysisResult:
        return self._results.get(
            aspect.id,
            AspectAnalysisResult(
                needs_refinement=True,
                explanation="Default",
                clarifying_question="Question?"
            )
        )


# ---------------------------------------------------------------------------
# Test 1: Follow-Up Prompt Includes Synthesis Instructions
# ---------------------------------------------------------------------------

def test_follow_up_prompt_includes_synthesis_instructions():
    """Verify follow-up prompts instruct LLM to synthesize all conversation history."""
    aspect = make_aspect(aspect_id="population", name="Population")
    refiner = QueryAspectRefiner(refinement_aspect=aspect)
    
    # Simulate multi-turn conversation
    refiner.add_follow_up("What age group?", "Well, I'm thinking probably adults")
    refiner.add_follow_up("Specific ages?", "Maybe like 18 to 65 or so")
    refiner.add_follow_up("Any conditions?", "Yeah definitely Type 2 diabetes")
    
    prompt = refiner.format_follow_up_prompt_template("Original query")
    
    # Check for synthesis instructions (updated to use aspect.id field)
    assert "FOLLOW-UP CONTEXT" in prompt
    assert "FINAL SYNTHESIZED value" in prompt or "CUMULATIVE SYNTHESIZED value" in prompt
    assert "Combines ALL user responses" in prompt
    assert "entire conversation history" in prompt
    
    # Check for cleaning instructions
    assert "Removes conversational language" in prompt
    assert "I think" in prompt  # Example of what to remove
    assert "maybe" in prompt
    assert "probably" in prompt
    assert "Removes filler words" in prompt
    assert "Removes meta-commentary" in prompt
    
    # Check for declarative statement instruction
    assert "declarative statement" in prompt
    assert "not as an answer to a question" in prompt
    
    # Check for examples (now using aspect.id field instead of final_value)
    assert "GOOD population" in prompt or "GOOD" in prompt
    assert "BAD population" in prompt or "BAD" in prompt
    assert "Adults aged 18-65 with Type 2 diabetes" in prompt  # Good example
    
    # Verify conversation history is included
    assert "What age group?" in prompt
    assert "adults" in prompt
    assert "18 to 65" in prompt
    assert "Type 2 diabetes" in prompt


def test_follow_up_prompt_includes_conversation_history():
    """Verify all Q&A pairs are included in follow-up prompts."""
    aspect = make_aspect()
    refiner = QueryAspectRefiner(refinement_aspect=aspect)
    
    refiner.add_follow_up("Question 1", "Answer 1")
    refiner.add_follow_up("Question 2", "Answer 2")
    refiner.add_follow_up("Question 3", "Answer 3")
    
    prompt = refiner.format_follow_up_prompt_template("Test query")
    
    # All Q&A pairs should be present
    assert "Follow-up 1" in prompt
    assert "Question 1" in prompt
    assert "Answer 1" in prompt
    
    assert "Follow-up 2" in prompt
    assert "Question 2" in prompt
    assert "Answer 2" in prompt
    
    assert "Follow-up 3" in prompt
    assert "Question 3" in prompt
    assert "Answer 3" in prompt
    
    # Conversation history section should be present
    assert "Conversation history for this aspect:" in prompt


# ---------------------------------------------------------------------------
# Test 2: Dependency Context Includes Description
# ---------------------------------------------------------------------------

def test_dependency_context_includes_description():
    """Verify dependency context now includes aspect description."""
    dep_aspect = make_aspect(
        aspect_id="population",
        name="Population",
        description="Define the target population for your research"
    )
    target_aspect = make_aspect(
        aspect_id="intervention",
        name="Intervention",
        description="Specify the intervention or exposure",
        depends_on=["population"]
    )
    
    session = QueryRefinementSession(original_query="test query")
    dep_step = session.add_step(dep_aspect)
    dep_step.add_follow_up("Q", "Adults aged 18-65")
    dep_step.is_complete = True
    
    target_step = session.add_step(target_aspect)
    
    context = session.get_dependency_context("intervention")
    
    # Verify structure includes description
    assert "population" in context
    assert "name" in context["population"]
    assert "description" in context["population"]
    assert "value" in context["population"]
    
    # Verify values
    assert context["population"]["name"] == "Population"
    assert context["population"]["description"] == "Define the target population for your research"
    assert context["population"]["value"] == "Adults aged 18-65"


def test_dependency_context_prioritizes_refined_value():
    """Verify dependency context prioritizes refined_value over final_response."""
    dep_aspect = make_aspect(aspect_id="time_period", name="Time Period", description="Time constraints")
    
    session = QueryRefinementSession(original_query="test")
    dep_step = session.add_step(dep_aspect)
    
    # Simulate follow-up completion with synthesis in refined_value
    dep_step.add_follow_up("What timeframe?", "Well, maybe recent studies")
    dep_step.add_follow_up("How recent?", "I guess like 2020 onwards")
    dep_step.refined_value = "Studies published 2020-2025"  # Synthesized value
    dep_step.is_complete = True
    
    target_aspect = make_aspect(aspect_id="target", depends_on=["time_period"])
    session.add_step(target_aspect)
    
    context = session.get_dependency_context("target")
    
    # Should use refined_value (synthesized), not final_response (raw last answer)
    assert context["time_period"]["value"] == "Studies published 2020-2025"
    # NOT "I guess like 2020 onwards" (the raw last answer)


def test_dependency_context_fallback_chain():
    """Verify dependency context fallback priority: refined_value > final_response > history > clear > skipped."""
    session = QueryRefinementSession(original_query="original")
    
    # Test Priority 1: refined_value
    aspect1 = make_aspect(aspect_id="a1", name="A1", description="D1")
    step1 = session.add_step(aspect1)
    step1.refined_value = "Synthesized value"
    step1.is_complete = True
    
    # Test Priority 2: final_response (when no refined_value)
    aspect2 = make_aspect(aspect_id="a2", name="A2", description="D2")
    step2 = session.add_step(aspect2)
    step2.add_follow_up("Q", "Raw answer")
    step2.is_complete = True
    
    # Test Priority 5: skipped
    aspect3 = make_aspect(aspect_id="a3", name="A3", description="D3")
    step3 = session.add_step(aspect3)
    step3.was_skipped = True
    
    # Target aspect depends on all
    target = make_aspect(aspect_id="target", depends_on=["a1", "a2", "a3"])
    session.add_step(target)
    
    context = session.get_dependency_context("target")
    
    assert context["a1"]["value"] == "Synthesized value"
    assert context["a2"]["value"] == "Raw answer"
    assert "declined to provide" in context["a3"]["value"]


# ---------------------------------------------------------------------------
# Test 3: Prompt Rendering Includes Description
# ---------------------------------------------------------------------------

def test_get_prompts_formats_dependency_with_description():
    """Verify get_prompts formats dependencies with name, description, and value."""
    target_aspect = make_aspect(
        aspect_id="intervention",
        name="Intervention",
        depends_on=["population", "timeframe"]
    )
    refiner = QueryAspectRefiner(refinement_aspect=target_aspect)
    
    dependency_context = {
        "population": {
            "name": "Population",
            "description": "Define the target population",
            "value": "Adults aged 18-65 with Type 2 diabetes"
        },
        "timeframe": {
            "name": "Time Period",
            "description": "Temporal constraints for the study",
            "value": "Studies published 2020-2025"
        }
    }
    
    system_prompt, user_prompt = refiner.get_prompts(
        query="Test query",
        dependency_context=dependency_context
    )
    
    # Check formatting with description
    assert "**Population** (Define the target population): Adults aged 18-65 with Type 2 diabetes" in user_prompt
    assert "**Time Period** (Temporal constraints for the study): Studies published 2020-2025" in user_prompt
    
    # Check section header
    assert "Previous refinements" in user_prompt
    assert "authoritative context" in user_prompt


def test_get_prompts_handles_missing_description():
    """Verify get_prompts handles missing description gracefully."""
    target_aspect = make_aspect(aspect_id="target", depends_on=["dep"])
    refiner = QueryAspectRefiner(refinement_aspect=target_aspect)
    
    dependency_context = {
        "dep": {
            "name": "Dependency",
            "description": "",  # Empty description
            "value": "Some value"
        }
    }
    
    system_prompt, user_prompt = refiner.get_prompts(
        query="Test",
        dependency_context=dependency_context
    )
    
    # Should format without description when empty
    assert "**Dependency**: Some value" in user_prompt
    # Should NOT have empty parentheses
    assert "**Dependency** (): " not in user_prompt


# ---------------------------------------------------------------------------
# Test 4: Final Synthesis Prompt Enhancement
# ---------------------------------------------------------------------------

def test_synthesis_prompt_includes_quality_requirements():
    """Verify synthesize_refined_query includes enhanced quality instructions."""
    aspect = make_aspect(aspect_id="pop", name="Population")
    llm = StubLLMProvider(responses=["Refined output"])
    analyzer = StubQueryAnalyzer({})
    manager = QueryRefinementManager(llm_provider=llm, query_analyzer=analyzer)
    
    session = QueryRefinementSession(original_query="I think maybe adults with diabetes")
    step = session.add_step(aspect)
    step.add_follow_up("Q", "Well, probably 18-65 years old")
    step.is_complete = True
    
    result = manager.synthesize_refined_query(session)
    
    # Check that quality requirements were in the prompt
    assert len(llm.calls) == 1
    user_prompt = llm.calls[0]["user_prompt"]
    
    # Should mention synthesis quality
    assert "SYNTHESIS QUALITY REQUIREMENTS" in user_prompt or "synthesize" in user_prompt.lower()
    
    # Should mention removing conversational language
    assert "conversational language" in user_prompt.lower() or \
           "I think" in user_prompt or \
           "maybe" in user_prompt or \
           "probably" in user_prompt


def test_synthesis_uses_refined_value_when_available():
    """Verify synthesis uses refined_value (synthesized value) over raw responses."""
    aspect1 = make_aspect(aspect_id="a1", name="Aspect 1")
    aspect2 = make_aspect(aspect_id="a2", name="Aspect 2")
    
    llm = StubLLMProvider(responses=["Final refined query"])
    analyzer = StubQueryAnalyzer({})
    manager = QueryRefinementManager(llm_provider=llm, query_analyzer=analyzer)
    
    session = QueryRefinementSession(original_query="test")
    
    # Step with refined_value (synthesized)
    step1 = session.add_step(aspect1)
    step1.add_follow_up("Q1", "Well, I think adults")
    step1.add_follow_up("Q2", "Maybe 18-65")
    step1.refined_value = "Adults aged 18-65"  # Clean synthesized value
    step1.is_complete = True
    
    # Step without follow-ups but with refined_value (aspect was clear)
    step2 = session.add_step(aspect2)
    step2.refined_value = "Already clear in query"
    step2.is_complete = True
    
    result = manager.synthesize_refined_query(session)
    
    # Gather what was sent to LLM
    clarifications, summaries = manager._gather_refinement_details(session)
    
    # Should use refined_value for step1
    assert ("Aspect 1", "Adults aged 18-65") in clarifications
    # Should use refined_value for step2
    assert ("Aspect 2", "Already clear in query") in summaries


# ---------------------------------------------------------------------------
# Test 5: End-to-End Integration
# ---------------------------------------------------------------------------

def test_end_to_end_dependency_with_synthesis():
    """
    Integration test: Multi-turn follow-ups with dependencies should pass
    synthesized values to dependent aspects.
    """
    # Define aspects with dependency
    population = make_aspect(
        aspect_id="population",
        name="Population",
        description="Target population",
        allow_follow_up=True
    )
    intervention = make_aspect(
        aspect_id="intervention",
        name="Intervention",
        description="Intervention or exposure",
        depends_on=["population"],
        allow_follow_up=True
    )
    
    session = QueryRefinementSession(original_query="diabetes treatment study")
    
    # Simulate population refinement with multiple follow-ups
    pop_step = session.add_step(population)
    pop_step.add_follow_up("Age group?", "I think adults")
    pop_step.add_follow_up("Specific ages?", "Maybe 18 to 65")
    pop_step.add_follow_up("Conditions?", "Type 2 diabetes obviously")
    pop_step.refined_value = "Adults aged 18-65 with Type 2 diabetes (excluding gestational diabetes)"
    pop_step.is_complete = True
    
    # Add intervention step
    int_step = session.add_step(intervention)
    
    # Get dependency context for intervention
    context = session.get_dependency_context("intervention")
    
    # Verify intervention receives synthesized value, not raw last answer
    assert context["population"]["name"] == "Population"
    assert context["population"]["description"] == "Target population"
    assert context["population"]["value"] == "Adults aged 18-65 with Type 2 diabetes (excluding gestational diabetes)"
    # NOT "Type 2 diabetes obviously" (the raw last answer)
    
    # Verify prompt formatting
    system_prompt, user_prompt = int_step.get_prompts(
        query=session.original_query,
        dependency_context=context
    )
    
    # Should have well-formatted dependency context
    assert "**Population** (Target population):" in user_prompt
    assert "Adults aged 18-65 with Type 2 diabetes" in user_prompt
    # Should NOT contain conversational language from original answers
    assert "I think" not in user_prompt
    assert "Maybe" not in user_prompt
    assert "obviously" not in user_prompt


def test_multiple_dependencies_with_descriptions():
    """Test aspect depending on multiple aspects receives all descriptions."""
    pop = make_aspect(aspect_id="pop", name="Population", description="Population desc")
    time = make_aspect(aspect_id="time", name="Time", description="Time desc")
    outcome = make_aspect(
        aspect_id="outcome",
        name="Outcome",
        description="Outcome desc",
        depends_on=["pop", "time"]
    )
    
    session = QueryRefinementSession(original_query="test")
    
    pop_step = session.add_step(pop)
    pop_step.refined_value = "Adults"
    pop_step.is_complete = True
    
    time_step = session.add_step(time)
    time_step.refined_value = "2020-2025"
    time_step.is_complete = True
    
    outcome_step = session.add_step(outcome)
    
    context = session.get_dependency_context("outcome")
    
    # Both dependencies should have descriptions
    assert context["pop"]["description"] == "Population desc"
    assert context["time"]["description"] == "Time desc"
    
    system_prompt, user_prompt = outcome_step.get_prompts(
        query="test",
        dependency_context=context
    )
    
    # Both should be formatted with descriptions
    assert "**Population** (Population desc): Adults" in user_prompt
    assert "**Time** (Time desc): 2020-2025" in user_prompt


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
