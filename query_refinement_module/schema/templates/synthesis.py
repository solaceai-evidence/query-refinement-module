"""
Synthesis template for generating final research outputs.

Contains the template for synthesizing clarified dimensions
into search-optimized queries and structured outputs.
"""

SYNTHESIS_TEMPLATE = """
# RESEARCH SYNTHESIS AND SEARCH OPTIMIZATION

## Role
Transform a user's research query into a structured, search-ready framework. Do not answer the research question — structure it for database discovery. Output ONLY valid JSON. No preamble, no markdown fencing.

## Input
1. **Original research query** — verbatim user input
2. **Clarified dimensions** — refined specifications (`[SKIPPED]` → `null`)

---

## Output Schema

{
  "integrated_statement": "",
  "dimensions_specifications": {},
  "search_optimized": {
    "semantic": "",
    "keyword": {
      "structured": "",
      "phrases": [],
      "terms": {"required": [], "optional": [], "excluded": []}
    },
    "research_elements": {
      "subject": "",
      "phenomenon": "",
      "context": "",
      "location": "",
      "comparator": "",
      "outcome": "",
      "perspective": ""
    }
  },
  "search_filters": {
    "publication_years": "",
    "venues": [],
    "authors": [],
    "publication_types": [],
    "fields_of_study": []
  },
  "terminology": {
    "synonyms": {},
    "hyponyms": {}
  }
}

---

## Field Specifications

### integrated_statement
Combine the original query with all non-null dimensions into a single, coherent statement.

Rules (in precedence order):
1. Dimension values override conflicting original query content
2. Expand abbreviations (T2DM → type 2 diabetes mellitus)
3. Correct typos; preserve the user's terminology and phrasing style
4. Remove filler phrases: "I think", "I want to study", "maybe", "um", "well"
5. Preserve format: question stays a question; statement stays a statement
6. Never add information not present in the input or dimensions
7. When most/all dimensions are `[SKIPPED]`: apply rules 1–6 to the original query alone; use `[]` for any filter where the value is uncertain

### dimensions_specifications
All dimension keys from the input, with their values. Set to `null` for `[SKIPPED]` dimensions.

### search_optimized.semantic
50–100 word natural language query for vector/embedding search.
- Convey conceptual content and research aims
- Include technical terminology with context
- Exclude temporal constraints, venue names, author names, and publication types
- Exception: retain temporal elements intrinsic to the research question (e.g., "longitudinal trends", "pre/post policy changes")

### search_optimized.keyword.structured
Boolean query: AND-connected concept blocks; OR-connected variants within blocks.

**Structure:** `(CONCEPT_A) AND (CONCEPT_B) AND (CONCEPT_C)`

Each concept block may combine these patterns as needed:
- Core term plus modifiers: `("term" AND (mod1 OR mod2))`
- Quoted multi-word phrases: `"complete phrase"`
- Abbreviations: `ABC`
- Wildcards: `term*`
- Exhaustive enumeration for interventions, drugs, devices, procedures, technologies, and named subpopulations — draw specific terms from `terminology.hyponyms` when populating these enumerations
- Compound variants: `((qual1 OR qual2) AND (term1 OR term2))`

Rules:
- Build 3-5 concept blocks covering the indispensable concepts in the query; usually subject/population, phenomenon/exposure/intervention, and condition/topic, plus setting/location/factor blocks only when they materially affect retrieval
- Within each block, include exact synonyms, abbreviations, lexical variants, and hyponyms needed for high recall
- Build each block from the integrated statement plus `terminology.synonyms` and `terminology.hyponyms`; standard database indexing variants and well-established abbreviations are allowed when they are conventional retrieval forms of the same concept
- It is acceptable to enumerate narrower procedures, devices, drugs, technologies, named subtypes, and named subpopulations when they are explicit in the integrated statement, supplied via `terminology.hyponyms`, or are standard retrieval variants of an explicitly stated concept
- For process concepts such as adoption, implementation, uptake, or diffusion, a small set of closely adjacent process terms may be included when they are standard retrieval variants used to capture the same literature; keep them tightly coupled to the stated concept and do not expand to the full project lifecycle
- For geographic concepts stated at a macro level (for example, a region or country group), named member countries or subregions may be included only when they are valid instances of the stated geography and are supplied through `terminology.hyponyms` or are standard retrieval expansions needed for database recall
- Do not introduce broader adjacent concepts, speculative expansions, or unrelated sibling concepts merely to increase recall; every term in a block must remain anchored to the same underlying concept
- Use the minimum terms needed for exhaustive recall within the stated scope; prefer specificity over padding
- Exclude years, venues, authors, and publication types (those belong in `search_filters`)

### search_optimized.keyword.phrases
5–10 exact phrases (2–4 words each) characteristic of the target literature.

Rules:
- Prefer phrases taken directly from `integrated_statement` or from established equivalents already represented in `terminology.synonyms`
- Use phrases that a relevant title, abstract, subject heading, or author keyword could plausibly contain verbatim
- Favor discriminative literature phrases over generic academic language
- Do not include full-sentence fragments, vague process labels, or phrases that merely restate a single-word keyword without added retrieval value
- Keep phrases anchored to the stated scope; do not add phrases that imply a broader population, setting, or domain than the query supports

### search_optimized.keyword.terms
- `required`: 2–5 core terms that must appear in every relevant result
- `optional`: 5–10 domain-specific terms that improve precision
- `excluded`: terms that signal out-of-scope population, setting, or domain

Rules:
- `required` terms should be the smallest set of lexical anchors whose absence would usually make a result irrelevant; prefer core concepts over broad context words
- `optional` terms should be precision-raising terms that are strongly associated with the target literature but are not mandatory in every relevant result
- `excluded` terms should remove clearly out-of-scope populations, settings, scales, or domains that are plausible retrieval confounders for the query
- Keep all terms concise; use single terms or short noun phrases rather than sentence fragments
- Do not repeat the same concept across `required` and `optional` using only trivial wording differences
- Do not include generic research words, publication-type words, years, venue names, or author names
- Do not use `excluded` to negate close variants of the target concept; use it only for genuinely out-of-scope content

### search_optimized.research_elements
Seven-component decomposition spanning PICO, PECO, SPICE, SPIDER, ECLIPSE, and CIC frameworks. Extract strictly from `integrated_statement`; do not infer content not present. Set to `""` when a component is absent, inapplicable, or indeterminate. Each non-empty value: concise verbatim-derived phrase of 10–30 words. Do not paraphrase beyond normalization.

| Field | Universal meaning | Clinical | Social Science | Engineering/CS | Humanities | Public Health |
|---|---|---|---|---|---|---|
| **subject** | Who or what is under study | Patient population | Community or group | System or algorithm | Text, period, or artifact | Target population |
| **phenomenon** | What is being examined, applied, or experienced | Intervention or exposure | Policy, program, or practice | Method or technique | Theme, event, or argument | Exposure or intervention |
| **context** | Operational or institutional environment | Clinical setting (ICU, ED, primary care) | Organizational or societal setting | Deployment environment or platform | Archival or cultural setting | Health system or community org |
| **location** | Physical or geopolitical place | Country, region, urban/rural | Country, region, or community | Country or deployment region | Historical location | Country, LMIC/HIC, urban/rural |
| **comparator** | Contrast, baseline, or alternative condition | Control or active comparator | Alternative condition | Baseline method | Contrasting tradition | Counterfactual or alternative |
| **outcome** | Measured or assessed result | Clinical endpoint | Social or behavioral result | Performance metric | Interpretive finding | Health or policy outcome |
| **perspective** | Whose viewpoint or intended recipient | Patient or clinician | Policymaker or community member | End-user or developer | Reader or historian | Patient, provider, or planner |

Leave `phenomenon` empty for purely descriptive or exploratory questions.
Leave `context` empty when no specific setting is mentioned.
Leave `location` empty when geography is not a dimension of the question.
Leave `comparator` empty when no comparison is involved.
Leave `outcome` empty for description, mapping, or theory-building questions.
Leave `perspective` empty when no specific audience or viewpoint is stated.

### search_filters.publication_years
Format: `"YYYY-YYYY"` or `""` if no temporal reference.
- "Recent" in health/medicine → `"2020-2026"`
- "Last decade" → `"2016-2026"`
- "Since YYYY" → `"YYYY-2026"`

### search_filters.venues
Array of journal or conference names exactly as stated. `[]` if none.

### search_filters.authors
Array of author names exactly as stated. `[]` if none.

### search_filters.publication_types
Populate only when a study design is explicitly stated in the query or dimensions. Return `[]` otherwise.

Permitted values only:
Before and after study | Case control study | Case report | Case series | Clinical study | Clinical trial | Cohort study | Comparative study | Consensus conference | Cross-sectional study | Diagnostic test accuracy study | Evaluation study | Government document | Guideline | Living review | Meta-analysis | Narrative review | Observational study | Pilot study | Policy document | Quality improvement study | Randomized controlled trial | Rapid review | Review | Scoping review | Systematic review | Validation study

### search_filters.fields_of_study
Populate with 1-3 values from the permitted list. Use a field when it is explicitly stated in the query or dimensions, or when it is directly and unambiguously entailed by the topic. Multi-label assignment is allowed when multiple disciplines are central to the query rather than merely adjacent. Return `[]` when the field requires interpretation, when the query is too general to anchor a discipline, or when plausible labels are only loosely related.

Rules:
- Prefer the smallest sufficient set of fields
- Include multiple fields only when each one is materially necessary to classify the literature being sought
- Treat this as coarse disciplinary classification, not topic tagging
- Do not add background or supporting disciplines unless the query explicitly studies them
- Do not use fields_of_study as a substitute for topic keywords, setting, audience, or method
- Do not exceed 3 fields; if more than 3 seem plausible, keep only the most central disciplines that a database indexer would assign
- When in doubt between one field and several, choose the narrower set

Permitted values only:
Agricultural and Food Sciences | Art | Biology | Business | Chemistry | Computer Science | Economics | Education | Engineering | Environmental Science | Geography | Geology | History | Law | Linguistics | Materials Science | Mathematics | Medicine | Philosophy | Physics | Political Science | Psychology | Public Health | Sociology

### terminology.synonyms
For up to 8 core concepts drawn from `integrated_statement`: provide 3–8 synonyms each. When more than 8 concepts are present, prioritise in this order: subject, phenomenon, comparator, outcome, then remaining concepts by centrality to the research question. Synonyms only — alternative terms at the same level of specificity as the concept, with materially the same denotation in retrieval contexts. Use lexical variants, spelling variants, standard abbreviations, and established equivalent phrasings. Do not include broader terms, narrower terms, neighboring process stages, components, exemplars, or loosely associated terms. Do not include hyponyms (those belong in `terminology.hyponyms`).

### terminology.hyponyms
For up to 8 core concepts drawn from `integrated_statement`: provide 3–8 specific instances, subtypes, or narrower terms that fall under each concept (i.e., "X is a type of concept"). Hyponyms must be true members of the parent concept, not merely related mechanisms, neighboring concepts, overlapping policy categories, or retrieval-adjacent terms. Prioritise concepts whose hyponym expansion materially affects recall: interventions, exposures, technologies, populations, settings, and geographies. For geographic concepts, valid members of a stated region or country group may be used as hyponyms when they are concrete instances of the stated geography. These terms directly populate exhaustive enumerations in `keyword.structured` concept blocks — ensure completeness for any concept that would otherwise require a wildcard alone.

---

## Example 1 - Medicine Domain

**Input 1 (Original query):**
"I am interested in recent studies about venous thromboembolism prophylaxis in patients undergoing major orthopedic surgery"

**Input 2 (Clarified dimensions):**
- Population: "Patients undergoing major orthopedic surgery (total hip replacement, knee replacement, hip fracture surgery)"
- Intervention: "Thromboprophylaxis interventions including antithrombotic medications and mechanical interventions such as compression stockings"
- Comparison: "Within and across classes (comparing interventions both within the same class and between different classes)"
- Outcomes: [SKIPPED]

**Output:**

{
  "integrated_statement": "Recent studies about venous thromboembolism prophylaxis in patients undergoing major orthopedic surgery (total hip replacement, knee replacement, hip fracture surgery), comparing thromboprophylaxis interventions including antithrombotic medications and mechanical interventions such as compression stockings within and across classes",
  "dimensions_specifications": {
    "population": "Patients undergoing major orthopedic surgery (total hip replacement, knee replacement, hip fracture surgery)",
    "intervention": "Thromboprophylaxis interventions including antithrombotic medications and mechanical interventions such as compression stockings",
    "comparator": "Within and across classes (comparing interventions both within the same class and between different classes)",
    "outcomes": null
  },
  "search_optimized": {
    "semantic": "Studies comparing thromboprophylaxis interventions for venous thromboembolism prevention in patients undergoing major orthopedic surgery including total hip replacement, total knee replacement, and hip fracture surgery, examining antithrombotic medications such as low molecular weight heparins, direct oral anticoagulants, and antiplatelet agents alongside mechanical interventions including compression stockings and intermittent pneumatic compression devices, comparing effectiveness and safety both within intervention classes and across different prophylaxis approaches",
    "keyword": {
      "structured": "((\"arthroplasty\" AND (knee OR hip)) OR \"total knee replacement\" OR \"knee arthroplasty\" OR tkr OR knee prosthesis OR knee joint OR total hip replacement OR hip arthroplasty OR thr OR Hip Prosthesis OR hip fracture surgery OR hfs OR (arthroscop* AND (knee OR meniscectomy OR synovectomy OR cruciate ligament))) AND (\"pulmonary embol*\" OR \"pulmonary thromboembol*\" OR PE OR \"deep vein thrombos*\" OR \"deep venous thrombos*\" OR \"deep venous thromboembol*\" OR \"deep vein thromboembol*\" OR DVT OR \"venous thromboembol*\" OR VTE OR \"venous thrombos*\" OR clot) AND (aspirin OR clopidogrel OR ticlopidine OR prasugrel OR heparin OR UFH OR LMWH OR enoxaparin OR dalteparin OR nadroparin OR ardeparin OR bemiparin OR certoparin OR parnaparin OR reviparin OR tinzaparin OR danaparoid OR fondaparinux OR idraparinux OR rivaroxaban OR apixaban OR enoxaparin OR desirudin OR argatroban OR bivalirudin OR lepirudin OR dabigatran OR warfarin OR acenocoumarol OR dicoumarol OR dextran sulfate OR ((compression or elastic) and (stocking* or boot*)) OR GCS OR venous foot pump OR VFP OR \"pneumatic compression\" OR \"pneumatic hose\" OR pneumatic compression hose OR \"vena cava filter*\" OR \"factor xa inhibitors\")",
      "phrases": ["venous thromboembolism prophylaxis", "major orthopedic surgery", "total hip replacement", "total knee replacement", "compression stockings", "antithrombotic medications", "mechanical prophylaxis", "thromboprophylaxis interventions"],
      "terms": {
        "required": ["venous thromboembolism", "prophylaxis"],
        "optional": ["LMWH", "DOAC", "compression stockings", "mechanical prophylaxis", "intermittent pneumatic compression", "hip fracture surgery"],
        "excluded": ["pediatric", "trauma", "spine surgery", "upper extremity"]
      }
    },
    "research_elements": {
      "subject": "Patients undergoing major orthopedic surgery (total hip replacement, knee replacement, hip fracture surgery)",
      "phenomenon": "Thromboprophylaxis interventions including antithrombotic medications and mechanical interventions such as compression stockings",
      "context": "",
      "location": "",
      "comparator": "Within and across intervention classes (same-class and cross-class comparisons)",
      "outcome": "",
      "perspective": ""
    }
  },
  "search_filters": {
    "publication_years": "2020-2026",
    "venues": [],
    "authors": [],
    "publication_types": [],
    "fields_of_study": ["Medicine"]
  },
  "terminology": {
    "synonyms": {
      "venous thromboembolism": ["VTE", "venous thrombosis", "thromboembolic disease", "thromboembolism"],
      "prophylaxis": ["prevention", "thromboprophylaxis", "preventive therapy", "preventive measures"],
      "major orthopedic surgery": ["major orthopaedic surgery", "major orthopedic procedures", "major orthopaedic procedures"],
      "total hip replacement": ["total hip arthroplasty", "THR", "THA", "hip prosthesis implantation"],
      "total knee replacement": ["total knee arthroplasty", "TKR", "TKA", "knee prosthesis implantation"],
      "antithrombotic medications": ["antithrombotic agents", "antithrombotic therapy", "antithrombotic drugs", "antithrombotic treatment"],
      "compression stockings": ["graduated compression stockings", "GCS", "elastic stockings", "compression hosiery"],
      "mechanical interventions": ["mechanical prophylaxis", "physical prophylaxis", "mechanical preventive measures"]
    },
    "hyponyms": {
      "venous thromboembolism": ["deep vein thrombosis", "DVT", "pulmonary embolism", "PE", "proximal DVT", "distal DVT"],
      "major orthopedic surgery": ["total hip replacement", "total knee replacement", "hip fracture surgery", "hip arthroplasty", "knee arthroplasty"],
      "antithrombotic medications": ["anticoagulants", "antiplatelet drugs", "low molecular weight heparins", "direct oral anticoagulants", "vitamin K antagonists", "LMWH", "DOAC"],
      "mechanical interventions": ["compression stockings", "intermittent pneumatic compression", "venous foot pumps", "anti-embolism stockings", "graduated compression sleeves"]
    }
  }
}

---

## Example 2 - Technology/Social Science Domain

**Input 1 (Original query):**
"What factors influence the adoption of renewable energy technologies in developing countries?"

**Input 2 (Clarified dimensions):**
- Technology Type: "Solar photovoltaic systems, wind turbines, and small-scale hydroelectric installations"
- Geographic Context: "Low and middle-income countries in Sub-Saharan Africa and South Asia"
- Factors: "Economic barriers, policy frameworks, infrastructure availability, cultural acceptance, and financing mechanisms"
- Target Adopters: "Rural households, smallholder farmers, and local enterprises"
- Deployment Context: "Off-grid and rural electrification programs"
- Intended For: "Energy policymakers and development aid organizations"
- Temporal Scope: "Studies from 2015 onwards"

**Output:**

{
  "integrated_statement": "What economic barriers, policy frameworks, infrastructure availability, cultural acceptance, and financing mechanisms influence the adoption of solar photovoltaic systems, wind turbines, and small-scale hydroelectric installations among rural households, smallholder farmers, and local enterprises in off-grid and rural electrification programs in low and middle-income countries in Sub-Saharan Africa and South Asia, based on studies from 2015 onwards, for use by energy policymakers and development aid organizations",
  "dimensions_specifications": {
    "technology_type": "Solar photovoltaic systems, wind turbines, and small-scale hydroelectric installations",
    "geographic_context": "Low and middle-income countries in Sub-Saharan Africa and South Asia",
    "factors": "Economic barriers, policy frameworks, infrastructure availability, cultural acceptance, and financing mechanisms",
    "target_adopters": "Rural households, smallholder farmers, and local enterprises",
    "deployment_context": "Off-grid and rural electrification programs",
    "intended_for": "Energy policymakers and development aid organizations",
    "temporal_scope": "Studies from 2015 onwards"
  },
  "search_optimized": {
    "semantic": "Research examining economic barriers, policy frameworks, infrastructure availability, cultural acceptance, and financing mechanisms that influence adoption of renewable energy technologies including solar photovoltaic systems, wind turbines, and small-scale hydroelectric installations among rural households, smallholder farmers, and local enterprises in off-grid and rural electrification programs across low and middle-income countries in Sub-Saharan Africa and South Asia, focusing on barriers and enablers to technology deployment, community acceptance, regulatory environments, and financial models that facilitate or hinder uptake, intended for energy policymakers and development aid organizations",
    "keyword": {
      "structured": "((\"solar photovoltaic*\" OR \"solar PV\" OR \"solar panel*\" OR \"solar energy\" OR \"solar power\") OR (\"wind turbine*\" OR \"wind energy\" OR \"wind power\" OR \"wind farm*\") OR (\"small-scale hydroelectric\" OR \"micro-hydro*\" OR \"mini-hydro*\" OR hydropower OR \"hydroelectric power\")) AND ((\"renewable energy\" OR \"clean energy\" OR \"green energy\" OR \"sustainable energy\" OR \"alternative energy\") AND (adoption OR uptake OR implementation OR deployment OR diffusion)) AND ((\"low and middle-income countr*\" OR \"low-income countr*\" OR \"middle-income countr*\" OR LMIC OR \"Sub-Saharan Africa\" OR \"South Asia\") OR (Kenya OR Tanzania OR Uganda OR Ethiopia OR India OR Bangladesh OR Pakistan OR Nepal)) AND (\"economic barrier*\" OR affordability OR cost OR pricing OR \"financial constraint*\" OR subsid* OR incentive* OR \"policy framework*\" OR regulation* OR governance OR legislation OR infrastructure OR grid OR \"energy access\" OR \"cultural acceptance\" OR \"social acceptance\" OR \"community acceptance\" OR perception* OR \"financing mechanism*\" OR investment OR \"business model*\" OR microfinance)",
      "phrases": [
        "renewable energy adoption",
        "low and middle-income countries",
        "solar photovoltaic systems",
        "wind turbines",
        "economic barriers",
        "policy frameworks",
        "Sub-Saharan Africa",
        "rural electrification programs"
      ],
      "terms": {
        "required": ["renewable energy", "adoption"],
        "optional": ["solar photovoltaic", "wind turbines", "small-scale hydroelectric", "financing mechanisms", "policy frameworks", "Sub-Saharan Africa", "South Asia", "rural households", "smallholder farmers", "off-grid electrification"],
        "excluded": ["developed countries", "high-income", "OECD", "industrial scale", "large-scale", "fossil fuel"]
      }
    },
    "research_elements": {
      "subject": "Rural households, smallholder farmers, and local enterprises",
      "phenomenon": "Economic barriers, policy frameworks, infrastructure availability, cultural acceptance, and financing mechanisms influencing renewable energy adoption",
      "context": "Off-grid and rural electrification programs",
      "location": "Low and middle-income countries in Sub-Saharan Africa and South Asia",
      "comparator": "",
      "outcome": "",
      "perspective": "Energy policymakers and development aid organizations"
    }
  },
  "search_filters": {
    "publication_years": "2015-2026",
    "venues": [],
    "authors": [],
    "publication_types": [],
    "fields_of_study": ["Environmental Science", "Engineering", "Economics"]
  },
  "terminology": {
    "synonyms": {
      "renewable energy": ["clean energy", "sustainable energy", "green energy", "alternative energy"],
      "adoption": ["uptake", "take-up", "technology uptake", "acceptance and uptake"],
      "low and middle-income countries": ["LMIC", "LMICs", "low- and middle-income countries", "lower- and middle-income countries"],
      "solar photovoltaic": ["solar PV", "photovoltaic systems", "PV systems", "solar photovoltaic systems"],
      "economic barriers": ["financial barriers", "cost barriers", "affordability constraints", "economic constraints"],
      "policy frameworks": ["regulatory frameworks", "policy environments", "governance structures", "legislative frameworks"],
      "infrastructure": ["energy infrastructure", "grid infrastructure", "power infrastructure", "energy access infrastructure"],
      "cultural acceptance": ["social acceptance", "community acceptance", "public acceptance", "societal acceptance"]
    },
    "hyponyms": {
      "renewable energy technologies": ["solar photovoltaic systems", "wind turbines", "small-scale hydroelectric installations", "solar home systems", "micro-wind turbines", "run-of-river hydro"],
      "adoption": ["implementation", "deployment", "diffusion"],
      "economic barriers": ["upfront capital costs", "credit access constraints", "affordability gaps", "financing gaps", "high import tariffs", "currency risk"],
      "policy frameworks": ["feed-in tariffs", "net metering policies", "renewable energy subsidies", "rural electrification mandates", "energy access legislation", "tax incentives"],
      "low and middle-income countries in Sub-Saharan Africa and South Asia": ["Kenya", "Tanzania", "Uganda", "Ethiopia", "India", "Bangladesh", "Pakistan", "Nepal"]
    }
  }
}
---

## Hard Rules
- Output only the JSON object — no text before or after, no markdown code blocks
- Valid JSON only: escape internal quotes (\"), no trailing commas
- All dimension keys must appear in `dimensions_specifications` (`null` for `[SKIPPED]`)
- `publication_types` and `fields_of_study` must use only values from the permitted lists above
"""
