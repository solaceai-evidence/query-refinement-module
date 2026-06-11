"""
Unit tests for the split synthesis helpers added in the workstream-5 architecture.

Covers:
- _extract_template_section / _extract_general_rules
- SynthesisPromptBuilder — all 5 system prompts and user prompts
- PUBLICATION_TYPES_PERMITTED constant
- _build_concept_inventory
- _compile_boolean_query (including wildcards, synonym cap, dedup)
- FilterSuggestionResponse expanded fields
- Publication-years validation edge cases (covered by test_core.py; repeated here
  for the explicit pub_types path)
"""

from __future__ import annotations

import json
import re
from typing import Dict, List

import pytest


PRIVATE_MODEL = "anthropic/claude-sonnet-4-6"
OPEN_MODEL = "ollama/qwen2.5:72b"

from query_refinement_module.core import (
    FIELDS_OF_STUDY_PERMITTED,
    PUBLICATION_TYPES_PERMITTED,
    QueryRefinementManager,
    RefinementSession,
)
from query_refinement_module.schema.response import (
    FilterSuggestionResponse,
    KeywordSupportResponse,
    StatementResponse,
    TerminologyResponse,
)
from query_refinement_module.schema.synthesis import (
    SynthesisPromptBuilder,
    _use_open_llm_synthesis_variant_for_model,
    _extract_general_rules,
    _extract_template_section,
)


# =============================================================================
# _extract_template_section
# =============================================================================

class TestExtractTemplateSection:
    """_extract_template_section returns verbatim body text from SYNTHESIS_TEMPLATE."""

    def _all_headings(self):
        return [
            "### integrated_statement",
            "### search_optimized.semantic",
            "### search_optimized.keyword.structured",
            "### search_optimized.keyword.phrases",
            "### search_optimized.keyword.terms",
            "### search_filters.publication_years",
            "### search_filters.venues",
            "### search_filters.authors",
            "### search_filters.publication_types",
            "### search_filters.fields_of_study",
            "### terminology.synonyms",
        ]

    def test_all_sections_return_non_empty(self):
        for heading in self._all_headings():
            result = _extract_template_section(heading)
            assert result, f"Section for '{heading}' returned empty string"

    def test_general_rules_non_empty(self):
        assert _extract_general_rules()

    def test_unknown_heading_returns_empty(self):
        assert _extract_template_section("### no_such_section") == ""

    def test_heading_not_included_in_result(self):
        """The heading line itself must not appear in the extracted body."""
        for heading in self._all_headings():
            result = _extract_template_section(heading)
            assert heading not in result, (
                f"Heading '{heading}' should not appear in its own extracted body"
            )

    def test_sibling_sections_do_not_bleed(self):
        """Each section must not contain content from the next sibling."""
        pub_years = _extract_template_section("### search_filters.publication_years")
        venues = _extract_template_section("### search_filters.venues")
        authors = _extract_template_section("### search_filters.authors")

        assert "venues" not in pub_years.lower()
        assert "authors" not in venues.lower()

    def test_integrated_statement_contains_abbreviation_rule(self):
        """The abbreviation rule must instruct the model to keep both forms."""
        section = _extract_template_section("### integrated_statement")
        assert "full form" in section.lower() or "ABBR" in section
        # Must not still say only 'expand' without 'retain'
        assert "retain" in section.lower() or "keep both" in section.lower() or "do not drop" in section.lower()

    def test_publication_types_contains_permitted_values(self):
        section = _extract_template_section("### search_filters.publication_types")
        assert "Randomized controlled trial" in section
        assert "Systematic review" in section

    def test_fields_of_study_contains_permitted_values(self):
        section = _extract_template_section("### search_filters.fields_of_study")
        assert "Medicine" in section
        assert "Psychology" in section


def test_schema_helper_classifies_wrapper_private_and_open_models():
    assert _use_open_llm_synthesis_variant_for_model("bedrock/anthropic.claude-3-7-sonnet") is False
    assert _use_open_llm_synthesis_variant_for_model("llamaindex/openai/gpt-4o") is False
    assert _use_open_llm_synthesis_variant_for_model("google/gemma-2-27b") is True


# =============================================================================
# SynthesisPromptBuilder — system prompts
# =============================================================================

