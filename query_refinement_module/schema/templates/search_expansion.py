"""Prompt template for post-synthesis search expansion."""

SEARCH_EXPANSION_TEMPLATE = """
You generate optional retrieval broadening levels after query synthesis.

Return exactly one JSON object matching this schema:

{
  "levels": [
    {
      "level": 1,
      "label": "short label",
      "search_query": "search query variant",
      "relaxed_dimensions": {"dimension_id": "search-only relaxed value"},
      "rationale": "what changed and why it broadens recall"
    }
  ]
}

Rules:
- Generate Levels 1 through N only. Never generate Level 0.
- Treat the supplied Level 0 anchor as fixed. Do not restate or edit it.
- Use the synthesis result as source context, not as permission to change the review scope.
- Broaden only for search recall; do not redefine the canonical refined question.
- Relax only one or two dimensions per level.
- Prefer meaningful dimension-level broadening in this order: geography hierarchy, setting class, adjacent population grouping, broader condition family, broader time phase.
- Avoid Cartesian combinations of relaxed dimensions.
- Return zero additional levels if the question is already broad and has no narrow dimensions to relax.
- Return at most four additional levels.
- Explain what changed and why in each rationale.
- Use only accepted dimension IDs as keys in relaxed_dimensions.
- Keep search_query non-empty and directly usable by a retrieval system.
""".strip()


__all__ = ["SEARCH_EXPANSION_TEMPLATE"]
