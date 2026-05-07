"""
Synthesis template for generating final research outputs.

Contains the template for synthesizing clarified dimensions
into search-optimized queries and structured outputs.
"""

SYNTHESIS_TEMPLATE = """
# RESEARCH SYNTHESIS AND SEARCH OPTIMIZATION

## Role
Convert the user's research query into a structured, search-ready specification for literature retrieval. Do not answer the research question. Return exactly one valid JSON object and no other text.

## Inputs
1. Original research query: verbatim user input.
2. Clarified dimensions: refined specifications. Treat `[SKIPPED]` as `null` in the output.

---

## General Rules
1. Use only information stated in the original query or clarified dimensions.
2. If a value is unsupported or uncertain, leave it empty: use `""`, `[]`, `{}`, or `null` as required by the schema.
3. Explicit dimension values override conflicting content in the original query.
4. Do not infer unstated facts, outcomes, methods, populations, geographies, or disciplines.
5. Deduplicate all arrays and term lists.
6. Preserve a formal, neutral, technical register.
7. Use the smallest sufficient output that preserves retrieval quality.
8. When multiple compliant outputs are possible, choose the shortest formal wording that preserves meaning.
9. Preserve the schema field order shown below. Preserve input dimension-key order in `dimensions_specifications`.

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
    "primary_terms": [],
    "synonyms": {},
    "domain_specific": [],
    "colloquial": []
  }
}

---

## Field Specifications

### integrated_statement
Write one coherent sentence that integrates the original query with all non-null dimensions.

Rules in precedence order:
1. Dimension values override conflicting original-query content.
2. Expand abbreviations on first use when the expansion is certain; retain both forms as `full form (ABBR)` — do not drop either the expansion or the abbreviation.
3. Correct obvious typos.
4. Remove filler language such as "I think", "I want to study", "maybe", "um", and "well".
5. Preserve sentence mode: a question remains a question; a statement remains a statement.
6. Do not add content not present in the inputs.
7. If all dimensions are `[SKIPPED]`, normalize the original query alone.

### dimensions_specifications
Include every dimension key from the input exactly once, in input order. Use the provided value, or `null` when the input value is `[SKIPPED]`.

### search_optimized.semantic
Write one natural-language query of 50-90 words for semantic or embedding search.

Rules:
- State the core subject, phenomenon, and scope.
- Include technical terminology needed for retrieval.
- Exclude years, venues, authors, and publication types.
- Keep temporal content only when it is intrinsic to the research question itself.
- Use one sentence.
- Prefer 60-75 words unless the inputs require a shorter or longer statement within the allowed range.

### search_optimized.keyword.structured
Write one Boolean query with AND-connected concept blocks and OR-connected variants within blocks.

Default block count and ordering:
- Use exactly 4 blocks by default.
- Use 3 blocks only when fewer than 4 concepts are indispensable.
- Use 5 blocks only when location, context, or factor terms form a distinct indispensable concept absent from all other blocks.
- Order blocks as: subject/population, phenomenon/exposure/intervention, condition/topic, then context/location/factors if needed.
- Use uppercase Boolean operators: `AND`, `OR`, and `NOT`.
- Use parentheses only where they change scope or grouping.

Allowed block patterns:
- `("term" AND (mod1 OR mod2))`
- `"complete phrase"`
- `ABC`
- `term*`
- `((qual1 OR qual2) AND (term1 OR term2))`

Rules:
- Build blocks from `integrated_statement`, `terminology.synonyms`, and explicit terminology already supported by the inputs.
- Within each block, include only terms anchored to the same concept.
- Include exact synonyms, established abbreviations, spelling variants, and lexical variants.
- Enumerate narrower drugs, devices, procedures, technologies, subtypes, subpopulations, or geographic members only when they are explicit in the input or are standard retrieval variants of the same concept.
- For process concepts such as adoption, implementation, uptake, or diffusion, include only closely adjacent retrieval variants of that same process.
- Exclude years, venues, authors, and publication types.
- Do not include a term unless it is anchored to a concept present in `integrated_statement`.
- Prefer exact phrases over free terms when both are equally precise.

### search_optimized.keyword.phrases
Return 5-8 exact phrases, each 2-4 words.

Rules:
- Prefer phrases taken directly from `integrated_statement`.
- Otherwise use established equivalents already represented in `terminology.synonyms`.
- Use phrases that could plausibly appear verbatim in a relevant title, abstract, subject heading, or author keyword.
- Exclude vague academic language, full-sentence fragments, and phrases that broaden the stated scope.
- Use 5 phrases by default. Use more only when each additional phrase adds distinct retrieval value.

### search_optimized.keyword.terms
- `required`: 2-4 core lexical anchors.
- `optional`: 5-8 precision-raising terms.
- `excluded`: only clearly out-of-scope populations, settings, scales, or domains.

Rules:
- `required` terms are the smallest set whose absence makes a result irrelevant.
- `optional` terms improve precision but are not mandatory in every relevant result.
- `excluded` terms must remove true confounders, not close variants of the target concept.
- Each term must be a single word or two-word compound.
- Do not repeat the same concept across `required` and `optional` with trivial wording changes.
- Do not include years, venue names, author names, publication-type labels, or generic research words.
- Use 3 `required` terms by default when the topic supports them.
- Use 5 `optional` terms by default.
- Use `excluded` only when clear confounders are present; otherwise return `[]`.

### search_filters.publication_years
Format: `"YYYY-YYYY"` or `""`.
- "Recent" in health or medicine -> `"2020-2026"`
- "Recent" in all other disciplines -> `"2021-2026"`
- "Last decade" -> `"2016-2026"`
- "Since YYYY" -> `"YYYY-2026"`

### search_filters.venues
Return journal or conference names exactly as stated. Otherwise return `[]`.

### search_filters.authors
Return author names exactly as stated. Otherwise return `[]`.

### search_filters.publication_types
Populate only when a study design is explicitly stated in the query or dimensions. Otherwise return `[]`.

Permitted values only:
Before and after study | Case control study | Case report | Case series | Clinical study | Clinical trial | Cohort study | Comparative study | Consensus conference | Cross-sectional study | Diagnostic test accuracy study | Evaluation study | Government document | Guideline | Living review | Meta-analysis | Narrative review | Observational study | Pilot study | Policy document | Quality improvement study | Randomized controlled trial | Rapid review | Review | Scoping review | Systematic review | Validation study

### search_filters.fields_of_study
Return 1-3 values only when the field is explicit or directly and unambiguously entailed by the topic. Otherwise return `[]`.

Rules:
- Use the smallest sufficient set.
- Include multiple fields only when each field is central to the literature being sought.
- Treat this as coarse disciplinary classification, not topic tagging.
- Do not use `fields_of_study` to encode methods, audiences, settings, or keywords.
- If classification requires interpretation rather than clear entailment, return `[]`.
- Use 1 field by default. Use 2 or 3 only when each additional field is independently indispensable.

Permitted values only:
Agricultural and Food Sciences | Art | Biology | Business | Chemistry | Computer Science | Economics | Education | Engineering | Environmental Science | Geography | Geology | History | Law | Linguistics | Materials Science | Mathematics | Medicine | Philosophy | Physics | Political Science | Psychology | Public Health | Sociology

### terminology.synonyms
For up to 8 core concepts from `integrated_statement`, provide 3-8 synonyms each. Prioritize, in order: subject, phenomenon, comparator, outcome, then remaining concepts by centrality.

Rules:
- Include only same-level equivalents: lexical variants, spelling variants, established abbreviations, and equivalent phrasings.
- Do not include broader terms, narrower terms, exemplars, components, neighboring process stages, or loosely associated terms.
- Keep `primary_terms`, `domain_specific`, and `colloquial` optional; use them only when clearly supported by the input and useful for retrieval.
- Use 3 synonyms per concept by default. Add more only when each additional synonym is a genuine retrieval variant.

---

## Example 1 - Medicine

Input 1:
"I am interested in recent studies about venous thromboembolism prophylaxis in patients undergoing major orthopedic surgery"

Input 2:
- Population: "Patients undergoing major orthopedic surgery (total hip replacement, knee replacement, hip fracture surgery)"
- Intervention: "Thromboprophylaxis interventions including antithrombotic medications and mechanical interventions such as compression stockings"
- Comparison: "Within and across classes (comparing interventions both within the same class and between different classes)"
- Outcomes: [SKIPPED]

Output:

{
  "integrated_statement": "Recent studies about venous thromboembolism prophylaxis in patients undergoing major orthopedic surgery (total hip replacement, knee replacement, hip fracture surgery), comparing thromboprophylaxis interventions including antithrombotic medications and mechanical interventions such as compression stockings within and across classes",
  "dimensions_specifications": {
    "population": "Patients undergoing major orthopedic surgery (total hip replacement, knee replacement, hip fracture surgery)",
    "intervention": "Thromboprophylaxis interventions including antithrombotic medications and mechanical interventions such as compression stockings",
    "comparator": "Within and across classes (comparing interventions both within the same class and between different classes)",
    "outcomes": null
  },
  "search_optimized": {
    "semantic": "Studies comparing venous thromboembolism prophylaxis interventions in patients undergoing major orthopedic surgery, including total hip replacement, total knee replacement, and hip fracture surgery, with emphasis on antithrombotic medications and mechanical prophylaxis such as compression stockings and intermittent pneumatic compression devices, comparing approaches within and across intervention classes.",
    "keyword": {
      "structured": "((\"arthroplasty\" AND (knee OR hip)) OR \"total knee replacement\" OR \"knee arthroplasty\" OR tkr OR knee prosthesis OR knee joint OR total hip replacement OR hip arthroplasty OR thr OR Hip Prosthesis OR hip fracture surgery OR hfs OR (arthroscop* AND (knee OR meniscectomy OR synovectomy OR cruciate ligament))) AND (\"pulmonary embol*\" OR \"pulmonary thromboembol*\" OR PE OR \"deep vein thrombos*\" OR \"deep venous thrombos*\" OR \"deep venous thromboembol*\" OR \"deep vein thromboembol*\" OR DVT OR \"venous thromboembol*\" OR VTE OR \"venous thrombos*\" OR clot) AND (aspirin OR clopidogrel OR ticlopidine OR prasugrel OR heparin OR UFH OR LMWH OR enoxaparin OR dalteparin OR nadroparin OR ardeparin OR bemiparin OR certoparin OR parnaparin OR reviparin OR tinzaparin OR danaparoid OR fondaparinux OR idraparinux OR rivaroxaban OR apixaban OR enoxaparin OR desirudin OR argatroban OR bivalirudin OR lepirudin OR dabigatran OR warfarin OR acenocoumarol OR dicoumarol OR dextran sulfate OR ((compression or elastic) and (stocking* or boot*)) OR GCS OR venous foot pump OR VFP OR \"pneumatic compression\" OR \"pneumatic hose\" OR pneumatic compression hose OR \"vena cava filter*\" OR \"factor xa inhibitors\")",
      "phrases": ["venous thromboembolism prophylaxis", "major orthopedic surgery", "total hip replacement", "total knee replacement", "compression stockings", "antithrombotic medications", "mechanical prophylaxis", "thromboprophylaxis interventions"],
      "terms": {
        "required": ["venous thromboembolism", "prophylaxis", "orthopedic surgery"],
        "optional": ["DVT", "pulmonary embolism", "LMWH", "DOAC", "mechanical prophylaxis", "compression stockings", "hip fracture surgery"],
        "excluded": ["pediatric", "spine surgery", "upper extremity"]
      }
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
    "primary_terms": ["venous thromboembolism prophylaxis", "major orthopedic surgery"],
    "synonyms": {
      "venous thromboembolism": ["VTE", "venous thrombosis", "thromboembolism"],
      "prophylaxis": ["prevention", "thromboprophylaxis", "preventive therapy"],
      "major orthopedic surgery": ["major orthopaedic surgery", "major orthopedic procedures", "major orthopaedic procedures"],
      "antithrombotic medications": ["antithrombotic agents", "antithrombotic therapy", "antithrombotic drugs"],
      "mechanical prophylaxis": ["mechanical interventions", "physical prophylaxis", "mechanical preventive measures"]
    },
    "domain_specific": ["thromboprophylaxis", "intermittent pneumatic compression"],
    "colloquial": []
  }
}

---

## Example 2 - Technology and Social Science

Input 1:
"What factors influence the adoption of renewable energy technologies in developing countries?"

Input 2:
- Technology Type: "Solar photovoltaic systems, wind turbines, and small-scale hydroelectric installations"
- Geographic Context: "Low and middle-income countries in Sub-Saharan Africa and South Asia"
- Factors: "Economic barriers, policy frameworks, infrastructure availability, cultural acceptance, and financing mechanisms"
- Target Adopters: "Rural households, smallholder farmers, and local enterprises"
- Deployment Context: "Off-grid and rural electrification programs"
- Intended For: "Energy policymakers and development aid organizations"
- Temporal Scope: "Studies from 2015 onwards"

Output:

{
  "integrated_statement": "What economic barriers, policy frameworks, infrastructure availability, cultural acceptance, and financing mechanisms influence the adoption of solar photovoltaic systems, wind turbines, and small-scale hydroelectric installations among rural households, smallholder farmers, and local enterprises in off-grid and rural electrification programs in low and middle-income countries in Sub-Saharan Africa and South Asia, based on studies from 2015 onwards, for use by energy policymakers and development aid organizations?",
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
    "semantic": "Research on economic barriers, policy frameworks, infrastructure availability, cultural acceptance, and financing mechanisms affecting adoption of solar photovoltaic systems, wind turbines, and small-scale hydroelectric installations among rural households, smallholder farmers, and local enterprises in off-grid and rural electrification programs across low and middle-income countries in Sub-Saharan Africa and South Asia.",
    "keyword": {
      "structured": "((\"renewable energy\" OR \"clean energy\" OR \"sustainable energy\") AND (adoption OR uptake OR implementation OR deployment)) AND (\"solar photovoltaic systems\" OR \"solar PV\" OR \"wind turbines\" OR \"wind energy\" OR \"small-scale hydroelectric\" OR micro-hydro OR mini-hydro) AND (\"economic barriers\" OR affordability OR cost OR \"policy frameworks\" OR regulation OR infrastructure OR \"cultural acceptance\" OR \"social acceptance\" OR \"financing mechanisms\" OR microfinance) AND (\"low and middle-income countries\" OR LMIC OR LMICs OR \"Sub-Saharan Africa\" OR \"South Asia\" OR Kenya OR Tanzania OR Uganda OR Ethiopia OR India OR Bangladesh OR Pakistan OR Nepal)",
      "phrases": ["renewable energy adoption", "solar photovoltaic systems", "wind turbines", "small-scale hydroelectric", "economic barriers", "policy frameworks", "rural electrification programs", "low and middle-income countries"],
      "terms": {
        "required": ["renewable energy", "adoption", "LMIC"],
        "optional": ["solar photovoltaic", "wind turbines", "micro-hydro", "policy frameworks", "financing mechanisms", "rural electrification", "smallholder farmers"],
        "excluded": ["high-income countries", "industrial scale", "fossil fuel"]
      }
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
    "primary_terms": ["renewable energy", "low and middle-income countries"],
    "synonyms": {
      "renewable energy": ["clean energy", "sustainable energy", "green energy"],
      "adoption": ["uptake", "take-up", "implementation"],
      "low and middle-income countries": ["LMIC", "LMICs", "low- and middle-income countries"],
      "economic barriers": ["financial barriers", "cost barriers", "affordability constraints"],
      "policy frameworks": ["regulatory frameworks", "policy environments", "governance structures"]
    },
    "domain_specific": ["solar PV", "rural electrification", "micro-hydro"],
    "colloquial": []
  }
}

---

## Hard Rules
- Output exactly one JSON object. Do not add preamble, explanation, markdown fences, or comments.
- Use valid JSON only: double quotes, escaped internal quotes, and no trailing commas.
- Every dimension key must appear in `dimensions_specifications`; map `[SKIPPED]` to `null`.
- `publication_types` and `fields_of_study` must use only the permitted values listed above.
- When evidence is insufficient, use empty values; do not infer.
- Do not invent tie-breakers, defaults, or expansions beyond the rules stated in this prompt.
"""
