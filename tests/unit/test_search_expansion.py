"""Tests for the block-aware search expansion pipeline (Agent D)."""
from __future__ import annotations

import json
import pytest
from types import SimpleNamespace

from query_refinement_module.core import QueryRefinementManager
from query_refinement_module.api.routes.refinement import _dimension_value_is_accepted
from query_refinement_module.schema.search_expansion import (
    SearchExpansionPromptBuilder,
    build_keyword_statement,
    build_level1_query,
    build_leveln_query,
)
from query_refinement_module.schema.response import (
    CombinedBlock,
    ExpansionLevel,
    SearchExpansionInput,
)


# ─── Stub provider ───────────────────────────────────────────────────────────

class StubProvider:
    """Returns queued raw-text responses, one per LLM call, in order."""

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


# ─── Fixtures ─────────────────────────────────────────────────────────────────

ANCHOR = "How to improve mental health outcomes in children in Qoloji camp, Ethiopia."

GEO_BLOCK = CombinedBlock(
    role="geography",
    free_text=["Qoloji", "Ethiopia", "Ethiopian"],
    controlled_vocabulary={"MeSH": ["Ethiopia"]},
)

SETTING_BLOCK = CombinedBlock(
    role="setting_or_context",
    free_text=["refugee camp", "displacement camp", "IDP camp"],
    controlled_vocabulary={"MeSH": ["Refugee Camps"]},
)

TOPIC_BLOCK = CombinedBlock(
    role="topic_or_condition",
    free_text=["mental health", "MHPSS", "psychological wellbeing"],
    controlled_vocabulary={"MeSH": ["Mental Health"]},
)

POP_BLOCK = CombinedBlock(
    role="population_or_entity",
    free_text=["children", "under-five children", "U5"],
    controlled_vocabulary={"MeSH": ["Child"]},
)


def _geo_input() -> SearchExpansionInput:
    return SearchExpansionInput(
        clarified_query=ANCHOR,
        anchor_blocks=[TOPIC_BLOCK, POP_BLOCK, SETTING_BLOCK, GEO_BLOCK],
        concept_graph={},
    )


def _setting_input() -> SearchExpansionInput:
    return SearchExpansionInput(
        clarified_query="Effectiveness of nurse-led interventions for diabetes in hospitals.",
        anchor_blocks=[
            CombinedBlock(role="topic_or_condition", free_text=["diabetes management"]),
            CombinedBlock(
                role="setting_or_context",
                free_text=["hospitals", "hospital wards", "inpatient setting"],
            ),
        ],
        concept_graph={},
    )


def _geo_llm_response_json() -> str:
    return json.dumps({
        "geography_broadening_strategy": "context_proxy",
        "levels": [
            {
                "level": 2,
                "label": "Contextual analogy — conflict-affected LMICs",
                "broadened_value": "conflict-affected LMICs",
                "boolean_terms": ["conflict-affected low-income countries", "fragile states"],
                "clarified_query": "How to improve mental health outcomes in children in displacement camps in conflict-affected LMICs.",
                "rationale": "Ethiopia is a context proxy for conflict-affected settings.",
            },
            {
                "level": 3,
                "label": "No geographic restriction",
                "broadened_value": "(no restriction)",
                "boolean_terms": [],
                "clarified_query": "How to improve mental health outcomes in children in displacement camps globally.",
                "rationale": "Removes all geographic restriction.",
            },
        ],
        "recommended_starting_level": 2,
        "recommendation_rationale": "Level 1 names a specific camp site with almost no coverage.",
    })


def _setting_llm_response_json() -> str:
    return json.dumps({
        "geography_broadening_strategy": "none",
        "levels": [
            {
                "level": 2,
                "label": "Broader care settings",
                "broadened_value": "hospitals or clinics or outpatient care settings",
                "boolean_terms": ["hospitals", "clinics", "outpatient care settings"],
                "clarified_query": "Effectiveness of nurse-led interventions for diabetes in hospitals or clinics or outpatient care settings.",
                "rationale": "Broadens the setting to adjacent care contexts.",
            }
        ],
        "recommended_starting_level": 1,
        "recommendation_rationale": "Level 1 is likely sufficient; Level 2 adds setting breadth.",
    })


# ─── Prompt builder ───────────────────────────────────────────────────────────

def test_prompt_builder_system_prompt_contains_cochrane_guidance():
    system_prompt = SearchExpansionPromptBuilder.get_system_prompt()
    assert system_prompt
    assert "Cochrane" in system_prompt
    assert "geography" in system_prompt.lower()


def test_user_prompt_contains_anchor_and_level1_query():
    level1_query = "(mental health OR MHPSS) AND (children)"
    prompt = SearchExpansionPromptBuilder.get_user_prompt(_geo_input(), level1_query)
    assert ANCHOR in prompt
    assert level1_query in prompt


def test_user_prompt_includes_geography_block_instructions_when_geo_present():
    level1_query = "(mental health) AND (Qoloji OR Ethiopia)"
    prompt = SearchExpansionPromptBuilder.get_user_prompt(_geo_input(), level1_query)
    assert "Geography block" in prompt
    assert "Qoloji" in prompt


