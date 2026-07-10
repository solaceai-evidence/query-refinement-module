"""Shared helpers for interactive refinement entry points."""

from __future__ import annotations

import re
from typing import Any, Dict, Optional

from query_refinement_module.schema.response import SearchExpansionInput


def build_search_expansion_input_from_synthesis(
    synthesis: Dict[str, Any],
) -> Optional[SearchExpansionInput]:
    """Build Agent D input from synthesis output when combined blocks exist."""
    clarified_query = synthesis.get("clarified_query")
    if not clarified_query:
        return None

    search_optimized = synthesis.get("search_optimized")
    combined_blocks = None
    if search_optimized is not None:
        keyword = getattr(search_optimized, "keyword", None)
        if keyword is not None:
            combined_blocks = getattr(keyword, "combined_blocks", None)

    if not combined_blocks:
        return None

    concept_graph = synthesis.get("concept_graph") or {}
    semantic_statement = getattr(search_optimized, "semantic", "") or "" if search_optimized else ""
    keyword_statement = synthesis.get("keyword_statement") or ""

    keyword = getattr(search_optimized, "keyword", None) if search_optimized else None
    keyword_structured = getattr(keyword, "structured", "") or "" if keyword else ""
    phrases = list(getattr(keyword, "phrases", None) or []) if keyword else []
    search_filters = synthesis.get("search_filters")

    return SearchExpansionInput(
        clarified_query=clarified_query,
        anchor_blocks=combined_blocks,
        concept_graph=concept_graph,
        semantic_statement=semantic_statement,
        keyword_statement=keyword_statement,
        keyword_structured=keyword_structured,
        search_filters=search_filters,
        phrases=phrases,
    )


def resolve_numeric_examples(user_input: str, examples: Optional[list[str]]) -> tuple[str, bool]:
    """Resolve a numeric example selection like ``1`` or ``1,2`` to example text."""
    if not examples:
        return user_input, False

    numbers = re.findall(r"\d+", user_input.strip())
    if not numbers:
        return user_input, False

    cleaned = re.sub(r"\b(and|or)\b", "", user_input.strip(), flags=re.IGNORECASE)
    cleaned = re.sub(r"[\d\s,\.]+", "", cleaned)
    if cleaned:
        return user_input, False

    resolved = []
    for num_str in numbers:
        try:
            idx = int(num_str) - 1
            if 0 <= idx < len(examples):
                resolved.append(examples[idx])
            else:
                return user_input, False
        except (ValueError, IndexError):
            return user_input, False

    if not resolved:
        return user_input, False
    if len(resolved) == 1:
        return resolved[0], True
    return " | ".join(resolved), True