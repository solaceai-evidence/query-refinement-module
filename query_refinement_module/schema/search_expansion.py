"""Prompt builder for standalone search expansion."""

from __future__ import annotations

import json
from typing import Any, Dict

from .response import SearchExpansionInput


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
        search_input: SearchExpansionInput,
    ) -> str:
        search_context = search_input.search_context or {}
        support_context = {
            "filters": _to_jsonable(getattr(search_context, "filters", {})),
            "synonyms": _to_jsonable(getattr(search_context, "synonyms", {})),
        }
        return (
            "## Level 0 Anchor (already established; do not regenerate)\n\n"
            f"{search_input.anchor_query}\n\n"
            "## Eligible Dimensions For Search-Only Relaxation\n\n"
            f"{json.dumps(_to_jsonable(search_input.eligible_dimensions), ensure_ascii=False, indent=2)}\n\n"
            "## Supporting Search Context\n\n"
            f"{json.dumps(support_context, ensure_ascii=False, indent=2)}\n\n"
            "Reminder: Level 0 is already established and must not be regenerated. "
            "Return only Levels 1-N, or an empty levels list."
        )


__all__ = ["SearchExpansionPromptBuilder"]