def test_user_prompt_includes_setting_block_instructions_when_no_geo():
    level1_query = "(diabetes management) AND (hospitals)"
    prompt = SearchExpansionPromptBuilder.get_user_prompt(_setting_input(), level1_query, broadened_role="setting_or_context")
    assert "Setting/context block" in prompt
    assert "hospitals" in prompt


# ─── build_level1_query ──────────────────────────────────────────────────────

def test_build_level1_query_joins_blocks_with_and():
    blocks = [
        CombinedBlock(role="topic", free_text=["cancer", "neoplasm"]),
        CombinedBlock(role="population", free_text=["children", "pediatric"]),
    ]
    query, _ = build_level1_query(blocks, {})
    assert " AND " in query
    assert query.startswith("(")


def test_build_level1_query_or_joins_terms_within_block():
    blocks = [CombinedBlock(role="topic", free_text=["cancer", "neoplasm", "tumour"])]
    query, _ = build_level1_query(blocks, {})
    assert "cancer OR neoplasm OR tumour" in query


def test_build_level1_query_merges_controlled_vocabulary():
    blocks = [
        CombinedBlock(
            role="topic",
            free_text=["cancer"],
            controlled_vocabulary={"MeSH": ["Neoplasms"], "PsycINFO": ["Cancer"]},
        )
    ]
    _, cv = build_level1_query(blocks, {})
    assert "MeSH" in cv
    assert "Neoplasms" in cv["MeSH"]
    assert "PsycINFO" in cv


def test_build_level1_query_enriches_from_concept_graph():
    blocks = [CombinedBlock(role="topic_or_condition", free_text=["cancer"])]
    graph = {
        "cancer": {
            "query_role": "topic_or_condition",
            "domain_terms": ["malignancy", "carcinoma"],
        }
    }
    query, _ = build_level1_query(blocks, graph)
    assert "malignancy" in query
    assert "carcinoma" in query


def test_build_level1_query_quotes_multi_word_phrases():
    blocks = [CombinedBlock(role="topic", free_text=["mental health", "MHPSS"])]
    query, _ = build_level1_query(blocks, {})
    assert '"mental health"' in query
    assert "MHPSS" in query


def test_build_level1_query_empty_blocks_returns_empty():
    query, cv = build_level1_query([], {})
    assert query == ""
    assert cv == {}


def test_build_keyword_statement_skips_wildcard_terms():
    blocks = [
        CombinedBlock(
            role="intervention",
            free_text=["improv*", "treat*", "prevent*", "programmes", "strategies", "services"],
        )
    ]

    keyword_query = build_keyword_statement(blocks)

    assert "*" not in keyword_query
    assert keyword_query == "programmes strategies services"


# ─── build_leveln_query ──────────────────────────────────────────────────────

def test_build_leveln_query_replaces_broadened_block():
    blocks = [
        CombinedBlock(role="topic", free_text=["cancer"]),
        CombinedBlock(role="geography", free_text=["Ethiopia", "Qoloji"]),
    ]
    query, _ = build_leveln_query(blocks, {}, "geography", ["conflict-affected LMICs", "fragile states"])
    assert "Ethiopia" not in query
    assert "conflict-affected LMICs" in query
    assert "cancer" in query


def test_build_leveln_query_removes_block_when_no_replacement_terms():
    blocks = [
        CombinedBlock(role="topic", free_text=["cancer"]),
        CombinedBlock(role="geography", free_text=["Ethiopia"]),
    ]
    query, _ = build_leveln_query(blocks, {}, "geography", [])
    assert "Ethiopia" not in query
    assert "cancer" in query


def test_build_leveln_query_excludes_cv_for_broadened_block():
    blocks = [
        CombinedBlock(role="topic", free_text=["cancer"], controlled_vocabulary={"MeSH": ["Neoplasms"]}),
        CombinedBlock(role="geography", free_text=["London"], controlled_vocabulary={"MeSH": ["London"]}),
    ]
    _, cv = build_leveln_query(blocks, {}, "geography", ["United Kingdom"])
    assert "Neoplasms" in cv.get("MeSH", [])
    assert "London" not in cv.get("MeSH", [])


def test_build_leveln_query_preserves_other_blocks_verbatim():
    blocks = [
        CombinedBlock(role="topic", free_text=["diabetes", "DM"]),
        CombinedBlock(role="population", free_text=["adults", "patients"]),
        CombinedBlock(role="geography", free_text=["Ethiopia"]),
    ]
    query, _ = build_leveln_query(blocks, {}, "geography", ["sub-Saharan Africa"])
    assert "diabetes" in query
    assert "adults" in query
    assert "sub-Saharan Africa" in query


# ─── generate_search_expansion_levels pipeline ───────────────────────────────