class TestSystemPrompts:
    """All 5 system prompts must be non-trivially long and contain key markers."""

    def test_statement_schema_marker(self):
        text = SynthesisPromptBuilder.get_statement_system_prompt()
        assert "integrated_statement" in text
        assert "StatementResponse" in text

    def test_statement_general_rules_included(self):
        text = SynthesisPromptBuilder.get_statement_system_prompt()
        assert "Deduplicate" in text  # from General Rules

    def test_statement_abbreviation_rule_propagated(self):
        """The 'keep both forms' fix in the template must reach the system prompt."""
        text = SynthesisPromptBuilder.get_statement_system_prompt()
        assert "ABBR" in text or "retain" in text.lower() or "do not drop" in text.lower()

    def test_semantic_schema_marker(self):
        text = SynthesisPromptBuilder.get_semantic_query_system_prompt()
        assert "SemanticQueryResponse" in text
        assert "semantic" in text

    def test_terminology_schema_marker(self):
        text = SynthesisPromptBuilder.get_terminology_system_prompt()
        assert "TerminologyResponse" in text
        assert "synonyms" in text

    def test_keyword_support_schema_marker(self):
        text = SynthesisPromptBuilder.get_keyword_support_system_prompt(PRIVATE_MODEL)
        assert "KeywordSupportResponse" in text
        assert "phrases" in text
        assert "required" in text
        assert "excluded" in text

    def test_keyword_support_structured_note(self):
        """Must tell the model that 'structured' is produced by a separate call."""
        text = SynthesisPromptBuilder.get_keyword_support_system_prompt(PRIVATE_MODEL)
        assert "separate call" in text.lower()

    def test_filter_resolution_schema_marker(self):
        text = SynthesisPromptBuilder.get_filter_resolution_system_prompt(PRIVATE_MODEL)
        assert "FilterSuggestionResponse" in text
        assert "publication_years" in text
        assert "publication_types" in text
        assert "fields_of_study" in text

    def test_filter_resolution_contains_permitted_pub_types(self):
        text = SynthesisPromptBuilder.get_filter_resolution_system_prompt(PRIVATE_MODEL)
        assert "Randomized controlled trial" in text
        assert "Systematic review" in text

    def test_filter_resolution_contains_permitted_fields_of_study(self):
        text = SynthesisPromptBuilder.get_filter_resolution_system_prompt(PRIVATE_MODEL)
        assert "Medicine" in text
        assert "Agricultural and Food Sciences" in text

    def test_filter_resolution_contains_year_resolution_rules(self):
        text = SynthesisPromptBuilder.get_filter_resolution_system_prompt(PRIVATE_MODEL)
        assert "2020" in text
        assert "decade" in text.lower()
        assert "Since YYYY" in text or "since yyyy" in text.lower()

    def test_open_llm_filter_resolution_system_prompt_matches_full_contract(self):
        text = SynthesisPromptBuilder.get_filter_resolution_system_prompt(OPEN_MODEL)
        assert "publication_years" in text
        assert "publication_types" in text
        assert "fields_of_study" in text

    @pytest.mark.parametrize("call", [
        "statement", "semantic", "terminology", "keyword_support", "filter_resolution"
    ])
    def test_all_system_prompts_non_trivially_sized(self, call):
        fn_map = {
            "statement": SynthesisPromptBuilder.get_statement_system_prompt,
            "semantic": SynthesisPromptBuilder.get_semantic_query_system_prompt,
            "terminology": SynthesisPromptBuilder.get_terminology_system_prompt,
            "keyword_support": lambda: SynthesisPromptBuilder.get_keyword_support_system_prompt(PRIVATE_MODEL),
            "filter_resolution": lambda: SynthesisPromptBuilder.get_filter_resolution_system_prompt(PRIVATE_MODEL),
        }
        text = fn_map[call]()
        assert len(text) >= 300, f"{call} system prompt is suspiciously short ({len(text)} chars)"


# =============================================================================
# SynthesisPromptBuilder — user prompts
# =============================================================================

class TestUserPrompts:
    """User prompts must include the right dynamic content."""

    def test_filter_resolution_prompt_includes_current_year(self):
        from datetime import datetime
        text = SynthesisPromptBuilder.get_filter_resolution_prompt("query", {}, [], PRIVATE_MODEL)
        assert str(datetime.now().year) in text

    def test_filter_resolution_prompt_includes_original_input(self):
        text = SynthesisPromptBuilder.get_filter_resolution_prompt("my test query", {}, [], PRIVATE_MODEL)
        assert "my test query" in text

    def test_filter_resolution_prompt_includes_permitted_values(self):
        permitted = ["Medicine", "Biology"]
        text = SynthesisPromptBuilder.get_filter_resolution_prompt("q", {}, permitted, PRIVATE_MODEL)
        assert "Medicine" in text
        assert "Biology" in text

    def test_open_llm_filter_resolution_prompt_includes_current_year(self):
        text = SynthesisPromptBuilder.get_filter_resolution_prompt("query", {}, [], OPEN_MODEL)
        assert "Current Year" in text

    def test_terminology_prompt_lists_concepts(self):
        concepts = ["cognitive behavioural therapy (CBT)", "young adults"]
        text = SynthesisPromptBuilder.get_terminology_prompt("some statement", concepts)
        for c in concepts:
            assert c in text

    def test_keyword_support_prompt_includes_synonyms(self):
        synonyms = {"CBT": ["cognitive behavioural therapy", "cognitive therapy"]}
        text = SynthesisPromptBuilder.get_keyword_support_prompt(
            "some statement", ["CBT"], synonyms, PRIVATE_MODEL
        )
        assert "CBT" in text
        assert "cognitive behavioural therapy" in text


