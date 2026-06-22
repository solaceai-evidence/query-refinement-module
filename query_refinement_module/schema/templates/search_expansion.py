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

## Example — Medicine

Anchor Query (the normalized research statement):
"Recent studies about venous thromboembolism prophylaxis in patients undergoing major orthopedic surgery (total hip replacement, knee replacement, hip fracture surgery), comparing thromboprophylaxis interventions including antithrombotic medications and mechanical interventions such as compression stockings within and across classes."

Output:

{
  "assessments": [
    {
      "aspect": "topic_or_condition",
      "detected": true,
      "detected_value": "venous thromboembolism",
      "broadening_candidates": ["thrombosis", "vascular events"],
      "reasoning": "The anchor specifies venous thromboembolism as the primary condition; removing 'venous' broadens to all thrombosis types; 'vascular events' is a further superset."
    },
    {
      "aspect": "population_or_entity",
      "detected": true,
      "detected_value": "patients undergoing major orthopedic surgery",
      "broadening_candidates": ["orthopedic surgery patients", "surgical patients"],
      "reasoning": "The anchor constrains to major orthopedic surgery; removing 'major' captures all orthopedic procedures; 'surgical patients' is the broadest meaningful superset."
    },
    {
      "aspect": "intervention_or_exposure_or_phenomenon",
      "detected": true,
      "detected_value": "thromboprophylaxis interventions",
      "broadening_candidates": ["prophylaxis", "surgical prophylaxis"],
      "reasoning": "The anchor states thromboprophylaxis as the intervention class; 'prophylaxis' broadens to all preventive measures; 'surgical prophylaxis' widens the scope without changing the surgical context."
    },
    {
      "aspect": "setting_or_context",
      "detected": false,
      "detected_value": "",
      "broadening_candidates": [],
      "reasoning": "No specific clinical setting (e.g. ICU, inpatient, outpatient) appears in the anchor."
    },
    {
      "aspect": "geography",
      "detected": false,
      "detected_value": "",
      "broadening_candidates": [],
      "reasoning": "No geographic constraint is present in the anchor."
    },
    {
      "aspect": "time_scope",
      "detected": false,
      "detected_value": "",
      "broadening_candidates": [],
      "reasoning": "No temporal constraint appears in the anchor. The word 'recent' describes the intended literature vintage but is not a searchable constraint that can be broadened."
    }
  ]
}
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
4. Level 4 — strategy "indexing_variant" (optional): when controlled_vocabulary_hints are provided in the Supporting Search Context, use those vocabulary names and terms to construct a database-specific controlled vocabulary query (e.g. MeSH headings for MEDLINE, ERIC descriptors for education databases). Name the vocabulary in the label. Skip Level 4 entirely when no controlled_vocabulary_hints are provided or all entries have confidence "low".

Rules:
- Generate Levels 1 through N only. Never generate Level 0. The supplied Level 0 anchor is fixed; do not restate, rewrite, or replace it.
- Broaden only for search recall; never change the intent, scope, or core meaning of the anchor query.
- Keep each search_query concise, readable, and directly usable as a retrieval query.
- Prefer one short natural-language retrieval string or one compact keyword query, not a long synonym dump.
- Do not concatenate every available synonym. Use only the highest-value lexical variants needed for recall.
- Avoid telegraphic keyword soup. Preserve recognizable phrase structure whenever possible.
- Unless the input already requires dense Boolean syntax, keep each level to the smallest query that expresses the intended broadening.
- relaxed_aspects keys must come from the allowed aspects listed in the input. Never use an aspect marked AVOID or an aspect that was not detected.
- Conceptual broadened values must come from (or be consistent with) the allowed broadening candidates given per aspect.
- If relaxed_aspects contains exactly two keys, use strategy "conceptual_multi_aspect".
- If strategy is "conceptual_single_aspect", relax exactly one aspect.
- Relax at most two aspects per level, and avoid Cartesian combinations.
- Prefer lexical expansion before any conceptual broadening.
- Treat filters as retrieval constraints to respect during broadening; do not contradict them or force them into the query text unless they naturally belong there.
- Use provided synonyms selectively, only when they improve recall without changing scope.
- Return zero additional levels if the anchor query is already broad or no useful safe broadening exists.
- Return at most four additional levels.
- Keep search_query non-empty and directly usable by a retrieval system.
- Explain in each rationale what changed and why it broadens recall without scope drift.

## Example — Medicine

Level 0 Anchor (given — the normalized research statement; do not regenerate):
"Recent studies about venous thromboembolism prophylaxis in patients undergoing major orthopedic surgery (total hip replacement, knee replacement, hip fracture surgery), comparing thromboprophylaxis interventions including antithrombotic medications and mechanical interventions such as compression stockings within and across classes."

