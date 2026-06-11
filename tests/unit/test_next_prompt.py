from types import SimpleNamespace

import pytest

from query_refinement_module.next_prompt import resolve_next_prompt


class Step:
    def __init__(self, aspect_id: str, name: str, question: str | None = None):
        self.refinement_aspect = SimpleNamespace(id=aspect_id, name=name)
        self.follow_up_question = question
        self.reasoning = None
        self.is_complete = False
        self.normalized_value_as_str = None


class Session:
    def __init__(self, steps):
        self.steps = steps

    def get_next_unrefined_aspect(self):
        for step in self.steps:
            if not step.is_complete:
                return step
        return None


@pytest.mark.asyncio
async def test_resolve_next_prompt_prefers_existing_follow_up_question():
    session = Session([Step("population", "Population", question="Who is included?")])

    async def analyze_initial(step):
        raise AssertionError("analysis should not run when a question already exists")

    payload = await resolve_next_prompt(
        session,
        analyze_initial=analyze_initial,
        process_analysis_result=lambda step, result: result,
        build_payload=lambda session, step, question: {
            "aspect_id": step.refinement_aspect.id,
            "question": question,
        },
    )

    assert payload == {"aspect_id": "population", "question": "Who is included?"}


@pytest.mark.asyncio
async def test_resolve_next_prompt_skips_auto_completed_steps():
    first = Step("population", "Population")
    second = Step("context", "Context")
    session = Session([first, second])
    completed = []
    results = iter(
        [
            {"complete": True, "current": "adults"},
            {"complete": False, "next_question": "Which setting?"},
        ]
    )

    async def analyze_initial(step):
        return next(results)

    def process_analysis_result(step, result):
        if result.get("complete"):
            step.is_complete = True
            step.normalized_value_as_str = result.get("current")
        else:
            step.follow_up_question = result.get("next_question")
        return result

    def on_auto_completed(step, status):
        completed.append((step.refinement_aspect.id, status["current"]))

    payload = await resolve_next_prompt(
        session,
        analyze_initial=analyze_initial,
        process_analysis_result=process_analysis_result,
        build_payload=lambda session, step, question: {
            "aspect_id": step.refinement_aspect.id,
            "question": question,
        },
        on_auto_completed=on_auto_completed,
    )

    assert payload == {"aspect_id": "context", "question": "Which setting?"}
    assert completed == [("population", "adults")]


@pytest.mark.asyncio
async def test_resolve_next_prompt_uses_fallback_when_analysis_fails():
    session = Session([Step("population", "Population")])

    async def analyze_initial(step):
        raise RuntimeError("boom")

    payload = await resolve_next_prompt(
        session,
        analyze_initial=analyze_initial,
        process_analysis_result=lambda step, result: result,
        build_payload=lambda session, step, question: {
            "aspect_id": step.refinement_aspect.id,
            "question": question,
        },
    )

    assert payload == {
        "aspect_id": "population",
        "question": "Please provide details about Population",
    }
    assert session.steps[0].follow_up_question == "Please provide details about Population"