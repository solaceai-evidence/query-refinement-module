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
      "focus": "",
      "comparator": "",
      "outcome": ""
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
    "colloquial": []
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

Each concept block must include:
- Core term plus modifiers: `("term" AND (mod1 OR mod2))`
- Quoted multi-word phrases: `"complete phrase"`
- Abbreviations: `ABC`
- Wildcards: `term*`
- Exhaustive enumeration for interventions, drugs, devices, and procedures
- Compound variants: `((qual1 OR qual2) AND (term1 OR term2))`

Rules:
- Use the minimum terms needed for exhaustive recall; prefer specificity over padding
- Exclude years, venues, authors, and publication types (those belong in `search_filters`)

### search_optimized.keyword.phrases
5–10 exact phrases (2–4 words each) characteristic of the target literature.

### search_optimized.keyword.terms
- `required`: 2–5 core terms that must appear in every relevant result
- `optional`: 5–10 domain-specific terms that improve precision
- `excluded`: terms that signal out-of-scope population, setting, or domain

### search_optimized.research_elements
Four-component decomposition equivalent to PICO. Extract strictly from `integrated_statement`; do not infer content not present. Set to `""` when a component is absent, inapplicable, or indeterminate. Each non-empty value: concise verbatim-derived phrase of 10–30 words. Do not paraphrase beyond normalization.

| Field | Universal meaning | Clinical | Social Science | Engineering/CS | Humanities |
|---|---|---|---|---|---|
| **subject** | Who or what is under study | Population | Community or phenomenon | System or algorithm | Period, text, or artifact |
| **focus** | Variable, action, or phenomenon examined | Intervention/Exposure | Policy, program, or factor | Method or approach | Theme or argument |
| **comparator** | Contrast, baseline, or alternative condition | Control | Alternative condition | Baseline method | Contrasting tradition |
| **outcome** | Measured or assessed result | Clinical endpoint | Social/behavioral result | Performance metric | Interpretive finding |

Leave `focus` empty for purely descriptive or exploratory questions.
Leave `comparator` empty when no comparison is involved.
Leave `outcome` empty for description, mapping, or theory-building questions.

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
Populate when explicitly stated in the query or dimensions, or when the domain is unambiguous from context (e.g., a query about clinical trials and drug efficacy → Medicine; a query about machine learning model architectures → Computer Science). Return `[]` when the field requires interpretation or is genuinely cross-disciplinary without a clear primary domain.

Permitted values only:
Agricultural and Food Sciences | Art | Biology | Business | Chemistry | Computer Science | Economics | Education | Engineering | Environmental Science | Geography | Geology | History | Law | Linguistics | Materials Science | Mathematics | Medicine | Philosophy | Physics | Political Science | Psychology | Public Health | Sociology

### terminology.synonyms
For up to 8 core concepts drawn from `integrated_statement`: provide 3–8 synonyms each. When more than 8 concepts are present, prioritise in this order: subject, focus, comparator, outcome, then remaining concepts by centrality to the research question. Synonyms only — alternative terms for the same concept. Do not include hyponyms (specific instances of the concept).

