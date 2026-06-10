from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from query_refinement_module.core import QueryRefinementManager
from query_refinement_module.api.routes.refinement import (
    _dimension_value_is_accepted,
    _reconstruct_synthesis_response_from_query,
)
from query_refinement_module.schema.search_expansion import SearchExpansionPromptBuilder
from query_refinement_module.schema.response import (
    KeywordSearch,
    QueryRefinementResponse,
    SearchExpansionLevel,
    SearchExpansionResponse,
    SearchFilters,
    SearchOptimized,
    SearchTerms,
    Terminology,
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


def _synthesis_response() -> QueryRefinementResponse:
    return QueryRefinementResponse(
        integrated_statement="Studies of heatwave impacts on pregnant people in London.",
        dimensions_specifications={
            "population": "pregnant people",
            "condition": "heatwave impacts",
            "geography": "London",
        },
        search_optimized=SearchOptimized(
            semantic="heatwave impacts pregnant people London",
            keyword=KeywordSearch(
                structured="heatwave AND pregnancy",
                phrases=["heatwave impacts"],
                terms=SearchTerms(required=["heatwave"], optional=["pregnancy"], excluded=[]),
            ),
        ),
        search_filters=SearchFilters(fields_of_study=["Medicine"]),
        terminology=Terminology(synonyms={"heatwave": ["extreme heat"]}),
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


def test_prompt_builder_user_prompt_includes_exact_integrated_statement():
    synthesis = _synthesis_response()

    prompt = SearchExpansionPromptBuilder.get_user_prompt(
        synthesis_response=synthesis,
        accepted_dimensions={"geography": "London"},
        original_query="heat and pregnancy",
    )

    assert synthesis.integrated_statement in prompt
    assert "Level 0" in prompt
    assert "geography" in prompt


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
    synthesis = _synthesis_response()

    levels, metadata = await manager.generate_search_expansion_levels(
        original_query="heat and pregnancy",
        synthesis_response=synthesis,
        accepted_dimensions={"geography": "London"},
    )

    assert levels[0].level == 0
    assert levels[0].search_query == synthesis.integrated_statement
    assert levels[1].level == 1
    assert metadata["status"] == "completed"
    assert metadata["generated_level_count"] == 1


@pytest.mark.asyncio
async def test_empty_accepted_dimensions_return_level_0_only():
    provider = StubProvider(_valid_response())
    manager = QueryRefinementManager(provider)
    synthesis = _synthesis_response()

    levels, metadata = await manager.generate_search_expansion_levels(
        original_query="heat and pregnancy",
        synthesis_response=synthesis,
        accepted_dimensions={},
    )

    assert len(levels) == 1
    assert levels[0].search_query == synthesis.integrated_statement
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


def test_api_reconstructs_synthesis_response_from_persisted_query():
    synthesis = _synthesis_response()
    db_query = SimpleNamespace(
        id=42,
        integrated_statement=synthesis.integrated_statement,
        dimensions_specifications=synthesis.dimensions_specifications,
        search_optimized=synthesis.search_optimized.model_dump(),
        search_filters=synthesis.search_filters.model_dump(),
        terminology=synthesis.terminology.model_dump(),
        synthesis_metadata={"source": "test"},
        processing_log=None,
    )

    reconstructed = _reconstruct_synthesis_response_from_query(db_query)

    assert reconstructed.integrated_statement == synthesis.integrated_statement
    assert reconstructed.search_optimized.semantic == synthesis.search_optimized.semantic


def test_api_reconstruct_rejects_queries_without_completed_synthesis():
    db_query = SimpleNamespace(
        id=42,
        integrated_statement=None,
        dimensions_specifications=None,
        search_optimized=None,
        search_filters=None,
        terminology=None,
    )

    with pytest.raises(HTTPException) as exc:
        _reconstruct_synthesis_response_from_query(db_query)

    assert exc.value.status_code == 409


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
