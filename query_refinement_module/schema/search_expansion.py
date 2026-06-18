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
    return {
        "filters": _to_jsonable(getattr(search_context, "filters", {}) or {}),
        "synonyms": _to_jsonable(getattr(search_context, "synonyms", {}) or {}),
    }


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
            f"{search_input.anchor_query}",
            "## Supporting Search Context\n\n"
            f"{json.dumps(_support_context(search_input), ensure_ascii=False, indent=2)}",
        ]
        if search_input.advisory_dimensions:
            sections.append(
                "## Advisory Dimension Values (non-authoritative hints only)\n\n"
                f"{json.dumps(_to_jsonable(search_input.advisory_dimensions), ensure_ascii=False, indent=2)}"
            )
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
            f"{search_input.anchor_query}\n\n"
            "## Allowed Aspects For Search-Only Broadening\n\n"
            f"{json.dumps(allowed, ensure_ascii=False, indent=2)}\n\n"
            "## Supporting Search Context\n\n"
            f"{json.dumps(_support_context(search_input), ensure_ascii=False, indent=2)}\n\n"
            "Reminder: Level 0 is already established and must not be regenerated. "
            "Use only the allowed aspects above in relaxed_aspects. "
            "Return only Levels 1-N, or an empty levels list."
        )


__all__ = ["SearchExpansionPromptBuilder"]
