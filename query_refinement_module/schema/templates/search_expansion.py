"""Prompt template for standalone search expansion."""

SEARCH_EXPANSION_TEMPLATE = """
You generate optional retrieval broadening levels from an existing search anchor.

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
- Treat the supplied Level 0 anchor as fixed. Do not restate, rewrite, or replace it.
- Use the provided anchor query, eligible dimensions, filters, and synonyms as source context.
- Broaden only for search recall; do not change the intent, scope, or core meaning of the anchor query.
- Relax only one or two dimensions per level.
- Prefer meaningful dimension-level broadening such as moving from narrower to broader values, nearby populations, broader settings, broader places, broader condition families, or broader time scopes when those dimensions exist in the input.
- Avoid Cartesian combinations of relaxed dimensions.
- Return zero additional levels if the anchor query is already broad or if there are no useful eligible dimensions to relax.
- Return at most four additional levels.
- Explain what changed and why in each rationale.
- Use only eligible dimension IDs as keys in relaxed_dimensions.
- Keep search_query non-empty and directly usable by a retrieval system.
- When synonyms are provided in search_context, use them selectively when they improve recall without changing scope.
- Treat filters as retrieval constraints to respect during broadening; do not contradict them or force them into the query text unless they naturally belong there.
""".strip()


__all__ = ["SEARCH_EXPANSION_TEMPLATE"]
