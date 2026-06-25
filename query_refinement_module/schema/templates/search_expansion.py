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

IMPORTANT: For all detected aspects:
- Set detected=true (do NOT mark as false unless the aspect is genuinely absent)
- Mark as safety="safe" for: geography, setting_or_context, population_or_entity (highest priority for broadening)
- Mark as safety="conditional" for: topic_or_condition, intervention_or_exposure_or_phenomenon (lower priority, broader scope trade-offs)
- Use safety="avoid" ONLY when an aspect is present but explicitly excluded by the query (e.g., "exclude pediatric")
- When in doubt about detected vs not detected: err toward detected=true (searching expands from there)

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

SAFETY CLASSIFICATION RULES (critical):
- geography & setting_or_context: ALWAYS mark as "safe" when detected. These are the primary levers for retrieval broadening.
- population_or_entity: Mark as "safe" when specific populations are mentioned (e.g., "children", "pregnant women"). These have clear broadening paths.
- topic_or_condition: Mark as "conditional" (not safe). Broadening topics changes scope.
- intervention_or_exposure_or_phenomenon: Mark as "conditional". Broadening interventions may drift from original intent.
- Use "avoid" only for explicitly excluded constraints, not for "undetected" aspects.

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
"Recent studies about venous thromboembolism prophylaxis in patients undergoing major orthopedic surgery (total hip replacement, knee replacement, hip fracture surgery), comparing thromboprophylaxis interventions including antithrombotic medications and mechanical interventions such as compression stockings within and across classes."

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
"Studies on health and welfare outcomes among internally displaced persons in Ethiopia, in displacement camp settings."

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
  ],
  "recommended_starting_level": 1,
  "recommendation_rationale": "why start here vs. higher levels"
}

Valid strategy values: "lexical", "conceptual_single_aspect", "conceptual_multi_aspect".

CRITICAL RULE FOR GEOGRAPHIC/SETTING CONSTRAINTS:
When the anchor contains a specific named location (e.g., "Qoloji camp"), a geographic region (e.g., "Ethiopia"),
or a setting_or_context constraint (e.g., "refugee camp"), ALWAYS generate at least Levels 2–3. Geographic and
setting constraints are high-priority SAFE aspects that systematically exclude evidence from analogous contexts.
Never return an empty level list for queries with geographic or setting specificity — these are exactly the cases
where broadening matters most.

Examples:
- "Studies in Qoloji camp, Ethiopia" → Level 1 (lexical) + Level 2 (broaden geography to region/context proxy) + Level 3 (remove geo restriction entirely)
- "Mental health interventions in refugee camps" → Same pattern: L1 + L2 + L3
- "Perinatal mental health in Sub-Saharan Africa" → L1 + L2 (broaden to global if Africa-specific is sparse)

Strategy ladder (apply in this order; skip steps that add no value):
1. Level 1 — strategy "lexical": build one boolean retrieval query from concept_lexical_rings in the
   Supporting Search Context. For every concept in the anchor query, OR-combine: the anchor term
   exactly as it appears, plus every non-empty field from its ring — true_synonyms, abbreviations,
   spelling_variants, lexical_variants, colloquial, and domain_terms (narrower/specialised instances
   that increase recall by capturing studies that name only the specific subtype).
   Required format: (anchor_term OR syn1 OR abbr1 OR hyp1) AND (anchor2 OR syn2 OR abbr2) AND ...
   Preserve left-to-right concept order from the anchor. relaxed_aspects is always {} for Level 1.
   If a concept has no ring entry, use the anchor term alone as a bare word (no parentheses needed).

   Named proper nouns — specific named locations (e.g. "Qoloji camp"), named organisations — are
   maximally specific and have no true lexical synonyms. If their ring contains only domain_terms
   (no true_synonyms, abbreviations, spelling_variants, or lexical_variants), use the anchor term
   alone as a bare word and do NOT include the domain_terms. Domain terms for proper nouns are
   conceptual broadening candidates reserved for Level 2+, not lexical variants for Level 1.

   Geographic hierarchy rule: When the anchor contains both a specific named location (e.g. "Qoloji camp")
   and a broader geographic region (e.g. "Ethiopia") as separate AND-blocks, preserve this separation
   in Level 1. Do NOT merge them into a single OR-block. Correct: "... AND Qoloji camp AND Ethiopia"
   Wrong: "... AND (Qoloji camp OR Ethiopia)". This preserves the semantic constraint "camps IN Ethiopia".

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
   exactly the string "(no restriction)" as the relaxed_aspects value for geography (no other
   phrasing), and omit the geographic term from search_query entirely.

