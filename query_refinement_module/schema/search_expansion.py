"""Prompt builder for the fixed-core search expansion stage."""

from __future__ import annotations

import json
from typing import Any, List

from .response import (
    AspectSafety,
    SearchAspectAssessment,
    SearchExpansionInput,
)


def _to_jsonable(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump()
    if isinstance(value, dict):
        return {k: _to_jsonable(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_to_jsonable(v) for v in value]
    return value


def _support_context(search_input: SearchExpansionInput) -> dict:
    search_context = search_input.search_context
    filters = _to_jsonable(getattr(search_context, "filters", {}) or {})

    concept_lexical_rings: dict = {}
    concept_graph = getattr(search_context, "concept_graph", None)
    if concept_graph:
        for concept, entry in concept_graph.items():
            if not isinstance(entry, dict):
                continue
            ring: dict = {}
            if entry.get("query_role"):
                ring["query_role"] = entry["query_role"]
            for field in (
                "true_synonyms",
                "abbreviations",
                "spelling_variants",
                "lexical_variants",
                "colloquial",
                "domain_terms",
            ):
                vals = list(entry.get(field) or [])
                if vals:
                    ring[field] = vals
            if ring:
                concept_lexical_rings[concept] = ring

    result: dict = {"filters": filters}
    if concept_lexical_rings:
        result["concept_lexical_rings"] = concept_lexical_rings
    return result


class SearchExpansionPromptBuilder:
    """Build system and user prompts for aspect assessment and expansion."""

    @staticmethod
    def get_assessment_system_prompt() -> str:
        from .templates.search_expansion import SEARCH_ASPECT_ASSESSMENT_TEMPLATE

        return SEARCH_ASPECT_ASSESSMENT_TEMPLATE

    @staticmethod
    def get_assessment_user_prompt(search_input: SearchExpansionInput) -> str:
        sections = [
            "## Anchor Query (source of truth)\n\n"
            f"{search_input.statement}",
            "## Supporting Search Context\n\n"
            f"{json.dumps(_support_context(search_input), ensure_ascii=False, indent=2)}",
        ]
        sections.append(
            "Return one assessment per fixed aspect. Detect only what is "
            "actually present in the anchor query."
        )
        return "\n\n".join(sections)

    @staticmethod
    def get_system_prompt() -> str:
        from .templates.search_expansion import SEARCH_EXPANSION_TEMPLATE

        return SEARCH_EXPANSION_TEMPLATE

    @staticmethod
    def get_user_prompt(
        search_input: SearchExpansionInput,
        assessments: List[SearchAspectAssessment],
    ) -> str:
        allowed = [
            {
                "aspect": a.aspect.value,
                "detected_value": a.detected_value,
                "safety": a.safety.value if a.safety else AspectSafety.AVOID.value,
                "broadening_candidates": a.broadening_candidates,
            }
            for a in assessments
            if a.detected and a.safety in (AspectSafety.SAFE, AspectSafety.CONDITIONAL)
        ]
        return (
            "## Level 0 Anchor (already established; do not regenerate)\n\n"
            f"{search_input.statement}\n\n"
            "## Allowed Aspects For Search-Only Broadening\n\n"
            f"{json.dumps(allowed, ensure_ascii=False, indent=2)}\n\n"
            "## Supporting Search Context\n\n"
            f"{json.dumps(_support_context(search_input), ensure_ascii=False, indent=2)}\n\n"
            "Reminder: Level 0 is already established and must not be regenerated. "
            "Use only the allowed aspects above in relaxed_aspects. "
            "Return only Levels 1-N, or an empty levels list."
        )


__all__ = ["SearchExpansionPromptBuilder"]
