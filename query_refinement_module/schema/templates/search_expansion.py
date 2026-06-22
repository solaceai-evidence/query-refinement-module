"""Prompt templates for the fixed-core search expansion stage."""

SEARCH_ASPECT_ASSESSMENT_TEMPLATE = """
You analyze a retrieval anchor query and detect which of a FIXED set of search aspects are present in it.

Systematic reviews require sensitive searches that maximize recall. Your goal is to identify every
constraint in the anchor that could legitimately be broadened to capture relevant evidence that
strict anchoring would miss.

The fixed aspect set (the only valid aspect ids):
- topic_or_condition: the core subject, condition, or problem of the query
- population_or_entity: the specific population, group, or entity studied
- intervention_or_exposure_or_phenomenon: the intervention, exposure, or phenomenon of interest
- setting_or_context: the setting or context (e.g. hospitals, schools, refugee camps, online platforms)
- geography: the geographic scope (e.g. a city, country, region)
- time_scope: the temporal scope (e.g. a year range, a period)

Disambiguation — setting_or_context vs geography:
- Classify as setting_or_context when the location describes a type of place or institutional context
  (e.g. "rural health clinics", "refugee camps", "urban schools", "online forums"). The type of
  place is the constraint, not the political geography.
- Classify as geography when the location names a political or geographic entity (e.g. "Ethiopia",
  "Sub-Saharan Africa", "the United Kingdom", "Latin America").
- Both may be present simultaneously only when the query contains distinct constraints of each kind
  (e.g. "displacement camps in Ethiopia" → setting_or_context: displacement camps; geography: Ethiopia).

Return exactly one JSON object matching this schema:

{
  "assessments": [
    {
      "aspect": "geography",
      "detected": true,
      "detected_value": "the exact phrase or constraint found in the anchor query",
      "broadening_candidates": ["a broader value", "a still broader value", "broadest option"],
      "reasoning": "why this aspect was detected and why each candidate broadens retrieval scope"
    }
  ]
}

General rules:
- Include one assessment object per aspect in the fixed set, in any order. Use detected=false with
  empty detected_value and empty broadening_candidates when the aspect is absent.
- detected_value must quote or closely paraphrase what is actually in the anchor query. Never invent
  constraints that are not present.
- broadening_candidates must be broader in retrieval scope than the detected value, ordered from
  least to most broad. Provide at most three.
- Do not propose candidates that change the research question itself (e.g. switching to a different
  condition, comparator, or outcome). Broadening candidates widen the retrieval net within the
  existing question.
- Never propose broadening candidates for comparators, outcomes, or methodological constraints;
  they are not part of the fixed aspect set.
- Use the optional advisory dimension values and synonyms only to resolve ambiguity about what the
  anchor query means; the anchor query itself is the source of truth.

Geography-specific rules:
- Ask: is this geographic constraint the variable under study, or a proxy for a context characteristic?
  - Variable under study (e.g. "comparing outcomes across Ethiopian regions", "policy differences
    between EU member states"): use geographic containment hierarchy as candidates
    (e.g. "East Africa", "Sub-Saharan Africa", "no geographic restriction").
  - Context proxy (e.g. "Ethiopia" appears because of a displacement crisis, income level, health
    system type, or political situation rather than because Ethiopia itself is what is being studied):
    include contextual analogy candidates that replace the location with its underlying characteristic
    (e.g. "conflict-affected low- and middle-income countries", "humanitarian crisis settings globally").
    Contextual analogy candidates may rank ahead of geographic supersets because they capture
    contextually equivalent evidence from other regions.
- Always include "no geographic restriction" as the final (broadest) candidate when any geographic
  constraint is detected. Removing the geographic restriction entirely is a valid and recommended
  systematic review strategy when evidence from the specific location is sparse.

Topic/condition-specific rules:
- Topic or condition broadening changes the research question scope (e.g. "VTE" → "thrombosis"
  includes arterial events not in the original question). List candidates but flag in reasoning
  that this is a scope-changing move to be applied only conditionally.

Time-scope rules:
- broadening_candidates must only relax or widen an existing time constraint. Never propose adding
  a date restriction when one is not present in the anchor.

## Example 1 — Biomedical (no geography or setting detected)

Anchor Query:
"Recent studies about venous thromboembolism prophylaxis in patients undergoing major orthopedic
surgery (total hip replacement, knee replacement, hip fracture surgery), comparing thromboprophylaxis
interventions including antithrombotic medications and mechanical interventions such as compression
stockings within and across classes."

Output:

{
  "assessments": [
    {
      "aspect": "topic_or_condition",
      "detected": true,
      "detected_value": "venous thromboembolism",
      "broadening_candidates": ["thrombosis", "vascular events"],
      "reasoning": "VTE is the primary condition. 'Thrombosis' widens to arterial events not in the original question; 'vascular events' is a further superset. Both are scope-changing and should only be applied conditionally."
    },
    {
      "aspect": "population_or_entity",
      "detected": true,
      "detected_value": "patients undergoing major orthopedic surgery",
      "broadening_candidates": ["orthopedic surgery patients", "surgical patients"],
      "reasoning": "The anchor constrains to major orthopedic procedures. Removing 'major' captures all orthopedic surgeries; 'surgical patients' is the broadest coherent superset without leaving the surgical context."
    },
    {
      "aspect": "intervention_or_exposure_or_phenomenon",
      "detected": true,
      "detected_value": "thromboprophylaxis interventions",
      "broadening_candidates": ["prophylaxis", "surgical prophylaxis"],
      "reasoning": "Thromboprophylaxis is the intervention class. 'Prophylaxis' broadens to all preventive approaches; 'surgical prophylaxis' widens without leaving the surgical context. Intervention broadening risks scope drift and should be applied conditionally."
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

## Example 2 — Social science (geography as context proxy; setting detected separately)

Anchor Query:
"Studies on health and welfare outcomes among internally displaced persons in Ethiopia,
in displacement camp settings."

Output:

{
  "assessments": [
    {
      "aspect": "topic_or_condition",
      "detected": true,
      "detected_value": "health and welfare outcomes",
      "broadening_candidates": ["health outcomes", "wellbeing outcomes"],
      "reasoning": "Health and welfare outcomes is the core topic. 'Health outcomes' removes the welfare dimension; 'wellbeing outcomes' is a broader framing. Both are scope-changing and should only be applied conditionally."
    },
    {
      "aspect": "population_or_entity",
      "detected": true,
      "detected_value": "internally displaced persons",
      "broadening_candidates": ["displaced populations", "forced migrants"],
      "reasoning": "IDPs are a specific legal/administrative category. 'Displaced populations' includes refugees and stateless persons; 'forced migrants' is the broadest superset covering all involuntary mobility."
    },
    {
      "aspect": "intervention_or_exposure_or_phenomenon",
      "detected": false,
      "detected_value": "",
      "broadening_candidates": [],
      "reasoning": "No specific intervention or exposure is stated in the anchor."
    },
    {
      "aspect": "setting_or_context",
      "detected": true,
      "detected_value": "displacement camp settings",
      "broadening_candidates": ["formal and informal displacement settlements", "humanitarian assistance settings"],
      "reasoning": "The anchor restricts to displacement camps specifically. The first candidate captures informal and spontaneous settlements; the second broadens to all humanitarian delivery contexts."
    },
    {
      "aspect": "geography",
      "detected": true,
      "detected_value": "Ethiopia",
      "broadening_candidates": [
        "conflict-affected low- and middle-income countries",
        "humanitarian crisis settings globally",
        "no geographic restriction"
      ],
      "reasoning": "Ethiopia appears as a context proxy for displacement crisis conditions, not as the variable under study. Geographic containment hierarchy (East Africa, Sub-Saharan Africa) would miss contextually equivalent evidence from displaced populations in South Asia, the Middle East, and Latin America. Contextual analogy candidates capture this equivalence. 'No geographic restriction' is the broadest valid option, recommended when evidence from Ethiopia specifically is sparse."
    },
    {
      "aspect": "time_scope",
      "detected": false,
      "detected_value": "",
      "broadening_candidates": [],
      "reasoning": "No temporal constraint is present in the anchor."
    }
  ]
}
""".strip()