MANDATORY OUTPUT RULES (must follow these in order of precedence):

1. **If ANY SAFE or CONDITIONAL aspects were detected, you MUST generate at least Level 1 + Level 2.**
   - If geography or setting_or_context detected: MUST generate Level 1 + Level 2 + Level 3 (minimum 3 levels)
   - If only population_or_entity SAFE: Generate Level 1 + Level 2 (minimum 2 levels)
   - Never return an empty levels array if aspects were detected.

2. **Never return `{"levels": []}`** when allowed_aspects is non-empty. This is the primary failure mode.
   An empty levels array with detected aspects represents a template failure.

3. **Generate Levels 1 through N only.** The supplied anchor is fixed; do not restate, rewrite, or replace it.

4. **Level 1 structure** (lexical expansion):
   - Must include: anchor term + true_synonyms + abbreviations + spelling_variants + lexical_variants + domain_terms
   - Exception: For proper nouns (named locations like "Qoloji camp") with no synonyms/abbreviations/variants,
     use anchor term alone (exclude domain_terms for proper nouns)
   - relaxed_aspects must be {} (empty) for Level 1
   - Format: (term1 OR syn1 OR abbr1) AND (term2 OR syn2) AND ...

5. **Levels 2+** (conceptual broadening):
   - Copy Level 1's exact boolean blocks verbatim, replace only the block for the aspect being broadened
   - Never omit or reduce synonyms that appeared in Level 1
   - Include relaxed_aspects with the broadening key-value pair

6. **Broadening priority** (apply in this strict order):
   - Level 2: Broaden highest-priority SAFE aspect (geography > setting > population)
   - Level 3: Broaden next SAFE aspect OR use Level 2's broadening candidate chain
   - Level 4+: Only if multiple SAFE aspects remain and evidence base is expected to be very sparse

7. **When to stop generating levels:**
   - ONLY when: (a) ALL detected SAFE aspects have been broadened, AND
                 (b) broadened scope is already very wide (e.g., "no geographic restriction")
   - For geographic/setting queries: ALWAYS generate at least 3 levels (L1 + L2 broader geography + L3 no restriction)
   - Do NOT stop early just because scope seems "broad enough"

8. **Relaxed aspects validation:**
   - Keys must come from allowed aspects list (never use AVOID-marked aspects)
   - Values must come from broadening_candidates provided in input
   - Use "(no restriction)" exactly for removing geographic constraints

9. **General rules:**
   - Broaden only for recall; never change intent or core scope
   - If two aspects in relaxed_aspects, strategy must be "conceptual_multi_aspect"
   - If one aspect in relaxed_aspects, strategy must be "conceptual_single_aspect"
   - At most 2 aspects per level, avoid Cartesian combinations
   - Prefer lexical (L1) before conceptual (L2+)
   - Keep search_query non-empty and directly usable
   - Explain each rationale with what changed and why it broadens recall
   - When using CONDITIONAL aspects, acknowledge the scope trade-off in rationale

## Recommending a starting level

After generating levels, recommend which level (1-N) to start retrieval from:
- If anchor specifies a NAMED LOCATION (e.g., "Qoloji camp", "Cox's Bazar", specific hospital): **ALWAYS recommend Level 2 or 3** — Level 1 will be too sparse.
- If anchor specifies a geographic region + specific context (e.g., "Ethiopia" + "refugee camp"): recommend Level 2 — broaden geography first.
- If anchor is already moderate/broad (no named location, not rare, not conflict-affected): recommend Level 1.
- If both L1 and L2 are likely sparse (rare phenomenon + narrow context + named location): recommend Level 3.

