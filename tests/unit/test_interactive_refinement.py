from types import SimpleNamespace

import pytest

from query_refinement_module.application.interactive_refinement_helpers import (
    build_search_expansion_input_from_synthesis,
    resolve_numeric_examples,
)
from query_refinement_module.application.interactive_refinement_service import (
    InteractivePrompt,
    InteractiveRefinementService,
)
from query_refinement_module.schema.response import CombinedBlock


class StubStep:
    def __init__(self, *, question=None, history=None):
        self.refinement_aspect = SimpleNamespace(
            id="aspect",
            name="Aspect",
            description="Aspect description",
        )
        self.refinement_question = question
        self.analysis_suggested_question = question
        self.follow_up_history = list(history or [])
        self.quick_replies = []
        self.is_complete = False

    def add_follow_up(self, question, response):
        self.follow_up_history.append({"question": question, "response": response})


class StubSession:
    def __init__(self, step):
        self.step = step
        self.synthesis_requested = False

    def get_next_unrefined_aspect(self):
        if self.step and not self.step.is_complete:
            return self.step
        return None

    def get_active_step(self):
        return self.get_next_unrefined_aspect()

    def get_dependency_context(self, aspect_id):
        return {"population": {"name": "Population", "value": "Adults"}}

    def handle_command(self, command_result):
        if command_result.command.value == "help":
            return {"message": "help text"}
        self.synthesis_requested = True
        return {"message": "submitted", "submit": True}


class StubManager:
    def __init__(self):
        self.analysis_calls = []
        self.followup_calls = []

    def initialize_sequential(self, original_query, refinement_framework):
        return {"original_query": original_query, "framework": refinement_framework}

    async def get_analysis_prompts(self, session, aspect_id, mode="initial"):
        self.analysis_calls.append((aspect_id, mode))
        return SimpleNamespace(complete=False, question="What do you mean?", examples=["Example 1"])

    def process_analysis_result(self, session, aspect_id, result):
        session.step.refinement_question = result.question
        session.step.quick_replies = list(result.examples)
        return {"complete": False}

    async def run_followup_until_clear(self, session, aspect_id=None, max_rounds=5):
        self.followup_calls.append((aspect_id, max_rounds))
        return {"is_complete": True, "rounds": 1}

    async def synthesize_refined_query(self, session):
        return {"clarified_query": "Refined query"}


def test_build_search_expansion_input_from_synthesis_maps_fields():
    synthesis = {
        "clarified_query": "refined query",
        "keyword_statement": "keywords",
        "concept_graph": {"topic": {"query_role": "topic_or_condition"}},
        "search_filters": {"publication_years": "2020-2024"},
        "search_optimized": SimpleNamespace(
            semantic="semantic statement",
            keyword=SimpleNamespace(
                structured="(cancer)",
                phrases=["cancer prevention"],
                combined_blocks=[
                    CombinedBlock(
                        role="topic_or_condition",
                        free_text=["cancer"],
                        controlled_vocabulary={"MeSH": ["Neoplasms"]},
                    )
                ],
            ),
        ),
    }

    result = build_search_expansion_input_from_synthesis(synthesis)

    assert result is not None
    assert result.clarified_query == "refined query"
    assert result.semantic_statement == "semantic statement"
    assert result.keyword_statement == "keywords"
    assert result.keyword_structured == "(cancer)"
    assert result.phrases == ["cancer prevention"]


def test_build_search_expansion_input_from_synthesis_requires_blocks():
    synthesis = {"clarified_query": "refined query", "search_optimized": SimpleNamespace(keyword=None)}

    assert build_search_expansion_input_from_synthesis(synthesis) is None


@pytest.mark.parametrize(
    ("user_input", "examples", "expected", "was_numeric"),
    [
        ("1", ["alpha", "beta"], "alpha", True),
        ("1, 2", ["alpha", "beta"], "alpha | beta", True),
        ("type 1 diabetes", ["alpha", "beta"], "type 1 diabetes", False),
    ],
)
def test_resolve_numeric_examples(user_input, examples, expected, was_numeric):
    assert resolve_numeric_examples(user_input, examples) == (expected, was_numeric)


@pytest.mark.asyncio
async def test_get_next_prompt_uses_existing_legacy_question_without_llm_call():
    manager = StubManager()
    service = InteractiveRefinementService(manager)
    session = StubSession(StubStep(question="Existing question?"))

    prompt = await service.get_next_prompt(session)

    assert isinstance(prompt, InteractivePrompt)
    assert prompt.question == "Existing question?"
    assert prompt.examples == []
    assert manager.analysis_calls == []


@pytest.mark.asyncio
async def test_get_next_prompt_generates_prompt_when_missing_question():
    manager = StubManager()
    service = InteractiveRefinementService(manager)
    session = StubSession(StubStep(question=None, history=[{"response": "prior"}]))

    prompt = await service.get_next_prompt(session)

    assert prompt.question == "What do you mean?"
    assert prompt.examples == ["Example 1"]
    assert manager.analysis_calls == [("aspect", "followup")]


@pytest.mark.asyncio
async def test_submit_input_marks_step_complete_when_followup_finishes():
    manager = StubManager()
    service = InteractiveRefinementService(manager)
    session = StubSession(StubStep(question="Existing question?"))

    result = await service.submit_input(session=session, user_input="answer")

    assert session.step.is_complete is True
    assert result.prompt is None
    assert manager.followup_calls == [("aspect", 5)]


@pytest.mark.asyncio
async def test_submit_input_handles_command_without_regenerating_help_prompt():
    manager = StubManager()
    service = InteractiveRefinementService(manager)
    session = StubSession(StubStep(question="Existing question?"))

    result = await service.submit_input(session=session, user_input="/help")

    assert result.message == "help text"
    assert result.prompt is None
    assert result.synthesis_requested is False