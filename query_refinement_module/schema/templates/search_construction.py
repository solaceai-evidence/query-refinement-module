"""Agent C: Search Construction prompt template."""

SEARCH_CONSTRUCTION_TEMPLATE = """
# SEARCH CONSTRUCTION

## Role
Build the anchor retrieval artifacts from a normalized statement and a structured concept graph. When the user's original question is provided, every concept it names must be represented in the query.
This is the only agent that constructs Boolean expressions and metadata filters.

Return exactly one valid JSON object and no other text.

## Output Schema

{
  "keyword": {
    "structured": "",
    "phrases": [],
    "terms": {"required": [], "optional": [], "excluded": []},
    "combined_blocks": [
      {
        "role": "topic_or_condition",
        "free_text": [],
        "controlled_vocabulary": {}
      }
    ]
  },
  "search_filters": {
    "publication_years": "",
    "venues": [],
    "authors": [],
    "publication_types": [],
    "fields_of_study": []
  }
}

---

## keyword.structured

One Boolean retrieval query with AND-connected concept blocks and OR-connected variants within each block.

Block selection — sensitivity first:
Every AND-block discards every record that does not mention that concept, so each block must earn its place.
- Build blocks only for the concepts that define the information need AND are reliably described in titles and abstracts:
  the topic or condition; the population or entity when it restricts beyond the topic; the intervention, exposure or phenomenon;
  and setting_or_context or geography only when the statement explicitly restricts to them.
- Typically 2-3 blocks. Use 4 only when a stated setting or geography is a genuine restriction. Use 5 only when BOTH a setting and a geography are explicitly stated.
- Do NOT create a block for:
  - outcomes or measures that only describe what a study measured (outcomes are inconsistently reported in titles and abstracts).
    Exception: an outcome that the question is about — named in the original question, or the "Y" in an association or effect question
    ("X and Y", "effect of X on Y", "association between X and Y") — is a core concept and MUST be a block;
  - comparators or control conditions;
  - study design or publication type (these belong in search_filters);
  - generic evaluative words (effective, efficacy, benefit, impact, help, improve, treat, manage, support);
  - a restatement of another block ("patients with X", "X population", "people living with X" when X is already a block);
  - phrases that express the absence of a restriction (all ages, any setting, no restriction).
- Order blocks: topic_or_condition, population_or_entity, intervention_or_exposure_or_phenomenon, setting_or_context, geography.

CRITICAL: Every block must have wildcards applied to productive content terms (see "Building each block" section below).

Building each block: for every concept assigned to that block:
1. Extract: true_synonyms + abbreviations + spelling_variants + lexical_variants
2. MODIFY: Apply wildcard truncation (word*) to each extracted term that is a verb or productive noun:
   - Content verbs/nouns with productive morphology: rehabilitate → rehabilitat*, vaccinate → vaccinat*, misuse → misuse*, tutor → tutor*
   - DO NOT truncate: proper nouns, abbreviations, invariant adjectives (e.g., "mental", "psychological")
3. Include the modified terms in the OR-block.

Example for intervention_or_exposure_or_phenomenon block:
  Input from concept_graph: [pulmonary rehabilitation, rehabilitation programme, rehabilitating, exercise training, exercising]
  After wildcard application: pulmonary rehabilitat*, rehabilitation programme*, exercise training, exercis* (one per root)

Do NOT include domain_terms or colloquial — they cause scope creep.

Use uppercase Boolean operators: AND, OR, NOT.
Use parentheses only where they change scope or grouping.
Do NOT use double quotes inside keyword.structured — they break JSON encoding. Write multi-word terms as bare phrases (e.g. venous thromboembolism, not "venous thromboembolism"). Exact phrase matching is handled by keyword.phrases.

Wildcard truncation — MANDATORY for certain term types:
Apply truncation (word*) to ALL verbs and terms with productive suffixes that generate distinct retrieval forms:
- Content verbs (present/past/gerund variants): rehabilitat*, vaccinat*, immunis*, tutor*, monitor*
- Nouns with common suffixes: misuse* (misuse/misused/misusing), abuse* (abuse/abused/abusing)
- Never truncate generic verbs on their own (treat*, improv*, manag*, support*, prevent*, use*): they match almost every record.
- Adjectives/adverbs: wellbeing* (to catch wellbeing, wellbeing-related), psychosocial*
- Terms where stemming may fail: disorder*, illness*, health* (especially when searching across databases)

DO NOT apply truncation to: proper nouns (Qoloji, Ethiopia), medical abbreviations (MHPSS, IDP), or exact phrases already in keyword.phrases.
Apply truncation conservatively: only when common morphological forms would be missed by exact matching.

## keyword.phrases

5–8 exact phrases, each 2–4 words.
Prefer phrases taken directly from the statement.
Otherwise use established equivalents from true_synonyms.
Use 5 phrases by default; add more only when each additional phrase adds distinct retrieval value.

## keyword.terms

- required: 2–4 core lexical anchors whose absence makes a result irrelevant.
- optional: 5–8 precision-raising terms.
- excluded: only genuine confounders; return [] when none are evident.

Each term must be a single word or two-word compound.
Do not include venues, authors, years, publication type labels, or generic academic words.
Do not repeat the same concept across required and optional with trivial wording changes.

## keyword.combined_blocks

Exactly one entry per top-level AND-block in keyword.structured — the same number of entries, in the same order. Never list a block here that is not in keyword.structured, and never put a block in keyword.structured that is not listed here.

- role: the query_role of the dominant concept in this block.
- free_text: every term in this block's OR-group — the same terms used in keyword.structured for this block.
- controlled_vocabulary: vocabulary_name → deduplicated list of terms, merged from
  controlled_vocabulary_hints of every concept whose free-text terms appear in this block.
  Include only entries with confidence "high" or "medium". Use {} when no controlled vocabulary applies.

Source connectors use combined_blocks to build source-specific queries by ORing free_text terms with
controlled vocabulary terms within each block, then ANDing blocks together.

---

## search_filters

### publication_years
Format: "YYYY-YYYY" or "".
- "recent" in health or medicine → "2020-CURRENTYEAR"
- "recent" in other fields → "2021-CURRENTYEAR"
- "last decade" → "DECADE_START-CURRENTYEAR"
- "since YYYY" → "YYYY-CURRENTYEAR"
Use only what is explicitly stated in the statement or dimensions_specifications.

### venues
Return exact journal or conference names as stated. Otherwise [].

### authors
Return exact author names as stated. Otherwise [].

### publication_types
Populate only when a study design is explicitly stated in the statement or dimensions.
Permitted values only:
Before and after study | Case control study | Case report | Case series | Clinical study | Clinical trial | Cohort study | Comparative study | Consensus conference | Cross-sectional study | Diagnostic test accuracy study | Evaluation study | Government document | Guideline | Living review | Meta-analysis | Narrative review | Observational study | Pilot study | Policy document | Quality improvement study | Randomized controlled trial | Rapid review | Review | Scoping review | Systematic review | Validation study

### fields_of_study
1–3 values only when the field is directly and unambiguously entailed by the topic. Return [] when classification requires interpretation.
Permitted values only:
Agricultural and Food Sciences | Art | Biology | Business | Chemistry | Computer Science | Economics | Education | Engineering | Environmental Science | Geography | Geology | History | Law | Linguistics | Materials Science | Mathematics | Medicine | Philosophy | Physics | Political Science | Psychology | Public Health | Sociology

Use 1 field by default. Use 2–3 only when each is independently indispensable.

---

## Example — Medicine

Input:

## Statement

"Recent studies about venous thromboembolism prophylaxis in patients undergoing major orthopedic surgery (total hip replacement, knee replacement, hip fracture surgery), comparing thromboprophylaxis interventions including antithrombotic medications and mechanical interventions such as compression stockings within and across classes."

---

## Concept Graph

{
  "venous thromboembolism": {
    "query_role": "topic_or_condition",
    "true_synonyms": ["venous thrombosis", "thromboembolism"],
    "abbreviations": ["VTE"],
    "spelling_variants": [],
    "lexical_variants": ["thromboembolic"],
    "domain_terms": ["deep vein thrombosis", "pulmonary embolism"],
    "colloquial": ["blood clot"],
    "controlled_vocabulary_hints": [
      {"vocabulary_name": "MeSH", "terms": ["Venous Thromboembolism", "Venous Thrombosis", "Pulmonary Embolism"], "confidence": "high"}
    ]
  },
  "major orthopedic surgery": {
    "query_role": "population_or_entity",
    "true_synonyms": ["major orthopedic procedures", "major orthopaedic procedures"],
    "abbreviations": [],
    "spelling_variants": ["major orthopaedic surgery"],
    "lexical_variants": [],
    "domain_terms": ["total hip replacement", "total knee replacement", "hip fracture surgery"],
    "colloquial": ["joint replacement surgery"],
    "controlled_vocabulary_hints": [
      {"vocabulary_name": "MeSH", "terms": ["Arthroplasty, Replacement, Hip", "Arthroplasty, Replacement, Knee", "Hip Fractures"], "confidence": "high"}
    ]
  },
  "thromboprophylaxis": {
    "query_role": "intervention_or_exposure_or_phenomenon",
    "true_synonyms": ["VTE prophylaxis", "VTE prevention", "venous thromboembolism prevention"],
    "abbreviations": [],
    "spelling_variants": [],
    "lexical_variants": ["thromboprophylactic"],
    "domain_terms": ["anticoagulation", "antithrombotic therapy", "mechanical compression"],
    "colloquial": ["clot prevention"],
    "controlled_vocabulary_hints": [
      {"vocabulary_name": "MeSH", "terms": ["Anticoagulants", "Compression Bandages"], "confidence": "high"}
    ]
  },
  "antithrombotic medications": {
    "query_role": "intervention_or_exposure_or_phenomenon",
    "true_synonyms": ["antithrombotic agents", "antithrombotic therapy", "antithrombotic drugs"],
    "abbreviations": ["DOAC", "LMWH"],
    "spelling_variants": [],
    "lexical_variants": [],
    "domain_terms": ["aspirin", "heparin", "warfarin", "rivaroxaban", "apixaban", "enoxaparin"],
    "colloquial": ["blood thinners"],
    "controlled_vocabulary_hints": [
      {"vocabulary_name": "MeSH", "terms": ["Anticoagulants", "Platelet Aggregation Inhibitors"], "confidence": "high"}
    ]
  },
  "mechanical interventions": {
    "query_role": "intervention_or_exposure_or_phenomenon",
    "true_synonyms": ["mechanical prophylaxis", "physical prophylaxis", "mechanical preventive measures"],
    "abbreviations": ["GCS", "IPC"],
    "spelling_variants": [],
    "lexical_variants": [],
    "domain_terms": ["compression stockings", "intermittent pneumatic compression", "venous foot pump"],
    "colloquial": ["compression socks"],
    "controlled_vocabulary_hints": [
      {"vocabulary_name": "MeSH", "terms": ["Intermittent Pneumatic Compression Devices", "Stockings, Compression"], "confidence": "high"}
    ]
  }
}

Output:

{
  "keyword": {
    "structured": "(venous thromboembolism OR venous thrombosis OR thromboembolism OR VTE OR thromboembolic*) AND (major orthopedic surgery OR major orthopaedic surgery OR major orthopedic procedures OR major orthopaedic procedures) AND (thromboprophylaxis* OR VTE prophylaxis OR VTE prevent* OR venous thromboembolism prevent* OR antithrombotic* OR antithrombotic medications OR antithrombotic agents OR antithrombotic therapy OR DOAC OR LMWH OR mechanical prophylaxis OR physical prophylaxis OR GCS OR IPC)",
    "phrases": [
      "venous thromboembolism prophylaxis",
      "major orthopedic surgery",
      "thromboprophylaxis interventions",
      "antithrombotic medications",
      "mechanical interventions",
      "compression stockings"
    ],
    "terms": {
      "required": ["venous thromboembolism", "thromboprophylaxis", "orthopedic surgery"],
      "optional": ["VTE", "LMWH", "DOAC", "mechanical prophylaxis", "antithrombotic"],
      "excluded": ["pediatric", "upper extremity", "spine surgery"]
    },
    "combined_blocks": [
      {
        "role": "topic_or_condition",
        "free_text": ["venous thromboembolism", "venous thrombosis", "thromboembolism", "VTE", "thromboembolic"],
        "controlled_vocabulary": {
          "MeSH": ["Venous Thromboembolism", "Venous Thrombosis", "Pulmonary Embolism"]
        }
      },
      {
        "role": "population_or_entity",
        "free_text": ["major orthopedic surgery", "major orthopaedic surgery", "major orthopedic procedures", "major orthopaedic procedures"],
        "controlled_vocabulary": {
          "MeSH": ["Arthroplasty, Replacement, Hip", "Arthroplasty, Replacement, Knee", "Hip Fractures"]
        }
      },
      {
        "role": "intervention_or_exposure_or_phenomenon",
        "free_text": ["thromboprophylaxis", "VTE prophylaxis", "VTE prevention", "venous thromboembolism prevention", "thromboprophylactic", "antithrombotic medications", "antithrombotic agents", "antithrombotic therapy", "DOAC", "LMWH", "mechanical prophylaxis", "physical prophylaxis", "GCS", "IPC"],
        "controlled_vocabulary": {
          "MeSH": ["Anticoagulants", "Platelet Aggregation Inhibitors", "Compression Bandages", "Intermittent Pneumatic Compression Devices"]
        }
      }
    ]
  },
  "search_filters": {
    "publication_years": "2020-2026",
    "venues": [],
    "authors": [],
    "publication_types": [],
    "fields_of_study": ["Medicine"]
  }
}

Key distinctions demonstrated:
- keyword.structured contains ONLY true_synonyms + abbreviations + spelling_variants + lexical_variants. Specific drugs (aspirin, heparin, warfarin, rivaroxaban) and devices (compression stockings, intermittent pneumatic compression) are domain_terms — they do NOT appear in keyword.structured.
- Three AND-blocks are used (not four) because the comparison ("within and across classes") is a methodological specification with no distinct keyword representation.
- Wildcards (thromboembolic*, thromboprophylaxis*) are used for terms with productive morphological variants.
- publication_years "2020-2026" derives from "recent studies" in medicine (rule: recent in medicine → 2020-CURRENTYEAR).
- combined_blocks mirrors the three AND-blocks exactly. The intervention block merges controlled vocabulary from three concepts (thromboprophylaxis, antithrombotic medications, mechanical interventions), deduplicating "Anticoagulants" which appeared in two of them.

## Geographic and Setting Blocks — Critical Rule

When both setting_or_context and geography are present in the concept_graph:
- Create SEPARATE AND-blocks for each.
- Order: setting_or_context block first, then geography block.
- Example: "Mental health of internally displaced people in displacement camps in Ethiopia" produces 4 blocks:
  - Block 1: (mental health OR ...) [topic]
  - Block 2: (internally displaced persons OR ...) [population]
  - Block 3: (displacement camps OR IDP camps OR ...) [setting_or_context]
  - Block 4: (Ethiopia OR Qoloji OR ...) [geography]

- Named proper-noun locations (e.g., "Qoloji camp") appear as bare terms in the geography block; they have no synonyms or domain_terms.
- DO NOT merge setting and geography blocks with a single OR-group. This collapses the query hierarchy and treats "Ethiopia" as an alternative to "refugee camp" instead of a geographic constraint on camp types.

---

## Example 2 — Humanitarian Health (Setting and Geography Blocks, No Generic Intervention Block)

Input Statement:
"How to improve mental health and substance misuse outcomes in children under 5 and pregnant and lactating women in Qoloji camp, Ethiopia."

Concept Graph (from Agent B) simplified:
```
- mental health, substance misuse [topic_or_condition]
- children under 5, pregnant and lactating women [population_or_entity]
- humanitarian or refugee camp setting [setting_or_context]
- Qoloji camp, Ethiopia [geography — two separate concepts]
```

Output keyword.structured (AFTER mandatory wildcard application):

`(mental health OR psychological wellbeing OR substance misuse* OR substance use* OR substance abuse*) AND (children under five OR pregnant women OR lactating women OR pregnant and lactating women) AND (refugee camp* OR displacement camp* OR IDP camp* OR humanitarian setting*) AND (Qoloji OR Ethiopia)`

Key distinctions demonstrated:
- **No intervention block**: "how to improve" names no specific intervention. A block of generic verbs (treat*, improv*, support*, prevent*) would match almost every record yet still exclude studies that use other wording — omit it.
- **4 AND-blocks**: setting_or_context and geography are both explicitly stated, so each gets its own block (not merged).
- **Block 1 wildcards**: substance misuse* (covers: misuse, misused), substance use* (covers: use, used, using).
- **Proper nouns**: Qoloji, Ethiopia remain unwildcarded (no morphological variants).
- **Abbreviations**: IDP remains unwildcarded.

---

## Hard Rules
- Output exactly one JSON object. No preamble, explanation, markdown fences, or comments.
- Do NOT use double quotes inside keyword.structured — they break JSON encoding. Use bare terms only.
- domain_terms and colloquial must NOT appear in keyword.structured. They are reserved for search expansion levels.
- When geography and setting_or_context are both present, create separate AND-blocks in strict order: setting_or_context first, geography last. Never merge them into a single OR-block.
- MANDATORY: Apply truncation (word*) to content terms with productive morphological suffixes (e.g. misuse*, abuse*, rehabilitat*, vaccinat*). Never build a block from generic verbs alone (treat*, improv*, manag*, support*, prevent*).
- Prefer fewer blocks: when in doubt whether a concept should be a block, leave it out — the expansion stage can add precision, but recall lost to an unnecessary AND-block cannot be recovered.
- keyword.combined_blocks must mirror the top-level AND-blocks of keyword.structured one-to-one.
- Do not invent venues, authors, years, or publication types not stated in the inputs.
- Use empty values ("", [], {}) when evidence is insufficient — do not infer.
""".strip()

__all__ = ["SEARCH_CONSTRUCTION_TEMPLATE"]