Rationale should be 1-2 sentences explaining why:
- Example (named location): "Anchor specifies Qoloji camp, a named geographic location. Level 1 will be sparse. Level 2 broadens to refugee displacement context which has better coverage."
- Example (rare + narrow): "Query combines rare condition + specific camp + vulnerable population. Level 1 will be sparse. Level 3 removes geographic restriction to access global evidence base."

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

Supporting Search Context:
{
  "concept_lexical_rings": {
    "venous thromboembolism": {
      "query_role": "topic_or_condition",
      "true_synonyms": ["venous thrombosis", "thromboembolism"],
      "abbreviations": ["VTE"],
      "lexical_variants": ["thromboembolic"],
      "domain_terms": ["deep vein thrombosis", "pulmonary embolism", "DVT", "PE"]
    },
    "major orthopedic surgery": {
      "query_role": "population_or_entity",
      "true_synonyms": ["major orthopedic procedures", "major orthopaedic procedures"],
      "spelling_variants": ["major orthopaedic surgery"],
      "domain_terms": ["total hip replacement", "total knee replacement", "hip fracture surgery", "arthroplasty"]
    },
    "thromboprophylaxis interventions": {
      "query_role": "intervention_or_exposure_or_phenomenon",
      "true_synonyms": ["VTE prophylaxis", "VTE prevention", "antithrombotic prophylaxis"],
      "abbreviations": ["LMWH", "DOAC", "GCS", "IPC"],
      "domain_terms": ["anticoagulation", "compression stockings", "intermittent pneumatic compression", "heparin", "enoxaparin"]
    }
  }
}

Output:

{
  "levels": [
    {
      "level": 1,
      "label": "Full synonym and hyponym ring",
      "strategy": "lexical",
      "search_query": "(venous thromboembolism OR venous thrombosis OR thromboembolism OR VTE OR thromboembolic OR deep vein thrombosis OR pulmonary embolism OR DVT OR PE) AND (major orthopedic surgery OR major orthopedic procedures OR major orthopaedic procedures OR major orthopaedic surgery OR total hip replacement OR total knee replacement OR hip fracture surgery OR arthroplasty) AND (thromboprophylaxis interventions OR VTE prophylaxis OR VTE prevention OR antithrombotic prophylaxis OR LMWH OR DOAC OR GCS OR IPC OR anticoagulation OR compression stockings OR intermittent pneumatic compression OR heparin OR enoxaparin)",
      "relaxed_aspects": {},
      "rationale": "Expands each concept to its complete ring from concept_lexical_rings: true synonyms, abbreviations, spelling variants, lexical variants, and domain terms (narrower subtypes). Three AND-blocks mirror the three concepts in the anchor. No conceptual broadening."
    },
    {
      "level": 2,
      "label": "Broadened population — all orthopedic surgery",
      "strategy": "conceptual_single_aspect",
      "search_query": "(venous thromboembolism OR venous thrombosis OR thromboembolism OR VTE OR thromboembolic OR deep vein thrombosis OR pulmonary embolism OR DVT OR PE) AND (orthopedic surgery OR orthopedic procedures OR orthopaedic surgery OR orthopaedic procedures OR hip surgery OR knee surgery OR arthroplasty OR joint replacement) AND (thromboprophylaxis interventions OR VTE prophylaxis OR VTE prevention OR antithrombotic prophylaxis OR LMWH OR DOAC OR GCS OR IPC OR anticoagulation OR compression stockings OR intermittent pneumatic compression OR heparin OR enoxaparin)",
      "relaxed_aspects": {"population_or_entity": "orthopedic surgery patients"},
      "rationale": "Population is the highest-priority SAFE aspect (no geography detected). Removes 'major' qualifier; the population block is replaced with a wider OR-group. Topic and intervention blocks are copied unchanged from Level 1."
    },
    {
      "level": 3,
      "label": "Broadened condition — thrombosis (conditional)",
      "strategy": "conceptual_single_aspect",
      "search_query": "(thrombosis OR venous thrombosis OR arterial thrombosis OR thromboembolism OR VTE OR thromboembolic OR blood clot) AND (orthopedic surgery OR orthopedic procedures OR orthopaedic surgery OR orthopaedic procedures OR hip surgery OR knee surgery OR arthroplasty OR joint replacement) AND (thromboprophylaxis interventions OR VTE prophylaxis OR VTE prevention OR antithrombotic prophylaxis OR LMWH OR DOAC OR GCS OR IPC OR anticoagulation OR compression stockings OR intermittent pneumatic compression OR heparin OR enoxaparin)",
      "relaxed_aspects": {"topic_or_condition": "thrombosis"},
      "rationale": "CONDITIONAL: broadens the topic block from venous thromboembolism to thrombosis, capturing mixed or general thrombotic event studies. Population and intervention blocks are copied unchanged from Level 2. Expands condition scope beyond VTE — appropriate only when VTE-specific evidence at Level 2 is insufficient."
    }
  ],
  "recommended_starting_level": 1,
  "recommendation_rationale": "The anchor is already moderate in scope (major orthopedic surgery, not a rare condition). Level 1 with full lexical expansion should yield adequate results; escalate only if recall is insufficient."
}