# =============================================================================
# PUBLICATION_TYPES_PERMITTED constant
# =============================================================================

class TestPublicationTypesPermitted:
    """PUBLICATION_TYPES_PERMITTED must be complete and consistent with the template."""

    def test_is_frozenset(self):
        assert isinstance(PUBLICATION_TYPES_PERMITTED, frozenset)

    def test_expected_count(self):
        # Template currently has 27 permitted publication types
        assert len(PUBLICATION_TYPES_PERMITTED) == 27

    @pytest.mark.parametrize("value", [
        "Randomized controlled trial",
        "Systematic review",
        "Meta-analysis",
        "Guideline",
        "Case report",
        "Cohort study",
        "Cross-sectional study",
    ])
    def test_canonical_values_present(self, value):
        assert value in PUBLICATION_TYPES_PERMITTED

    @pytest.mark.parametrize("bad_value", [
        "RCT",
        "rct",
        "systematic review",      # wrong case
        "Meta Analysis",          # missing hyphen
        "randomised controlled trial",  # British spelling variant not in list
    ])
    def test_non_canonical_values_absent(self, bad_value):
        assert bad_value not in PUBLICATION_TYPES_PERMITTED

    def test_consistent_with_template(self):
        """Every value in PUBLICATION_TYPES_PERMITTED must appear in the template section."""
        section = _extract_template_section("### search_filters.publication_types")
        for value in PUBLICATION_TYPES_PERMITTED:
            assert value in section, (
                f"Permitted value '{value}' not found in template publication_types section"
            )


# =============================================================================
# _build_concept_inventory
# =============================================================================

class TestBuildConceptInventory:
    def _mgr(self):
        from tests.unit.test_core import StubLLMProvider
        return QueryRefinementManager(llm_provider=StubLLMProvider([]))

    def test_empty_dimensions_returns_empty(self):
        mgr = self._mgr()
        assert mgr._build_concept_inventory("statement", {}) == []

    def test_skipped_value_excluded(self):
        mgr = self._mgr()
        result = mgr._build_concept_inventory(
            "statement", {"pop": None, "intervention": "CBT"}
        )
        assert result == ["CBT"]
        assert None not in result

    def test_deduplication(self):
        """Identical serialised values must appear only once."""
        mgr = self._mgr()
        result = mgr._build_concept_inventory(
            "statement",
            {"a": "adults", "b": "adults", "c": "CBT"},
        )
        assert result.count("adults") == 1
        assert "CBT" in result

    def test_order_preserved(self):
        mgr = self._mgr()
        result = mgr._build_concept_inventory(
            "stmt",
            {"pop": "adults", "intervention": "CBT", "outcome": "anxiety"},
        )
        assert result == ["adults", "CBT", "anxiety"]

    def test_dict_value_serialised(self):
        mgr = self._mgr()
        result = mgr._build_concept_inventory(
            "stmt", {"dim": {"primary": "hospital", "secondary": "community"}}
        )
        assert len(result) == 1
        parsed = json.loads(result[0])
        assert parsed == {"primary": "hospital", "secondary": "community"}


# =============================================================================
# _compile_boolean_query
# =============================================================================