SEARCH_EXPANSION_TEMPLATE = """
You generate optional retrieval broadening levels from an existing search anchor, following a fixed
aspect policy.

Systematic reviews require sensitive searches that maximize recall. These expansion levels represent
a progressive precision–recall trade-off: each level widens the retrieval net to capture relevant
evidence that the anchor query alone would miss. Apply them in order — use lower levels first and
move to wider levels only when the evidence base is insufficient.

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

Valid strategy values: "lexical", "conceptual_single_aspect", "conceptual_multi_aspect".

Strategy ladder (apply in this order; skip steps that add no value):
1. Level 1 — strategy "lexical": introduce spelling variants, abbreviations, and true synonyms only.
   Do not broaden any aspect conceptually. relaxed_aspects is empty for lexical levels.
   Valid lexical changes: spelling variants (e.g. orthopaedic/orthopedic), abbreviations (VTE, IDP,
   LMWH), true synonyms (different names for the exact same concept), plural/singular, word-order
   variants, hyphenation.
   Invalid at Level 1: broader category terms, related-but-distinct terms, conceptual supersets —
   those belong at Level 2 or higher.

2. Level 2 — strategy "conceptual_single_aspect": broaden exactly one aspect using one of its
   allowed broadening candidates. When multiple SAFE aspects are detected, prefer in this order:
   a. geography — geographic constraints are search-strategy artifacts that systematically exclude
      analogous evidence; broaden or remove them first. Use contextual analogy when geography
      appears as a context proxy (e.g. a country named for a crisis or income level), not just
      geographic containment.
   b. setting_or_context — setting restrictions narrow the evidence pool; broaden after geography.
   c. population_or_entity — widen to a larger but coherent population class.
   d. topic_or_condition — only when marked CONDITIONAL and explicitly justified; broadening the
      condition changes the research question scope.

3. Level 3 — strategy "conceptual_single_aspect" or "conceptual_multi_aspect": a wider single-aspect
   step, or at most two aspects when the evidence base for the Level 2 scope is likely to remain
   sparse (e.g. rare condition, specific minority population, conflict-affected low-income context
   with limited research output). At most one of the two aspects may be CONDITIONAL.
   "No geographic restriction" is a valid Level 3 option: if Level 2 broadened geography to a
   larger region or contextual class, Level 3 may remove the geographic constraint entirely. Use
   relaxed_aspects value "(no restriction)" and omit the geographic term from search_query.

Rules:
- Generate Levels 1 through N only. Never generate Level 0. The supplied Level 0 anchor is fixed;
  do not restate, rewrite, or replace it.
- Broaden only for search recall; never change the intent, scope, or core meaning of the anchor query.
- Keep each search_query concise, readable, and directly usable as a retrieval query.
- Prefer one short natural-language retrieval string or one compact keyword query, not a long synonym dump.
- Do not concatenate every available synonym. Use only the highest-value lexical variants needed for recall.
- Avoid telegraphic keyword soup. Preserve recognizable phrase structure whenever possible.
- Unless the input already requires dense Boolean syntax, keep each level to the smallest query that
  expresses the intended broadening.
- relaxed_aspects keys must come from the allowed aspects listed in the input. Never use an aspect
  marked AVOID or an aspect that was not detected.
- Conceptual broadened values must come from (or be consistent with) the allowed broadening candidates
  given per aspect.
- If relaxed_aspects contains exactly two keys, use strategy "conceptual_multi_aspect".
- If strategy is "conceptual_single_aspect", relax exactly one aspect.
- Relax at most two aspects per level, and avoid Cartesian combinations.
- Prefer lexical expansion before any conceptual broadening.
- Treat filters as retrieval constraints to respect during broadening; do not contradict them or
  force them into the query text unless they naturally belong there.
- Use provided synonyms selectively, only when they improve recall without changing scope.
- Return zero additional levels if the anchor query is already broad or no useful broadening exists.
- Return at most three additional levels.
- Keep search_query non-empty and directly usable by a retrieval system.
- Explain in each rationale what changed and why it broadens recall without scope drift.
- When a CONDITIONAL aspect is used, explicitly acknowledge the scope trade-off in the rationale.

## Example 1 — Biomedical (no geography; CONDITIONAL topic used at Level 3)

Level 0 Anchor (given — do not regenerate):
"Recent studies about venous thromboembolism prophylaxis in patients undergoing major orthopedic
surgery (total hip replacement, knee replacement, hip fracture surgery), comparing thromboprophylaxis
interventions including antithrombotic medications and mechanical interventions such as compression
stockings within and across classes."

Allowed Aspects For Search-Only Broadening:
[{"aspect": "topic_or_condition", "safety": "conditional", "detected_value": "venous thromboembolism", "broadening_candidates": ["thrombosis", "vascular events"]},
 {"aspect": "population_or_entity", "safety": "safe", "detected_value": "patients undergoing major orthopedic surgery", "broadening_candidates": ["orthopedic surgery patients", "surgical patients"]},
 {"aspect": "intervention_or_exposure_or_phenomenon", "safety": "conditional", "detected_value": "thromboprophylaxis interventions", "broadening_candidates": ["prophylaxis", "surgical prophylaxis"]}]

Output:

{
  "levels": [
    {
      "level": 1,
      "label": "Lexical variants",
      "strategy": "lexical",
      "search_query": "Studies on VTE prophylaxis or thromboprophylaxis in patients undergoing major orthopedic or orthopaedic surgery, comparing antithrombotic medications (LMWH, DOAC) and mechanical interventions (GCS, IPC) within and across intervention classes.",
      "relaxed_aspects": {},
      "rationale": "Introduces established abbreviations (VTE, LMWH, DOAC, GCS, IPC) and the British spelling 'orthopaedic'. No conceptual broadening — population, topic, and intervention scope are unchanged."
    },
    {
      "level": 2,
      "label": "Broadened population — all orthopedic surgery",
      "strategy": "conceptual_single_aspect",
      "search_query": "Studies on VTE prophylaxis or thromboprophylaxis in patients undergoing orthopedic surgery, comparing antithrombotic medications and mechanical interventions within and across intervention classes.",
      "relaxed_aspects": {"population_or_entity": "orthopedic surgery patients"},
      "rationale": "Removes the 'major' qualifier to include all orthopedic procedures. Widens population recall without changing condition or intervention scope. Population is the highest-priority SAFE aspect here since no geography was detected."
    },
    {
      "level": 3,
      "label": "Broadened condition — thrombosis (conditional)",
      "strategy": "conceptual_single_aspect",
      "search_query": "Studies on thrombosis prevention or prophylaxis in patients undergoing orthopedic surgery, comparing antithrombotic medications and mechanical interventions.",
      "relaxed_aspects": {"topic_or_condition": "thrombosis"},
      "rationale": "Broadens from venous thromboembolism to thrombosis to capture studies on mixed or general thrombotic complications in orthopedic settings. This is a CONDITIONAL change — it expands the condition scope beyond VTE and accepts topic imprecision in exchange for higher recall. Appropriate only when VTE-specific evidence is insufficient after Level 2."
    }
  ]
}

Key distinctions demonstrated:
- Level 0 is the anchor — never included in output.
- Level 1 adds lexical variants only; relaxed_aspects is empty.
- Level 2 broadens the single SAFE aspect (population). No geography was detected, so the ladder
  goes directly to population.
- Level 3 uses a CONDITIONAL aspect (topic_or_condition). The rationale explicitly acknowledges
  the scope trade-off and the condition under which this level applies.
- The second CONDITIONAL aspect (intervention) is not broadened because the anchor already covers
  both antithrombotic and mechanical approaches — no additional recall gain.
- Controlled vocabulary is not part of expansion levels; it is embedded in the anchor via
  combined_blocks and applied by source connectors.

## Example 2 — Social science (geography as context proxy; no restriction at Level 3)

Level 0 Anchor (given — do not regenerate):
"Studies on health and welfare outcomes among internally displaced persons in Ethiopia,
in displacement camp settings."

Allowed Aspects For Search-Only Broadening:
[{"aspect": "population_or_entity", "safety": "safe", "detected_value": "internally displaced persons", "broadening_candidates": ["displaced populations", "forced migrants"]},
 {"aspect": "setting_or_context", "safety": "safe", "detected_value": "displacement camp settings", "broadening_candidates": ["formal and informal displacement settlements", "humanitarian assistance settings"]},
 {"aspect": "geography", "safety": "safe", "detected_value": "Ethiopia", "broadening_candidates": ["conflict-affected low- and middle-income countries", "humanitarian crisis settings globally", "no geographic restriction"]}]

Output:

{
  "levels": [
    {
      "level": 1,
      "label": "Lexical variants",
      "strategy": "lexical",
      "search_query": "Studies on health and welfare outcomes among IDPs or internally displaced people in Ethiopia, in displacement camps or IDP camps.",
      "relaxed_aspects": {},
      "rationale": "Introduces the abbreviation IDP, the common alternative phrasing 'internally displaced people', and 'IDP camps' as a near-synonym for displacement camp settings. No conceptual broadening."
    },
    {
      "level": 2,
      "label": "Broadened geography — contextual analogy",
      "strategy": "conceptual_single_aspect",
      "search_query": "Studies on health and welfare outcomes among internally displaced persons or IDPs in conflict-affected low- and middle-income countries, in displacement camp settings.",
      "relaxed_aspects": {"geography": "conflict-affected low- and middle-income countries"},
      "rationale": "Geography is the highest-priority SAFE aspect. Ethiopia appears as a context proxy for displacement crisis conditions, not as the variable under study. Evidence from contextually analogous settings (e.g. South Sudan, DRC, Syria, Bangladesh) is directly relevant and would be missed by restricting to Ethiopia alone. Geographic containment hierarchy (East Africa) would exclude the most relevant analogues globally."
    },
    {
      "level": 3,
      "label": "No geographic restriction — global evidence base",
      "strategy": "conceptual_single_aspect",
      "search_query": "Studies on health and welfare outcomes among internally displaced persons or displaced populations, in displacement camp or humanitarian assistance settings.",
      "relaxed_aspects": {"geography": "(no restriction)"},
      "rationale": "Removes the geographic constraint entirely to capture the full global evidence base on displaced populations. Appropriate when evidence from the Level 2 contextual scope remains sparse. The setting constraint (displacement/humanitarian) preserves contextual focus without a geographic filter."
    }
  ]
}

Key distinctions demonstrated:
- Geography is broadened at Level 2 (highest-priority SAFE aspect) before population or setting.
- Level 2 uses contextual analogy rather than geographic containment because Ethiopia is a context
  proxy, not the variable under study.
- Level 3 removes the geographic restriction entirely using relaxed_aspects value "(no restriction)";
  the search_query omits the geographic term completely.
- Population (IDPs) and setting (displacement camps) remain unchanged through Levels 1–3 because
  they define the research question and are not the source of evidence sparsity.
- Topic/condition (health and welfare outcomes) is not broadened because it is CONDITIONAL and
  the evidence base is expected to be adequate once geography is opened up.
""".strip()


__all__ = ["SEARCH_ASPECT_ASSESSMENT_TEMPLATE", "SEARCH_EXPANSION_TEMPLATE"]