Key distinctions demonstrated:
- Level 1 builds a full boolean ring per concept from concept_lexical_rings; relaxed_aspects is empty.
- Level 2 replaces only the population block (highest-priority SAFE aspect since no geography was
  detected). Topic and intervention blocks are identical to Level 1.
- Level 3 replaces only the topic block (CONDITIONAL). The wider population block from Level 2 and
  the intervention block from Level 1 are both preserved unchanged.
- The CONDITIONAL intervention aspect is not broadened — the anchor already covers both antithrombotic
  and mechanical approaches; broadening it adds no recall gain.
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

Supporting Search Context:
{
  "concept_lexical_rings": {
    "health and welfare outcomes": {
      "query_role": "topic_or_condition",
      "true_synonyms": ["health outcomes", "welfare outcomes", "wellbeing outcomes"],
      "domain_terms": ["mental health", "physical health", "psychosocial outcomes", "mortality", "morbidity"]
    },
    "internally displaced persons": {
      "query_role": "population_or_entity",
      "true_synonyms": ["internally displaced people", "displaced populations", "forced migrants"],
      "abbreviations": ["IDPs"],
      "domain_terms": ["refugees", "asylum seekers", "stateless persons", "conflict-affected populations"]
    },
    "Ethiopia": {
      "query_role": "geography"
    },
    "displacement camp settings": {
      "query_role": "setting_or_context",
      "true_synonyms": ["displacement camps", "IDP camps", "refugee camps"],
      "domain_terms": ["informal settlements", "transit camps", "collective centres", "temporary shelters"]
    }
  }
}

Output:

