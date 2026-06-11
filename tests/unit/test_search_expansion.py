from __future__ import annotations

import pytest
from types import SimpleNamespace

from query_refinement_module.core import QueryRefinementManager
from query_refinement_module.api.routes.refinement import _dimension_value_is_accepted
from query_refinement_module.schema.search_expansion import SearchExpansionPromptBuilder
from query_refinement_module.schema.response import (
    SearchExpansionContext,
    SearchExpansionInput,
    SearchExpansionLevel,
    SearchExpansionResponse,
    SearchFilters,
)


class StubProvider:
    def __init__(self, response):
        self.response = response
        self.calls = []

    async def complete_async(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(
            context=self.response,
            metadata={"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
        )


def _search_input() -> SearchExpansionInput:
    return SearchExpansionInput(
        anchor_query="Studies of heatwave impacts on pregnant people in London.",
        eligible_dimensions={
            "population": "pregnant people",
            "condition": "heatwave impacts",
            "geography": "London",
        },
        search_context=SearchExpansionContext(
            filters=SearchFilters(fields_of_study=["Medicine"]).model_dump(exclude_none=True),
            synonyms={"heatwave": ["extreme heat"]},
        ),
    )


def _valid_response() -> SearchExpansionResponse:
    return SearchExpansionResponse(
        levels=[
            SearchExpansionLevel(
                level=1,
                label="Broader geography",
                search_query="Studies of heatwave impacts on pregnant people in urban UK settings.",
                relaxed_dimensions={"geography": "urban UK settings"},
                rationale="Broadens London to comparable urban UK settings for recall.",
            )
        ]
    )


def test_prompt_builder_system_prompt_non_empty():
    assert SearchExpansionPromptBuilder.get_system_prompt()


def test_prompt_builder_user_prompt_includes_exact_anchor_and_search_context():
    search_input = _search_input()

    prompt = SearchExpansionPromptBuilder.get_user_prompt(search_input=search_input)

    assert search_input.anchor_query in prompt
    assert "Level 0" in prompt
    assert "geography" in prompt
    assert "extreme heat" in prompt


def test_search_expansion_response_parses_valid_llm_output():
    parsed = SearchExpansionResponse(
        levels=[
            {
                "level": 1,
                "label": "Direct broadening",
                "search_query": "query",
                "relaxed_dimensions": {"geography": "UK"},
                "rationale": "reason",
            }
        ]
    )

    assert parsed.levels[0].level == 1


@pytest.mark.asyncio
async def test_generate_search_expansion_levels_injects_level_0_exactly():
    manager = QueryRefinementManager(StubProvider(_valid_response()))
    search_input = _search_input()

    levels, metadata = await manager.generate_search_expansion_levels(
        search_input=SearchExpansionInput(
            anchor_query=search_input.anchor_query,
            eligible_dimensions={"geography": "London"},
            search_context=search_input.search_context,
        ),
    )

    assert levels[0].level == 0
    assert levels[0].search_query == search_input.anchor_query
    assert levels[1].level == 1
    assert metadata["status"] == "completed"
    assert metadata["generated_level_count"] == 1


@pytest.mark.asyncio
async def test_empty_accepted_dimensions_return_level_0_only():
    provider = StubProvider(_valid_response())
    manager = QueryRefinementManager(provider)
    search_input = _search_input()

    levels, metadata = await manager.generate_search_expansion_levels(
        search_input=SearchExpansionInput(anchor_query=search_input.anchor_query, eligible_dimensions={}),
    )

    assert len(levels) == 1
    assert levels[0].search_query == search_input.anchor_query
    assert provider.calls == []
    assert metadata["status"] == "skipped_no_accepted_dimensions"


def test_validate_search_expansion_result_accepts_valid_levels():
    assert QueryRefinementManager._validate_search_expansion_result(
        _valid_response(),
        {"geography": "London"},
    ) is None


def test_validate_search_expansion_result_rejects_empty_search_query():
    with pytest.raises(ValueError):
        SearchExpansionResponse(
            levels=[
                {
                    "level": 1,
                    "label": "Label",
                    "search_query": "",
                    "relaxed_dimensions": {},
                    "rationale": "reason",
                }
            ]
        )


def test_validate_search_expansion_result_rejects_duplicate_level_numbers():
    result = SearchExpansionResponse(
        levels=[
            {"level": 1, "label": "A", "search_query": "q1", "relaxed_dimensions": {}, "rationale": "r1"},
            {"level": 1, "label": "B", "search_query": "q2", "relaxed_dimensions": {}, "rationale": "r2"},
        ]
    )

    error = QueryRefinementManager._validate_search_expansion_result(result, {})

    assert "duplicate level number" in error


def test_validate_search_expansion_result_rejects_invalid_relaxed_dimension_keys():
    result = SearchExpansionResponse(
        levels=[
            {
                "level": 1,
                "label": "Bad key",
                "search_query": "query",
                "relaxed_dimensions": {"unknown": "value"},
                "rationale": "reason",
            }
        ]
    )

    error = QueryRefinementManager._validate_search_expansion_result(result, {"geography": "London"})

    assert "invalid keys" in error


def test_validate_search_expansion_result_rejects_more_than_two_relaxed_dimensions():
    result = SearchExpansionResponse(
        levels=[
            {
                "level": 1,
                "label": "Too broad",
                "search_query": "query",
                "relaxed_dimensions": {"a": "1", "b": "2", "c": "3"},
                "rationale": "reason",
            }
        ]
    )

    error = QueryRefinementManager._validate_search_expansion_result(
        result,
        {"a": "x", "b": "y", "c": "z"},
    )

    assert "more than two dimensions" in error


def test_validate_search_expansion_result_rejects_more_than_four_generated_levels():
    result = SearchExpansionResponse(
        levels=[
            {"level": i, "label": f"L{i}", "search_query": f"q{i}", "relaxed_dimensions": {}, "rationale": f"r{i}"}
            for i in range(1, 6)
        ]
    )

    error = QueryRefinementManager._validate_search_expansion_result(result, {})

    assert "at most four" in error


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