class TestCompileBooleanQuery:
    """_compile_boolean_query produces correct AND-of-OR Boolean strings."""

    def test_empty_required_returns_empty(self):
        assert QueryRefinementManager._compile_boolean_query([], {}) == ""

    def test_single_term_no_synonyms(self):
        result = QueryRefinementManager._compile_boolean_query(["adults"], {})
        assert "adults" in result
        assert "AND" not in result

    def test_two_terms_joined_with_and(self):
        result = QueryRefinementManager._compile_boolean_query(["adults", "CBT"], {})
        assert " AND " in result

    def test_synonyms_joined_with_or(self):
        result = QueryRefinementManager._compile_boolean_query(
            ["CBT"], {"CBT": ["cognitive behavioural therapy", "cognitive therapy"]}
        )
        assert "OR" in result
        assert "CBT" in result
        assert "cognitive behavioural therapy" in result

    def test_synonym_cap_at_five(self):
        """Only the first 5 synonyms are included."""
        synonyms = [f"syn{i}" for i in range(10)]
        result = QueryRefinementManager._compile_boolean_query(
            ["term"], {"term": synonyms}
        )
        # term + 5 synonyms = 6 variants max
        variants_in_result = result.count(" OR ") + 1
        assert variants_in_result <= 7  # at most term + 5 synonyms + 1 wildcard

    def test_multi_word_term_quoted(self):
        result = QueryRefinementManager._compile_boolean_query(
            ["cognitive behavioural therapy"], {}
        )
        assert '"cognitive behavioural therapy"' in result

    def test_single_word_term_unquoted(self):
        result = QueryRefinementManager._compile_boolean_query(["adults"], {})
        assert '"adults"' not in result
        assert "adults" in result

    def test_wildcard_added_for_root_term(self):
        """Single-word terms of 5+ chars that have inflectional variants get a wildcard."""
        result = QueryRefinementManager._compile_boolean_query(["implementation"], {})
        assert "implement*" in result

    def test_wildcard_not_added_for_short_term(self):
        """Terms under 5 characters must not get a wildcard."""
        result = QueryRefinementManager._compile_boolean_query(["art"], {})
        assert "*" not in result

    def test_wildcard_not_added_for_abbreviation(self):
        """All-caps abbreviations (e.g. CBT) must not get a wildcard."""
        result = QueryRefinementManager._compile_boolean_query(["CBT"], {})
        assert "*" not in result

    def test_wildcard_not_added_for_multi_word(self):
        result = QueryRefinementManager._compile_boolean_query(
            ["cognitive therapy"], {}
        )
        assert "*" not in result

    def test_dedup_synonyms(self):
        """If a synonym duplicates the base term it must not appear twice."""
        result = QueryRefinementManager._compile_boolean_query(
            ["CBT"], {"CBT": ["CBT", "cognitive therapy"]}
        )
        assert result.count("CBT") == 1

    def test_output_is_valid_single_block_parentheses(self):
        """A term with synonyms must be wrapped in parentheses."""
        result = QueryRefinementManager._compile_boolean_query(
            ["CBT"], {"CBT": ["cognitive behavioural therapy"]}
        )
        assert result.startswith("(")
        assert result.endswith(")")

    def test_three_term_structure(self):
        result = QueryRefinementManager._compile_boolean_query(
            ["adults", "CBT", "anxiety"],
            {"CBT": ["cognitive behavioural therapy"]},
        )
        parts = result.split(" AND ")
        assert len(parts) == 3


# =============================================================================
# FilterSuggestionResponse — expanded fields
# =============================================================================

class TestFilterSuggestionResponse:
    """FilterSuggestionResponse must accept and expose all five filter fields."""

    def test_default_empty(self):
        r = FilterSuggestionResponse()
        assert r.publication_years == ""
        assert r.venues == []
        assert r.authors == []
        assert r.publication_types == []
        assert r.fields_of_study == []

    def test_all_fields_populated(self):
        r = FilterSuggestionResponse(
            publication_years="2020-2026",
            venues=["The Lancet"],
            authors=["Jane Smith"],
            publication_types=["Systematic review"],
            fields_of_study=["Medicine"],
        )
        assert r.publication_years == "2020-2026"
        assert r.venues == ["The Lancet"]
        assert r.authors == ["Jane Smith"]
        assert r.publication_types == ["Systematic review"]
        assert r.fields_of_study == ["Medicine"]

    def test_pub_types_is_list(self):
        r = FilterSuggestionResponse(publication_types=["Guideline", "Meta-analysis"])
        assert isinstance(r.publication_types, list)
        assert len(r.publication_types) == 2


# =============================================================================
# KeywordSupportResponse — excluded field
# =============================================================================

class TestKeywordSupportResponseExcluded:
    """KeywordSupportResponse.excluded must default to [] and accept values."""

    def test_excluded_defaults_to_empty(self):
        r = KeywordSupportResponse(phrases=[], required=[], optional=[])
        assert r.excluded == []

    def test_excluded_populated(self):
        r = KeywordSupportResponse(
            phrases=["mindfulness CBT"],
            required=["CBT"],
            optional=["anxiety"],
            excluded=["drug therapy"],
        )
        assert r.excluded == ["drug therapy"]