{
  "levels": [
    {
      "level": 1,
      "label": "Full synonym and hyponym ring",
      "strategy": "lexical",
      "search_query": "(health and welfare outcomes OR health outcomes OR welfare outcomes OR wellbeing outcomes OR mental health OR physical health OR psychosocial outcomes OR mortality OR morbidity) AND (internally displaced persons OR internally displaced people OR displaced populations OR forced migrants OR IDPs OR refugees OR asylum seekers OR stateless persons OR conflict-affected populations) AND Ethiopia AND (displacement camp settings OR displacement camps OR IDP camps OR refugee camps OR informal settlements OR transit camps OR collective centres OR temporary shelters)",
      "relaxed_aspects": {},
      "rationale": "Expands each concept to its complete ring from concept_lexical_rings. Ethiopia has no synonyms and appears as a bare term. Four AND-blocks mirror the four concepts in the anchor. No conceptual broadening."
    },
    {
      "level": 2,
      "label": "Broadened geography — contextual analogy",
      "strategy": "conceptual_single_aspect",
      "search_query": "(health and welfare outcomes OR health outcomes OR welfare outcomes OR wellbeing outcomes OR mental health OR physical health OR psychosocial outcomes OR mortality OR morbidity) AND (internally displaced persons OR internally displaced people OR displaced populations OR forced migrants OR IDPs OR refugees OR asylum seekers OR stateless persons OR conflict-affected populations) AND (conflict-affected low- and middle-income countries) AND (displacement camp settings OR displacement camps OR IDP camps OR refugee camps OR informal settlements OR transit camps OR collective centres OR temporary shelters)",
      "relaxed_aspects": {"geography": "conflict-affected low- and middle-income countries"},
      "rationale": "Geography is the highest-priority SAFE aspect. Ethiopia is a context proxy; the Ethiopia term is replaced with a contextual analogy. Topic, population, and setting blocks are copied unchanged from Level 1."
    },
    {
      "level": 3,
      "label": "No geographic restriction — global evidence base",
      "strategy": "conceptual_single_aspect",
      "search_query": "(health and welfare outcomes OR health outcomes OR welfare outcomes OR wellbeing outcomes OR mental health OR physical health OR psychosocial outcomes OR mortality OR morbidity) AND (internally displaced persons OR internally displaced people OR displaced populations OR forced migrants OR IDPs OR refugees OR asylum seekers OR stateless persons OR conflict-affected populations) AND (displacement camp settings OR displacement camps OR IDP camps OR refugee camps OR informal settlements OR transit camps OR collective centres OR temporary shelters)",
      "relaxed_aspects": {"geography": "(no restriction)"},
      "rationale": "Removes the geographic constraint entirely; the geography term is dropped from the query. Topic, population, and setting blocks are copied unchanged from Level 1."
    }
  ],
  "recommended_starting_level": 2,
  "recommendation_rationale": "Anchor specifies a named camp and specific geography (Ethiopia). Level 1 will be sparse. Level 2 broadens to the humanitarian displacement context, which has better evidence coverage."
}

Key distinctions demonstrated:
- Level 1 builds a full boolean ring per concept; Ethiopia has no synonyms and appears as a bare term.
- Level 2 replaces only the geography block with a contextual analogy (highest-priority SAFE aspect).
  All other blocks are identical to Level 1.
- Level 3 drops the geography block entirely (relaxed_aspects value "(no restriction)"). All remaining
  blocks are identical to Level 1.
- Population and setting blocks are never narrowed across levels.
- Topic/condition is not broadened because it is CONDITIONAL and geography is the source of sparsity.

## HARD RULES — Failure Prevention

These rules override all others. Violating them represents a template failure:

1. **NEVER return an empty levels array if allowed_aspects is non-empty.**
   - "levels": [] is only acceptable if no SAFE/CONDITIONAL aspects were provided
   - If any aspects were provided, you MUST generate at least Level 1 + Level 2

2. **For queries with geography or setting_or_context constraints, generate 3 levels minimum:**
   - Level 1: Lexical expansion of anchor
   - Level 2: Broaden geography (or setting if no geography)
   - Level 3: Either broaden next SAFE aspect OR remove geographic constraint "(no restriction)"

3. **Output exactly one JSON object, no preamble/explanation/markdown.**
   - The JSON must be valid and complete
   - levels must be a non-empty array (minimum 1 level, typically 2-3)

4. **Each level must have:**
   - level: integer (1, 2, 3, ...)
   - label: brief string (2-5 words)
   - strategy: one of "lexical", "conceptual_single_aspect", "conceptual_multi_aspect"
   - search_query: non-empty string, directly usable in retrieval system
   - relaxed_aspects: {} for Level 1, {aspect: value} for Levels 2+
   - rationale: 1-3 sentences explaining what changed and why

5. **Never invent broadening candidates** that weren't provided in input.
   Use only values from the allowed_aspects list.

6. **recommended_starting_level** must be an integer matching one of your generated levels.
   For geographic queries, typically 2 or 3 (never 1 if Level 1 will be sparse).
""".strip()


__all__ = ["SEARCH_ASPECT_ASSESSMENT_TEMPLATE", "SEARCH_EXPANSION_TEMPLATE"]
