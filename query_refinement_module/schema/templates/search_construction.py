"""Agent D: Search Construction prompt template."""

SEARCH_CONSTRUCTION_TEMPLATE = """
# SEARCH CONSTRUCTION

## Role
Build the anchor retrieval artifacts from a normalized research statement and a structured concept graph.
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
  "grey_literature": {
    "broad_concepts": [],
    "organizational_terms": [],
    "geographic_variants": []
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

Block count and ordering:
- 4 blocks by default.
- 3 blocks only when fewer than 4 concepts are indispensable.
- 5 blocks only when a location, context, or factor forms a distinct indispensable concept absent from all other blocks.
- Order blocks by query_role: topic_or_condition first, then population_or_entity, then intervention_or_exposure_or_phenomenon, then setting_or_context or geography.

Building each block: for every concept in the block, include ONLY:
  true_synonyms + abbreviations + spelling_variants + lexical_variants

Do NOT use domain_terms or colloquial in keyword.structured — they cause scope creep.

Use uppercase Boolean operators: AND, OR, NOT.
Use parentheses only where they change scope or grouping.
Prefer exact phrases over free terms when equally precise.
Use truncation (word*) for morphological variants when appropriate.

## keyword.phrases

5–8 exact phrases, each 2–4 words.
Prefer phrases taken directly from the research_statement.
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

One entry per AND-block in keyword.structured, in the same order.

- role: the query_role of the dominant concept in this block (e.g. "topic_or_condition", "population_or_entity").
- free_text: every term in this block's OR-group — the same set used in keyword.structured for this block.
- controlled_vocabulary: a dict of vocabulary_name → deduplicated list of terms, merged from
  controlled_vocabulary_hints of every concept whose free-text terms appear in this block.
  Include only entries with confidence "high" or "medium". Use {} when no controlled vocabulary applies.

Source connectors use combined_blocks to build source-specific queries by ORing free_text terms with
controlled vocabulary terms within each block, then ANDing blocks together.

---

## grey_literature

Populate using the concept_graph:
- broad_concepts: colloquial terms from concept_graph entries for the primary subject and entity concepts.
- organizational_terms: institutional or organizational names if explicitly present in the research_statement.
- geographic_variants: colloquial or simplified geographic terms if present in concept_graph.colloquial.

Return null for grey_literature when colloquial and domain_terms are empty across all concepts.

---

## search_filters

### publication_years
Format: "YYYY-YYYY" or "".
- "recent" in health or medicine → "2020-CURRENTYEAR"
- "recent" in other fields → "2021-CURRENTYEAR"
- "last decade" → "DECADE_START-CURRENTYEAR"
- "since YYYY" → "YYYY-CURRENTYEAR"
Use only what is explicitly stated in research_statement or dimensions_specifications.

### venues
Return exact journal or conference names as stated. Otherwise [].

### authors
Return exact author names as stated. Otherwise [].

### publication_types
Populate only when a study design is explicitly stated in the research_statement or dimensions.
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

Research Statement: "Recent studies about venous thromboembolism prophylaxis in patients undergoing major orthopedic surgery (total hip replacement, knee replacement, hip fracture surgery), comparing thromboprophylaxis interventions including antithrombotic medications and mechanical interventions such as compression stockings within and across classes."

Concept Graph:
{
  "venous thromboembolism": {
    "query_role": "topic_or_condition",
    "true_synonyms": ["venous thrombosis", "thromboembolism"],
    "abbreviations": ["VTE"],
    "spelling_variants": [],
    "lexical_variants": ["thromboembolic"],
    "domain_terms": ["deep vein thrombosis", "pulmonary embolism"],
    "colloquial": ["blood clot"]
  },
  "major orthopedic surgery": {
    "query_role": "population_or_entity",
    "true_synonyms": ["major orthopedic procedures", "major orthopaedic procedures"],
    "abbreviations": [],
    "spelling_variants": ["major orthopaedic surgery"],
    "lexical_variants": [],
    "domain_terms": ["total hip replacement", "total knee replacement", "hip fracture surgery"],
    "colloquial": ["joint replacement surgery"]
  },
  "thromboprophylaxis": {
    "query_role": "intervention_or_exposure_or_phenomenon",
    "true_synonyms": ["VTE prophylaxis", "VTE prevention", "venous thromboembolism prevention"],
    "abbreviations": [],
    "lexical_variants": ["thromboprophylactic"],
    "domain_terms": ["anticoagulation", "antithrombotic therapy", "mechanical compression"],
    "colloquial": ["clot prevention"]
  },
  "antithrombotic medications": {
    "query_role": "intervention_or_exposure_or_phenomenon",
    "true_synonyms": ["antithrombotic agents", "antithrombotic therapy", "antithrombotic drugs"],
    "abbreviations": ["DOAC", "LMWH"],
    "domain_terms": ["aspirin", "heparin", "warfarin", "rivaroxaban", "apixaban"],
    "colloquial": ["blood thinners"]
  },
  "mechanical interventions": {
    "query_role": "intervention_or_exposure_or_phenomenon",
    "true_synonyms": ["mechanical prophylaxis", "physical prophylaxis", "mechanical preventive measures"],
    "abbreviations": ["GCS", "IPC"],
    "domain_terms": ["compression stockings", "intermittent pneumatic compression", "venous foot pump"],
    "colloquial": ["compression socks"]
  }
}

Output:

{
  "keyword": {
    "structured": "("venous thromboembolism" OR "venous thrombosis" OR thromboembolism OR VTE OR thromboembolic) AND ("major orthopedic surgery" OR "major orthopaedic surgery" OR "major orthopedic procedures" OR "major orthopaedic procedures") AND (thromboprophylaxis OR "VTE prophylaxis" OR "VTE prevention" OR "venous thromboembolism prevention" OR thromboprophylactic OR "antithrombotic medications" OR "antithrombotic agents" OR "antithrombotic therapy" OR DOAC OR LMWH OR "mechanical prophylaxis" OR "physical prophylaxis" OR GCS OR IPC)",
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
  "grey_literature": {
    "broad_concepts": ["blood clot", "clot prevention", "blood thinners", "compression socks", "joint replacement surgery"],
    "organizational_terms": [],
    "geographic_variants": []
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
- keyword.structured contains ONLY true_synonyms + abbreviations + spelling_variants + lexical_variants. Specific drugs (aspirin, heparin, warfarin, rivaroxaban) and devices (compression stockings, intermittent pneumatic compression) are domain_terms — they do NOT appear in the anchor Boolean query.
- grey_literature.broad_concepts is populated from colloquial fields across all concepts ("blood clot", "clot prevention", "blood thinners", "compression socks", "joint replacement surgery").
- Three AND-blocks are used (not four) because the comparison ("within and across classes") is a methodological specification with no distinct keyword representation.
- publication_years "2020-2026" derives from "recent studies" in medicine (rule: recent in medicine → 2020-CURRENTYEAR).
- combined_blocks mirrors the three AND-blocks exactly. The intervention block merges controlled vocabulary from three concepts (thromboprophylaxis, antithrombotic medications, mechanical interventions), deduplicating "Anticoagulants" which appeared in both. Source connectors use combined_blocks to build (free_text[0] OR free_text[1] OR ... OR MeSH_term[MeSH] OR ...) AND (...) queries for indexed databases.

---

## Hard Rules
- Output exactly one JSON object. No preamble, explanation, markdown fences, or comments.
- domain_terms and colloquial must NOT appear in keyword.structured.
- Do not invent venues, authors, years, or publication types not stated in the inputs.
- Use empty values ("", [], null) when evidence is insufficient — do not infer.
""".strip()

__all__ = ["SEARCH_CONSTRUCTION_TEMPLATE"]
