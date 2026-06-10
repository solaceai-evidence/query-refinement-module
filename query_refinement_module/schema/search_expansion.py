"""Prompt builder for post-synthesis search expansion."""

from __future__ import annotations

import json
from typing import Any, Dict

from .response import QueryRefinementResponse


def _to_jsonable(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump()
    if isinstance(value, dict):
        return {k: _to_jsonable(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_to_jsonable(v) for v in value]
    return value


class SearchExpansionPromptBuilder:
    """Build system and user prompts for search expansion."""

    @staticmethod
    def get_system_prompt() -> str:
        from .templates.search_expansion import SEARCH_EXPANSION_TEMPLATE

        return SEARCH_EXPANSION_TEMPLATE

    @staticmethod
    def get_user_prompt(
        synthesis_response: QueryRefinementResponse,
        accepted_dimensions: Dict[str, Any],
        original_query: str,
    ) -> str:
        support_context = {
            "search_optimized_semantic": synthesis_response.search_optimized.semantic,
            "search_filters": _to_jsonable(synthesis_response.search_filters),
            "terminology_synonyms": synthesis_response.terminology.synonyms,
        }
        return (
            f"## Original Query\n\n{original_query}\n\n"
            "## Level 0 Anchor (already established; do not regenerate)\n\n"
            f"{synthesis_response.integrated_statement}\n\n"
            "## Dimensions Specifications\n\n"
            f"{json.dumps(_to_jsonable(synthesis_response.dimensions_specifications), ensure_ascii=False, indent=2)}\n\n"
            "## Accepted Dimensions Eligible for Search-Only Relaxation\n\n"
            f"{json.dumps(_to_jsonable(accepted_dimensions), ensure_ascii=False, indent=2)}\n\n"
            "## Supporting Search Context\n\n"
            f"{json.dumps(support_context, ensure_ascii=False, indent=2)}\n\n"
            "Reminder: Level 0 is already established and must not be regenerated. "
            "Return only Levels 1-N, or an empty levels list."
        )


__all__ = ["SearchExpansionPromptBuilder"]
