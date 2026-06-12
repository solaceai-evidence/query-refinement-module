"""Prompt templates for the fixed-core search expansion stage."""

SEARCH_ASPECT_ASSESSMENT_TEMPLATE = """
You analyze a retrieval anchor query and detect which of a FIXED set of search aspects are present in it.

The fixed aspect set (the only valid aspect ids):
- topic_or_condition: the core subject, condition, or problem of the query
- population_or_entity: the specific population, group, or entity studied
- intervention_or_exposure_or_phenomenon: the intervention, exposure, or phenomenon of interest
- setting_or_context: the setting or context (e.g. hospitals, schools, workplaces)
- geography: the geographic scope (e.g. a city, country, region)
- time_scope: the temporal scope (e.g. a year range, a period)

Return exactly one JSON object matching this schema:

{
  "assessments": [
    {
      "aspect": "geography",
      "detected": true,
      "detected_value": "the exact phrase or constraint found in the anchor query",
      "broadening_candidates": ["a strictly broader value", "another strictly broader value"],
      "reasoning": "why this aspect was detected and why each candidate is a true superset"
    }
  ]
}

Rules:
- Include one assessment object per aspect in the fixed set, in any order. Use detected=false with empty detected_value when the aspect is absent from the anchor query.
- detected_value must quote or closely paraphrase what is actually in the anchor query. Never invent constraints that are not there.
- broadening_candidates must be strictly broader supersets of the detected value (e.g. "London" -> "urban UK settings" -> "United Kingdom"). Order them from least to most broad. Provide at most three.
- Do not propose candidates that change the meaning or intent of the query.
- Never broaden comparators, outcomes, or methodological constraints; they are not part of the fixed aspect set.
- Use the optional advisory dimension values and synonyms only to resolve ambiguity about what the anchor query means; the anchor query itself is the source of truth.
""".strip()


SEARCH_EXPANSION_TEMPLATE = """
You generate optional retrieval broadening levels from an existing search anchor, following a fixed aspect policy.

Return exactly one JSON object matching this schema:

{
  "levels": [
    {
      "level": 1,
      "label": "short label",
      "strategy": "lexical",
      "search_query": "search query variant",
      "relaxed_aspects": {"aspect_id": "search-only broadened value"},
      "rationale": "what changed and why it broadens recall"
    }
  ]
}

Valid strategy values: "lexical", "conceptual_single_aspect", "conceptual_multi_aspect", "indexing_variant".

Strategy ladder (apply in this order; skip steps that add no value):
1. Level 1 — strategy "lexical": expand within detected aspects using the provided synonyms and near-variants only. Do not broaden any aspect conceptually. relaxed_aspects stays empty for purely lexical levels.
2. Level 2 — strategy "conceptual_single_aspect": broaden exactly one SAFE aspect using one of its allowed broadening candidates.
3. Level 3 — strategy "conceptual_single_aspect" or "conceptual_multi_aspect": a broader single-aspect step, or at most two aspects when one alone is insufficient. At most one of the two may be CONDITIONAL.
4. Level 4 — strategy "indexing_variant" (optional): a database-friendly or broader indexing-language variant, only if the provided synonyms or context support it.

Rules:
- Generate Levels 1 through N only. Never generate Level 0. The supplied Level 0 anchor is fixed; do not restate, rewrite, or replace it.
- Broaden only for search recall; never change the intent, scope, or core meaning of the anchor query.
- relaxed_aspects keys must come from the allowed aspects listed in the input. Never use an aspect marked AVOID or an aspect that was not detected.
- Conceptual broadened values must come from (or be consistent with) the allowed broadening candidates given per aspect.
- Relax at most two aspects per level, and avoid Cartesian combinations.
- Prefer lexical expansion before any conceptual broadening.
- Treat filters as retrieval constraints to respect during broadening; do not contradict them or force them into the query text unless they naturally belong there.
- Use provided synonyms selectively, only when they improve recall without changing scope.
- Return zero additional levels if the anchor query is already broad or no useful safe broadening exists.
- Return at most four additional levels.
- Keep search_query non-empty and directly usable by a retrieval system.
- Explain in each rationale what changed and why it broadens recall without scope drift.
""".strip()


__all__ = ["SEARCH_ASPECT_ASSESSMENT_TEMPLATE", "SEARCH_EXPANSION_TEMPLATE"]
