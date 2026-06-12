from __future__ import annotations

import pytest
from types import SimpleNamespace

from query_refinement_module.core import QueryRefinementManager
from query_refinement_module.api.routes.refinement import _dimension_value_is_accepted
from query_refinement_module.schema.search_expansion import SearchExpansionPromptBuilder
from query_refinement_module.schema.response import (
    AspectSafety,
    DEFAULT_ASPECT_SAFETY,
    ExpansionStrategy,
    SearchAspect,
    SearchAspectAssessment,
    SearchAspectAssessmentResponse,
    SearchExpansionContext,
    SearchExpansionInput,
    SearchExpansionLevel,
    SearchExpansionResponse,
    SearchFilters,
)


class StubProvider:
    """Returns queued responses, one per LLM call, in order."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    async def complete_async(self, **kwargs):
        self.calls.append(kwargs)
        response = self.responses.pop(0)
        return SimpleNamespace(
            context=response,
            metadata={"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
        )


ANCHOR = "Studies of heatwave impacts on pregnant people in London."


def _search_input() -> SearchExpansionInput:
    return SearchExpansionInput(
        anchor_query=ANCHOR,
        advisory_dimensions={
            "population": "pregnant people",
            "condition": "heatwave impacts",
            "geography": "London",
        },
        search_context=SearchExpansionContext(
            filters=SearchFilters(fields_of_study=["Medicine"]).model_dump(exclude_none=True),
            synonyms={"heatwave": ["extreme heat"]},
        ),
    )


def _assessment_response(detected_aspects=None) -> SearchAspectAssessmentResponse:
    detected_aspects = detected_aspects if detected_aspects is not None else {
        SearchAspect.TOPIC_OR_CONDITION: ("heatwave impacts", ["extreme weather impacts"]),
        SearchAspect.POPULATION_OR_ENTITY: ("pregnant people", ["women of reproductive age"]),
        SearchAspect.GEOGRAPHY: ("London", ["urban UK settings", "United Kingdom"]),
    }
    assessments = []
    for aspect in SearchAspect:
        if aspect in detected_aspects:
            value, candidates = detected_aspects[aspect]
            assessments.append(
                SearchAspectAssessment(
                    aspect=aspect,
                    detected=True,
                    detected_value=value,
                    broadening_candidates=candidates,
                    reasoning="present in anchor",
                )
            )
        else:
            assessments.append(SearchAspectAssessment(aspect=aspect, detected=False))
    return SearchAspectAssessmentResponse(assessments=assessments)


def _valid_expansion_response() -> SearchExpansionResponse:
    return SearchExpansionResponse(
        levels=[
            SearchExpansionLevel(
                level=1,
                label="Lexical variants",
                strategy=ExpansionStrategy.LEXICAL,
                search_query="Studies of heatwave or extreme heat impacts on pregnant people in London.",
                relaxed_aspects={},
                rationale="Adds synonym variants without conceptual broadening.",
            ),
            SearchExpansionLevel(
                level=2,
                label="Broader geography",
                strategy=ExpansionStrategy.CONCEPTUAL_SINGLE_ASPECT,
                search_query="Studies of heatwave impacts on pregnant people in urban UK settings.",
                relaxed_aspects={"geography": "urban UK settings"},
                rationale="Broadens London to comparable urban UK settings for recall.",
            ),
        ]
    )


def _allowed_aspects() -> dict:
    return {
        SearchAspect.TOPIC_OR_CONDITION.value: AspectSafety.SAFE,
        SearchAspect.POPULATION_OR_ENTITY.value: AspectSafety.SAFE,
        SearchAspect.GEOGRAPHY.value: AspectSafety.SAFE,
    }


# ---------------------------------------------------------------------------
# Prompt builder
# ---------------------------------------------------------------------------

def test_prompt_builder_system_prompts_non_empty():
    system_prompt = SearchExpansionPromptBuilder.get_system_prompt()
    assert system_prompt
    assert "concise, readable" in system_prompt
    assert SearchExpansionPromptBuilder.get_assessment_system_prompt()


def test_assessment_user_prompt_includes_anchor_and_advisory_context():
    prompt = SearchExpansionPromptBuilder.get_assessment_user_prompt(_search_input())

    assert ANCHOR in prompt
    assert "pregnant people" in prompt
    assert "extreme heat" in prompt
    assert "non-authoritative" in prompt


def test_expansion_user_prompt_includes_anchor_and_allowed_aspects_only():
    assessments = QueryRefinementManager._apply_aspect_safety_policy(
        _assessment_response().assessments
    )

    prompt = SearchExpansionPromptBuilder.get_user_prompt(_search_input(), assessments)

    assert ANCHOR in prompt
    assert "Level 0" in prompt
    assert "geography" in prompt
    assert "urban UK settings" in prompt
    assert "extreme heat" in prompt
    # Undetected aspects are AVOID and must not be offered for broadening
    assert "time_scope" not in prompt


# ---------------------------------------------------------------------------
# Safety policy
# ---------------------------------------------------------------------------

def test_safety_policy_assigns_defaults_and_marks_undetected_avoid():
    classified = QueryRefinementManager._apply_aspect_safety_policy(
        _assessment_response().assessments
    )

    by_aspect = {a.aspect: a for a in classified}
    assert len(by_aspect) == len(SearchAspect)
    assert by_aspect[SearchAspect.GEOGRAPHY].safety == AspectSafety.SAFE
    assert by_aspect[SearchAspect.TIME_SCOPE].safety == AspectSafety.AVOID  # not detected


def test_safety_policy_marks_detected_intervention_conditional():
    detected = {
        SearchAspect.INTERVENTION_OR_EXPOSURE_OR_PHENOMENON: ("heat exposure", ["climate exposure"]),
    }
    classified = QueryRefinementManager._apply_aspect_safety_policy(
        _assessment_response(detected).assessments
    )

    by_aspect = {a.aspect: a for a in classified}
    assert (
        by_aspect[SearchAspect.INTERVENTION_OR_EXPOSURE_OR_PHENOMENON].safety
        == AspectSafety.CONDITIONAL
    )


def test_safety_policy_fills_missing_aspects_as_avoid():
    partial = [
        SearchAspectAssessment(
            aspect=SearchAspect.GEOGRAPHY,
            detected=True,
            detected_value="London",
        )
    ]

    classified = QueryRefinementManager._apply_aspect_safety_policy(partial)

    assert len(classified) == len(SearchAspect)
    assert all(a.safety is not None for a in classified)


def test_default_policy_marks_intervention_conditional_only():
    conditional = [a for a, s in DEFAULT_ASPECT_SAFETY.items() if s == AspectSafety.CONDITIONAL]
    assert conditional == [SearchAspect.INTERVENTION_OR_EXPOSURE_OR_PHENOMENON]


# ---------------------------------------------------------------------------
# Response model validation
# ---------------------------------------------------------------------------

def test_search_expansion_response_parses_valid_llm_output():
    parsed = SearchExpansionResponse(
        levels=[
            {
                "level": 1,
                "label": "Direct broadening",
                "strategy": "conceptual_single_aspect",
                "search_query": "query",
                "relaxed_aspects": {"geography": "UK"},
                "rationale": "reason",
            }
        ]
    )

    assert parsed.levels[0].level == 1
    assert parsed.levels[0].strategy == ExpansionStrategy.CONCEPTUAL_SINGLE_ASPECT


def test_search_expansion_level_rejects_empty_search_query():
    with pytest.raises(ValueError):
        SearchExpansionLevel(
            level=1,
            label="Label",
            search_query="",
            relaxed_aspects={},
            rationale="reason",
        )


def test_aspect_assessment_requires_value_when_detected():
    with pytest.raises(ValueError):
        SearchAspectAssessment(aspect=SearchAspect.GEOGRAPHY, detected=True, detected_value="")


# ---------------------------------------------------------------------------
# Contextual validation against allowed aspects
# ---------------------------------------------------------------------------

def test_validate_accepts_valid_levels():
    assert QueryRefinementManager._validate_search_expansion_result(
        _valid_expansion_response(),
        _allowed_aspects(),
    ) is None


def test_validate_rejects_duplicate_level_numbers():
    result = SearchExpansionResponse(
        levels=[
            {"level": 1, "label": "A", "search_query": "q1", "relaxed_aspects": {}, "rationale": "r1"},
            {"level": 1, "label": "B", "search_query": "q2", "relaxed_aspects": {}, "rationale": "r2"},
        ]
    )

    error = QueryRefinementManager._validate_search_expansion_result(result, {})

    assert "duplicate level number" in error


def test_validate_rejects_disallowed_relaxed_aspects():
    result = SearchExpansionResponse(
        levels=[
            {
                "level": 1,
                "label": "Bad key",
                "search_query": "query",
                "relaxed_aspects": {"time_scope": "any period"},
                "rationale": "reason",
            }
        ]
    )

    error = QueryRefinementManager._validate_search_expansion_result(result, _allowed_aspects())

    assert "disallowed aspects" in error


def test_validate_rejects_more_than_two_relaxed_aspects():
    result = SearchExpansionResponse(
        levels=[
            {
                "level": 1,
                "label": "Too broad",
                "search_query": "query",
                "relaxed_aspects": {
                    "topic_or_condition": "1",
                    "population_or_entity": "2",
                    "geography": "3",
                },
                "rationale": "reason",
            }
        ]
    )

    error = QueryRefinementManager._validate_search_expansion_result(result, _allowed_aspects())

    assert "more than two aspects" in error


def test_validate_rejects_two_conditional_aspects_in_one_level():
    allowed = {
        SearchAspect.GEOGRAPHY.value: AspectSafety.CONDITIONAL,
        SearchAspect.SETTING_OR_CONTEXT.value: AspectSafety.CONDITIONAL,
    }
    result = SearchExpansionResponse(
        levels=[
            {
                "level": 1,
                "label": "Two conditional",
                "strategy": "conceptual_multi_aspect",
                "search_query": "query",
                "relaxed_aspects": {"geography": "UK", "setting_or_context": "any setting"},
                "rationale": "reason",
            }
        ]
    )

    error = QueryRefinementManager._validate_search_expansion_result(result, allowed)

    assert "conditional" in error


def test_validate_rejects_two_relaxed_aspects_with_single_aspect_strategy():
    result = SearchExpansionResponse(
        levels=[
            {
                "level": 3,
                "label": "Mislabeled multi-aspect broadening",
                "strategy": "conceptual_single_aspect",
                "search_query": "query",
                "relaxed_aspects": {"geography": "Pakistan", "setting_or_context": "outpatient care"},
                "rationale": "reason",
            }
        ]
    )

    error = QueryRefinementManager._validate_search_expansion_result(result, {
        SearchAspect.GEOGRAPHY.value: AspectSafety.SAFE,
        SearchAspect.SETTING_OR_CONTEXT.value: AspectSafety.SAFE,
    })

    assert "single-aspect strategy" in error


def test_validate_rejects_anchor_strategy_in_generated_levels():
    result = SearchExpansionResponse(
        levels=[
            {
                "level": 1,
                "label": "Anchor restated",
                "strategy": "anchor",
                "search_query": "query",
                "relaxed_aspects": {},
                "rationale": "reason",
            }
        ]
    )

    error = QueryRefinementManager._validate_search_expansion_result(result, _allowed_aspects())

    assert "anchor strategy" in error


def test_validate_rejects_more_than_four_generated_levels():
    result = SearchExpansionResponse(
        levels=[
            {"level": i, "label": f"L{i}", "search_query": f"q{i}", "relaxed_aspects": {}, "rationale": f"r{i}"}
            for i in range(1, 6)
        ]
    )

    error = QueryRefinementManager._validate_search_expansion_result(result, {})

    assert "at most four" in error


# ---------------------------------------------------------------------------
# Orchestration pipeline
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_pipeline_injects_deterministic_level_0_and_runs_two_calls():
    provider = StubProvider([_assessment_response(), _valid_expansion_response()])
    manager = QueryRefinementManager(provider)

    levels, metadata = await manager.generate_search_expansion_levels(
        search_input=_search_input(),
    )

    assert len(provider.calls) == 2
    assert levels[0].level == 0
    assert levels[0].search_query == ANCHOR
    assert levels[0].strategy == ExpansionStrategy.ANCHOR
    assert levels[0].relaxed_aspects == {}
    assert levels[1].strategy == ExpansionStrategy.LEXICAL
    assert metadata["status"] == "completed"
    assert metadata["used_llm"] is True
    assert metadata["generated_level_count"] == 2
    # Token usage accumulated across both calls
    assert metadata["total_tokens"] == 30


@pytest.mark.asyncio
async def test_pipeline_exposes_assessment_summary_metadata():
    provider = StubProvider([_assessment_response(), _valid_expansion_response()])
    manager = QueryRefinementManager(provider)

    _, metadata = await manager.generate_search_expansion_levels(
        search_input=_search_input(),
    )

    summary = metadata["aspect_assessment"]
    assert SearchAspect.GEOGRAPHY.value in summary["safe_aspects"]
    assert SearchAspect.TIME_SCOPE.value in summary["avoided_aspects"]
    assert len(summary["assessed_aspects"]) == len(SearchAspect)
    assert metadata["allowed_aspect_count"] == 3


@pytest.mark.asyncio
async def test_pipeline_skips_expansion_when_no_aspects_detected():
    provider = StubProvider([_assessment_response(detected_aspects={})])
    manager = QueryRefinementManager(provider)

    levels, metadata = await manager.generate_search_expansion_levels(
        search_input=_search_input(),
    )

    assert len(provider.calls) == 1  # assessment only, no expansion call
    assert len(levels) == 1
    assert levels[0].level == 0
    assert metadata["status"] == "skipped_no_assessable_aspects"


@pytest.mark.asyncio
async def test_pipeline_soft_fails_to_level_0_when_assessment_fails():
    provider = StubProvider(["not json at all"])
    manager = QueryRefinementManager(provider)

    levels, metadata = await manager.generate_search_expansion_levels(
        search_input=_search_input(),
    )

    assert len(levels) == 1
    assert levels[0].search_query == ANCHOR
    assert metadata["status"] == "failed_level_0_only"


@pytest.mark.asyncio
async def test_pipeline_soft_fails_to_level_0_when_expansion_invalid_after_repair():
    invalid = SearchExpansionResponse(
        levels=[
            SearchExpansionLevel(
                level=1,
                label="Bad",
                search_query="query",
                relaxed_aspects={"time_scope": "any period"},
                rationale="reason",
            )
        ]
    )
    provider = StubProvider([_assessment_response(), invalid, invalid])
    manager = QueryRefinementManager(provider)

    levels, metadata = await manager.generate_search_expansion_levels(
        search_input=_search_input(),
    )

    assert len(provider.calls) == 3  # assessment + expansion + one repair
    assert len(levels) == 1
    assert metadata["status"] == "failed_level_0_only"


@pytest.mark.asyncio
async def test_pipeline_repair_recovers_invalid_expansion():
    invalid = SearchExpansionResponse(
        levels=[
            SearchExpansionLevel(
                level=1,
                label="Bad",
                search_query="query",
                relaxed_aspects={"time_scope": "any period"},
                rationale="reason",
            )
        ]
    )
    provider = StubProvider([_assessment_response(), invalid, _valid_expansion_response()])
    manager = QueryRefinementManager(provider)

    levels, metadata = await manager.generate_search_expansion_levels(
        search_input=_search_input(),
    )

    assert len(provider.calls) == 3
    assert metadata["status"] == "completed"
    assert len(levels) == 3


# ---------------------------------------------------------------------------
# API helper
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("value, expected", [
    (None, False),
    ("", False),
    ("[SKIPPED]", False),
    ("null", False),
    ("London", True),
    ({"city": "London"}, True),
])
def test_api_dimension_value_acceptance_filter(value, expected):
    assert _dimension_value_is_accepted(value) is expected