@pytest.mark.asyncio
async def test_pipeline_returns_level1_only_when_no_expandable_blocks():
    provider = StubProvider([])  # no LLM call expected
    manager = QueryRefinementManager(provider)

    expansion_input = SearchExpansionInput(
        clarified_query="Studies of cancer treatment.",
        anchor_blocks=[CombinedBlock(role="topic_or_condition", free_text=["cancer", "tumour"])],
        concept_graph={},
    )
    result, metadata = await manager.generate_search_expansion_levels(search_input=expansion_input)

    assert len(provider.calls) == 0
    assert len(result.levels) == 2  # Level 0 (anchor) + Level 1
    assert result.levels[0].level == 0
    assert result.levels[1].level == 1
    assert metadata["status"] == "completed_no_geography"


@pytest.mark.asyncio
async def test_pipeline_returns_three_levels_with_geography():
    provider = StubProvider([_geo_llm_response_json()])
    manager = QueryRefinementManager(provider)

    result, metadata = await manager.generate_search_expansion_levels(search_input=_geo_input())

    assert len(provider.calls) == 1
    assert metadata["used_llm"] is True
    assert metadata["status"] == "completed"
    assert len(result.levels) == 4  # Level 0 (anchor) + Levels 1, 2, 3
    assert result.levels[0].level == 0
    assert result.levels[1].level == 1
    assert result.levels[2].level == 2
    assert result.levels[3].level == 3
    assert result.levels[3].cochrane_compliant is True


@pytest.mark.asyncio
async def test_pipeline_level1_is_built_deterministically():
    """Level 1 is built from blocks alone; it precedes the LLM call."""
    provider = StubProvider([_geo_llm_response_json()])
    manager = QueryRefinementManager(provider)

    result, _ = await manager.generate_search_expansion_levels(search_input=_geo_input())

    level1 = result.levels[1]  # Level 0 is anchor; Level 1 is at index 1
    assert level1.level == 1
    assert "mental health" in level1.search_query
    assert "Qoloji" in level1.search_query
    assert level1.broadened_aspect == ""
    assert level1.semantic_statement == ANCHOR


@pytest.mark.asyncio
async def test_pipeline_setting_broadening_produces_two_levels():
    provider = StubProvider([_setting_llm_response_json()])
    manager = QueryRefinementManager(provider)

    result, metadata = await manager.generate_search_expansion_levels(search_input=_setting_input())

    assert metadata["status"] == "completed"
    assert len(result.levels) == 3  # Level 0 (anchor) + Levels 1, 2
    assert result.levels[2].level == 2
    # No geo restriction → all levels are Cochrane-compliant
    assert result.levels[2].cochrane_compliant is True
    assert result.levels[2].semantic_statement == result.levels[2].clarified_query


@pytest.mark.asyncio
async def test_pipeline_fails_gracefully_when_no_anchor_blocks():
    provider = StubProvider([])
    manager = QueryRefinementManager(provider)

    expansion_input = SearchExpansionInput(
        clarified_query="Some query.",
        anchor_blocks=[],
        concept_graph={},
    )
    result, metadata = await manager.generate_search_expansion_levels(search_input=expansion_input)

    assert len(result.levels) == 0
    assert metadata["status"] == "failed"


@pytest.mark.asyncio
async def test_pipeline_returns_level1_when_llm_fails():
    """When the LLM returns unparseable text, Level 1 is still returned (soft-fail)."""
    provider = StubProvider(["not json at all"])
    manager = QueryRefinementManager(provider)

    result, metadata = await manager.generate_search_expansion_levels(search_input=_geo_input())

    assert len(result.levels) == 2  # Level 0 (anchor) + Level 1 (soft-fail returns both)
    assert result.levels[1].level == 1


def test_expansion_level_serializes_rag_friendly_field_names():
    level = ExpansionLevel(
        level=1,
        label="Full lexical ring",
        clarified_query="query text",
        semantic_statement="semantic text",
        keyword_statement="keyword text",
        search_query="boolean text",
        rationale="why",
    )

    payload = level.model_dump(by_alias=True)

    assert payload["query"] == "query text"
    assert payload["semantic_query"] == "semantic text"
    assert payload["keyword_query"] == "keyword text"
    assert payload["boolean_query"] == "boolean text"


@pytest.mark.asyncio
async def test_pipeline_records_total_tokens():
    provider = StubProvider([_geo_llm_response_json()])
    manager = QueryRefinementManager(provider)

    _, metadata = await manager.generate_search_expansion_levels(search_input=_geo_input())

    assert metadata.get("total_tokens", 0) == 15


@pytest.mark.asyncio
async def test_pipeline_geography_broadening_strategy_propagated():
    provider = StubProvider([_geo_llm_response_json()])
    manager = QueryRefinementManager(provider)

    result, _ = await manager.generate_search_expansion_levels(search_input=_geo_input())

    assert result.geography_broadening_strategy == "context_proxy"


@pytest.mark.asyncio
async def test_pipeline_recommended_starting_level_propagated():
    provider = StubProvider([_geo_llm_response_json()])
    manager = QueryRefinementManager(provider)

    result, _ = await manager.generate_search_expansion_levels(search_input=_geo_input())

    assert result.recommended_starting_level == 2


# ─── API helper ──────────────────────────────────────────────────────────────

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