### terminology.colloquial
3-6 plain-language phrases that a non-academic audience would use for this topic.

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
        "required": ["arthroplasty", "venous thromboembolism", "prophylaxis"],
        "optional": ["LMWH", "DOAC", "compression stockings","mechanical prophylaxis", "anticoagulant", "postoperative care","rehabilitation"],
        "excluded": ["pediatric", "trauma", "spine surgery", "upper extremity"]
      }
    },
    "research_elements": {
      "subject": "Patients undergoing major orthopedic surgery (total hip replacement, knee replacement, hip fracture surgery)",
      "focus": "Thromboprophylaxis interventions including antithrombotic medications and mechanical interventions such as compression stockings",
      "comparator": "Within and across intervention classes (same-class and cross-class comparisons)",
      "outcome": ""
    }
  },
  "search_filters": {
    "publication_years": "2020-2026",
    "venues": [],
    "authors": [],
    "publication_types": ["Comparative study"],
    "fields_of_study": ["Medicine"]
  },
  "terminology": {
    "synonyms": {
      "venous thromboembolism": ["VTE", "venous thrombosis", "thromboembolic disease", "blood clots"],
      "prophylaxis": ["prevention", "thromboprophylaxis", "preventive therapy", "preventive measures"],
      "major orthopedic surgery": ["joint replacement surgery", "arthroplasty", "orthopedic procedures"],
      "total hip replacement": ["total hip arthroplasty", "THR", "THA", "hip prosthesis"],
      "total knee replacement": ["total knee arthroplasty", "TKR", "TKA", "knee prosthesis"],
      "antithrombotic medications": ["anticoagulants", "blood thinners", "antithrombotic agents", "antiplatelet drugs"],
      "compression stockings": ["graduated compression stockings", "GCS", "elastic stockings", "compression devices"],
      "mechanical interventions": ["mechanical prophylaxis", "physical methods", "compression therapy", "intermittent pneumatic compression"]
    },
    "colloquial": ["preventing blood clots after hip or knee surgery",
  "blood clot prevention for joint replacement patients",
  "blood thinners versus compression stockings after surgery",
  "DVT prevention after orthopedic surgery"]
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
- Temporal Scope: "Studies from 2015 onwards"

**Output:**

{
  "integrated_statement": "What economic barriers, policy frameworks, infrastructure availability, cultural acceptance, and financing mechanisms influence the adoption of solar photovoltaic systems, wind turbines, and small-scale hydroelectric installations in low and middle-income countries in Sub-Saharan Africa and South Asia, based on studies from 2015 onwards",
  "dimensions_specifications": {
    "technology_type": "Solar photovoltaic systems, wind turbines, and small-scale hydroelectric installations",
    "geographic_context": "Low and middle-income countries in Sub-Saharan Africa and South Asia",
    "factors": "Economic barriers, policy frameworks, infrastructure availability, cultural acceptance, and financing mechanisms",
    "temporal_scope": "Studies from 2015 onwards"
  },
  "search_optimized": {
    "semantic": "Research examining economic barriers, policy frameworks, infrastructure availability, cultural acceptance, and financing mechanisms that influence adoption of renewable energy technologies including solar photovoltaic systems, wind turbines, and small-scale hydroelectric installations in low and middle-income countries across Sub-Saharan Africa and South Asia, focusing on barriers and enablers to technology deployment, community acceptance, regulatory environments, and financial models that facilitate or hinder renewable energy uptake in resource-constrained settings",
    "keyword": {
      "structured": "((\"solar photovoltaic*\" OR \"solar PV\" OR \"solar panel*\" OR \"solar energy\" OR \"solar power\") OR (\"wind turbine*\" OR \"wind energy\" OR \"wind power\" OR \"wind farm*\") OR (\"small-scale hydroelectric\" OR \"micro-hydro*\" OR \"mini-hydro*\" OR hydropower OR \"hydroelectric power\")) AND ((\"renewable energy\" OR \"clean energy\" OR \"green energy\" OR \"sustainable energy\" OR \"alternative energy\") AND (adoption OR uptake OR deployment OR implementation OR diffusion OR dissemination OR \"technology transfer\")) AND ((\"developing countr*\" OR \"low-income countr*\" OR \"middle-income countr*\" OR LMIC OR \"Global South\" OR \"Sub-Saharan Africa\" OR \"South Asia\" OR \"emerging econom*\") OR (Kenya OR Tanzania OR Uganda OR Ethiopia OR Nigeria OR Ghana OR India OR Bangladesh OR Pakistan OR Nepal)) AND (\"economic barrier*\" OR affordability OR cost OR pricing OR \"financial constraint*\" OR subsid* OR incentive* OR \"policy framework*\" OR regulation* OR governance OR legislation OR infrastructure OR grid OR \"energy access\" OR \"cultural acceptance\" OR \"social acceptance\" OR \"community acceptance\" OR perception* OR \"financing mechanism*\" OR investment OR \"business model*\" OR microfinance)",
      "phrases": [
        "renewable energy adoption",
        "developing countries",
        "solar photovoltaic systems",
        "wind turbines",
        "economic barriers",
        "policy frameworks",
        "Sub-Saharan Africa",
        "technology deployment"
      ],
      "terms": {
        "required": ["renewable energy", "adoption", "developing countries"],
        "optional": ["solar", "wind", "hydroelectric", "policy", "infrastructure", "financing", "barriers", "Sub-Saharan Africa", "South Asia"],
        "excluded": ["developed countries", "high-income", "OECD", "industrial scale", "large-scale", "fossil fuel"]
      }
    },
    "research_elements": {
      "subject": "Low and middle-income countries in Sub-Saharan Africa and South Asia",
      "focus": "Economic barriers, policy frameworks, infrastructure availability, cultural acceptance, and financing mechanisms influencing renewable energy adoption",
      "comparator": "",
      "outcome": ""
    }
  },
  "search_filters": {
    "publication_years": "2015-2026",
    "venues": [],
    "authors": [],
    "publication_types": [],
    "fields_of_study": ["Environmental Science", "Engineering", "Economics", "Sociology"]
  },
  "terminology": {
    "synonyms": {
      "renewable energy": ["clean energy", "sustainable energy", "green energy", "alternative energy"],
      "adoption": ["uptake", "deployment", "implementation", "diffusion", "dissemination"],
      "developing countries": ["low-income countries", "middle-income countries", "LMIC", "Global South", "emerging economies"],
      "solar photovoltaic": ["solar PV", "solar panels", "photovoltaic systems", "PV technology"],
      "economic barriers": ["financial barriers", "cost barriers", "affordability constraints", "economic constraints"],
      "policy frameworks": ["regulatory frameworks", "policy environments", "governance structures", "legislative frameworks"],
      "infrastructure": ["energy infrastructure", "grid infrastructure", "distribution networks", "transmission systems"],
      "cultural acceptance": ["social acceptance", "community acceptance", "public acceptance", "societal acceptance"]
    },
    "colloquial": [
      "why people in poor countries don't use solar panels",
      "barriers to wind and solar power in Africa and Asia",
      "what stops renewable energy adoption in developing nations",
      "making clean energy accessible in low-income countries"
    ]
  }
}
---

## Hard Rules
- Output only the JSON object — no text before or after, no markdown code blocks
- Valid JSON only: escape internal quotes (\"), no trailing commas
- All dimension keys must appear in `dimensions_specifications` (`null` for `[SKIPPED]`)
- `publication_types` and `fields_of_study` must use only values from the permitted lists above
"""