Allowed Aspects For Search-Only Broadening:
[{"aspect": "topic_or_condition", "safety": "safe", "detected_value": "venous thromboembolism", "broadening_candidates": ["thrombosis", "vascular events"]},
 {"aspect": "population_or_entity", "safety": "safe", "detected_value": "patients undergoing major orthopedic surgery", "broadening_candidates": ["orthopedic surgery patients", "surgical patients"]},
 {"aspect": "intervention_or_exposure_or_phenomenon", "safety": "conditional", "detected_value": "thromboprophylaxis interventions", "broadening_candidates": ["prophylaxis", "surgical prophylaxis"]}]

Supporting Search Context (controlled_vocabulary_hints from concept_graph):
[{"vocabulary_name": "MeSH", "terms": ["Venous Thromboembolism", "Venous Thrombosis", "Pulmonary Embolism"]},
 {"vocabulary_name": "MeSH", "terms": ["Arthroplasty, Replacement, Hip", "Arthroplasty, Replacement, Knee", "Hip Fractures"]},
 {"vocabulary_name": "MeSH", "terms": ["Anticoagulants", "Compression Bandages", "Intermittent Pneumatic Compression Devices"]}]

Output:

{
  "levels": [
    {
      "level": 1,
      "label": "Lexical variants",
      "strategy": "lexical",
      "search_query": "Recent studies on VTE prophylaxis or thromboprophylaxis in patients undergoing major orthopedic or orthopaedic surgery, comparing antithrombotic medications (LMWH, DOAC) and mechanical interventions (GCS, IPC) within and across intervention classes.",
      "relaxed_aspects": {},
      "rationale": "Introduces established abbreviations (VTE, LMWH, DOAC, GCS, IPC) and the British spelling 'orthopaedic'; no conceptual broadening — the population, topic, and intervention scope are unchanged."
    },
    {
      "level": 2,
      "label": "Broadened population — orthopedic surgery",
      "strategy": "conceptual_single_aspect",
      "search_query": "Studies on VTE prophylaxis or thromboprophylaxis in patients undergoing orthopedic surgery, comparing antithrombotic medications and mechanical interventions within and across intervention classes.",
      "relaxed_aspects": {"population_or_entity": "orthopedic surgery patients"},
      "rationale": "Removes the 'major' qualifier to include all orthopedic procedures; widens population recall without changing the condition or intervention scope."
    },
    {
      "level": 3,
      "label": "Broadened condition — thrombosis",
      "strategy": "conceptual_single_aspect",
      "search_query": "Studies on thrombosis prevention or prophylaxis in patients undergoing orthopedic surgery, comparing antithrombotic medications and mechanical interventions.",
      "relaxed_aspects": {"topic_or_condition": "thrombosis"},
      "rationale": "Broadens from venous thromboembolism to thrombosis to capture studies on mixed or general thrombotic complications in orthopedic settings; increases recall at the cost of some topic precision."
    },
    {
      "level": 4,
      "label": "Controlled vocabulary — MEDLINE MeSH",
      "strategy": "indexing_variant",
      "search_query": "("Venous Thromboembolism"[MeSH] OR "Venous Thrombosis"[MeSH] OR "Pulmonary Embolism"[MeSH]) AND ("Arthroplasty, Replacement, Hip"[MeSH] OR "Arthroplasty, Replacement, Knee"[MeSH] OR "Hip Fractures"[MeSH]) AND ("Anticoagulants"[MeSH] OR "Compression Bandages"[MeSH] OR "Intermittent Pneumatic Compression Devices"[MeSH])",
      "relaxed_aspects": {},
      "rationale": "Parallel controlled vocabulary track using MeSH headings for MEDLINE; complements free-text Levels 1-3 by retrieving records indexed under standardized headings regardless of author terminology."
    }
  ]
}

Key distinctions demonstrated:
- Level 0 is the normalized research statement — it is never included in the output.
- Level 1 adds only lexical and abbreviation variants; relaxed_aspects is empty.
- Levels 2 and 3 each relax exactly one SAFE aspect (population_or_entity, then topic_or_condition).
- Level 4 uses terms directly from controlled_vocabulary_hints; it constructs a database-specific query and leaves relaxed_aspects empty because broadening here comes from vocabulary coverage, not aspect relaxation.
- The CONDITIONAL aspect (intervention) is not broadened because the query already covers both antithrombotic and mechanical approaches.
""".strip()


__all__ = ["SEARCH_ASPECT_ASSESSMENT_TEMPLATE", "SEARCH_EXPANSION_TEMPLATE"]
