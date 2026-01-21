UNIFIED_ANALYSIS_PROMPT = """
**Original Research Input:** "{original_input}"

**Research Dimension:** {aspect_name} ({aspect_description})

---
**Conversation History for {aspect_name}:**
{conversation_section}

---

{dependency_section}

---

{evaluation_instructions}

---

{examples_section}

---

{output_format_section}
"""

SYNTHESIS_PROMPT_TEMPLATE = """
# TASK

Integrate the original research input with clarified details, then generate search-optimized variants and extract search filters.

---

## ORIGINAL INPUT
"{original_input}"

---

## CLARIFIED DETAILS

{aspects_section}

**Note:** [SKIPPED] = not applicable, omit from output.

---

## OUTPUT STRUCTURE

Your JSON output contains:

1. **synthesized_statement** — Faithful integration (primary deliverable)
2. **search_optimized** — Variants for semantic, keyword, grey literature search
3. **search_filters** — Academic database filters (years, venues, authors, fields)
4. **terminology** — Comprehensive term extraction
5. **detail_values** — Normalized values for each detail
6. **metadata** — Additional context
7. **processing_log** — Synthesis decisions documented

---

## STEP 1: CREATE SYNTHESIZED_STATEMENT

Integrate original input with clarified details:

1. Identify core question/topic from original
2. Enrich with all detail values (ignore [SKIPPED])
3. Preserve format: question → question, statement → statement
4. Resolve conflicts: prioritize detail over original (most recent intent)
5. Remove conversational artifacts: fillers, meta-commentary
6. Preserve user's terminology and phrasing

### Normalization Rules

**Always apply:**
- Fix typos and grammar
- Expand domain abbreviations (T2DM → type 2 diabetes mellitus)
- Remove fillers: um, well, you know, obviously, actually, sort of, kind of
- Remove meta-commentary: I think, maybe, I want to study, This research focuses on
- Use complete sentences

**Preserve user choice:**
- Keep user's terminology unless details refined it
- Keep phrasing style (formal/informal)
- Keep question structure ("Does X help Y?" not "Impact of X on Y")
- Don't impose academic register on plain language

**Apply if unambiguous:**
- Resolve pronouns with clear referents
- Make implicit explicit ("diabetes patients" → "patients with diabetes")
- Reorder for clarity

**Never:**
- Alter facts or add unstated information
- Expand vague temporal terms without context (preserve "recent" unless clear)
- Add constraints not in input/details
- Change operators (and ↔ or, with ↔ without)
- Rephrase for style alone

**Temporal context:** Current year 2026. "Recent" in medical research typically = 5-10 years if domain conventions clear.

---

## STEP 2: GENERATE SEARCH VARIANTS

Using synthesized_statement as foundation, create optimized variants.

### SEMANTIC SEARCH

**Goal:** Optimize for embedding/vector models (RAG, semantic databases)

**Requirements:**
- Natural language, clear concept relationships
- 40-80 words optimal
- Include technical terms + contextual information
- Don't keyword-stuff (embeddings understand meaning)

**Example:**
```
Original: "metformin for diabetes in elderly"
Semantic: "Effectiveness of metformin treatment for managing blood glucose levels and achieving glycemic control in older adult populations (65+ years) diagnosed with type 2 diabetes mellitus, including clinical outcomes such as HbA1c reduction and metabolic health improvements"
```

### KEYWORD SEARCH

**Goal:** Optimize for academic databases (PubMed, Scopus, Web of Science)

**Structured Boolean Query:**
- Use AND, OR, NOT with parentheses
- Include full terms + abbreviations
- Use truncation (diabet*, treat*)

**Key Phrases:**
- 5-10 phrases (2-4 words)
- Exact phrases from target literature

**Terms:**
- Required: Must appear for relevance
- Optional: Improve relevance but not essential
- Excluded: Filter irrelevant results

**Example:**
```
Structured: (metformin OR biguanides) AND (type 2 diabetes OR T2DM) AND (elderly OR older adults OR geriatric) AND (treatment OR therapy)
Phrases: ["metformin treatment", "type 2 diabetes", "older adults"]
Terms:
  Required: ["metformin", "diabetes", "elderly"]
  Optional: ["HbA1c", "outcomes"]
  Excluded: ["type 1 diabetes", "pediatric"]
```

### GREY LITERATURE

**Goal:** Optimize for reports, policy documents, NGO publications

**Broad Concepts:**
- Accessible terminology (not academic)
- Policy/practice language
- Outcomes and applications focus

**Organizational Terms:**
- NGO/government/WHO language
- Program/initiative terminology

**Geographic Variants:**
- Regional terminology (LMIC-specific)
- Local health system terms

**Example:**
```
Broad: ["diabetes medication programs for seniors"]
Organizational: ["diabetes management programs"]
Geographic: ["primary health center care"]
```

### TERMINOLOGY EXTRACTION

**Primary Terms:** 3-5 core concepts (from input + details)

**Synonyms:** For each primary term, list variants/abbreviations

**Domain-Specific:** Technical/scientific nomenclature

**Colloquial:** Plain language equivalents

**Example:**
```
Primary: ["metformin", "type 2 diabetes", "elderly"]
Synonyms:
  metformin: ["Glucophage", "biguanide"]
  type 2 diabetes: ["T2DM", "NIDDM"]
Domain: ["HbA1c", "hyperglycemia"]
Colloquial: ["blood sugar medication"]
```

---

## STEP 3: EXTRACT SEARCH FILTERS

Extract metadata filters for academic search APIs (Semantic Scholar, PubMed, Scopus).

### PUBLICATION YEARS

Extract temporal constraints from original input or clarified details.

**Rules:**
- Current year: 2026
- "Recent" → 2020-2026 (last 5-7 years, medical/health research)
- "Last decade" → 2016-2026
- "Since [year]" → [year]-2026
- "Last [N] years" → (2026-N)-2026
- If no temporal reference → leave empty

**Output:** `"start_year-end_year"` or `""` if not specified

**Examples:**
```
"recent diabetes studies" → "2020-2026"
"studies from 2018 to 2023" → "2018-2023"
"last 10 years" → "2016-2026"
"diabetes treatment" (no temporal) → ""
```

### VENUES

Extract specific journals, conferences, or publishers mentioned.

**Rules:**
- Use exact names as mentioned
- Comma-separated string
- Include both abbreviations and full names if mentioned
- If not mentioned → empty string

**Output:** `"venue1, venue2"` or `""`

**Examples:**
```
"papers from Nature or Science" → "Nature, Science"
"studies in NEJM" → "NEJM, New England Journal of Medicine"
"recent conference papers" (no specific venue) → ""
```

### AUTHORS

Extract specific author names mentioned.

**Rules:**
- Each author as separate array item
- Use format as mentioned (First Last or Last, First)
- If not mentioned → empty array

**Output:** `["Author 1", "Author 2"]` or `[]`

**Examples:**
```
"research by Jane Smith and John Doe" → ["Jane Smith", "John Doe"]
"studies on diabetes" (no authors) → []
```

### PUBLICATION TYPES

Extract specific publication study types mentioned

**standard publication type fields:**
Before and after study, Case control study, Case report, Case series, Clinical study, Clinical trial, Cohort study, Comparative study, Cross-sectional study, Diagnostic test accuracy study, Evaluation study, Observational study, Pilot study, Quality improvement study, Randomized controlled trial, Validation study, Consensus conference, Guideline, Living review, Meta-analysis, Rapid review, Scoping review, Systematic review, Narrative review, Review, Government document, Policy document

**Rules:**
- Each publication study type as separate array item
- If user explicitly specifies publication types that are not in the standard publication type fields, add them to the list
- If not mentioned → empty array

**Output:** `["Study type 1", "Study type 2"]` or `[]`

**Examples:** 
```
"research about effective diabetes treatment in older adults in before and after study and available systematic reviews" → ["before and after study", "systematic reviews"]
"studies on diabetes" (too vague, leave empty to include all types of studies) → []
```


### FIELDS OF STUDY

Map research topic to standardized fields.

**Allowed fields:**
Computer Science, Medicine, Public Health, Chemistry, Biology, Materials Science, Physics, Geology, Psychology, Art, History, Geography, Sociology, Business, Political Science, Economics, Philosophy, Mathematics, Engineering, Environmental Science, Agricultural and Food Sciences, Education, Law, Linguistics

**Rules:**
- Map subfields/ambiguous terms to closest match
- Multiple fields: comma-separated, no spaces
- If ambiguous, include all relevant fields
- If not determinable → empty string

**Mapping guidance:**
```
Machine learning, AI, NLP → Computer Science
Clinical trials, diseases, treatments → Medicine
Neuroscience → Medicine, Biology
Mental health → Medicine, Psychology
Climate change → Environmental Science
Farming, crops → Agricultural and Food Sciences
```

**Output:** `"Field1,Field2"` or `""`

**Examples:**
```
"machine learning for disease diagnosis" → "Computer Science,Medicine"
"diabetes treatment" → "Medicine"
"social media effects on teenagers" → "Psychology,Sociology"
"recent papers" (topic unclear) → ""
```

---

{output_format_section}

---

## EXAMPLE

**Original Input:** "recent machine learning papers from NeurIPS on protein folding"

**Clarified Details:**
- **Methodology** (Computational methods used)  
  Value: "deep learning neural networks"
- **Application Domain** (Target application area)  
  Value: "protein structure prediction"

---

**Output:**
```json
{
  "synthesized_statement": "Deep learning neural networks for protein structure prediction in recent machine learning research from NeurIPS",
  
  "detail_values": {
    "methodology": "deep learning neural networks",
    "application_domain": "protein structure prediction"
  },
  
  "search_optimized": {
    "semantic": "Application of deep learning neural network architectures to predict three-dimensional protein structures and folding patterns, focusing on machine learning approaches published in recent NeurIPS proceedings and related computational biology research",
    
    "keyword": {
      "structured": "(deep learning OR neural networks OR deep neural networks OR machine learning) AND (protein folding OR protein structure prediction OR protein structure OR structural prediction) AND (NeurIPS OR Neural Information Processing Systems)",
      
      "phrases": [
        "deep learning",
        "neural networks",
        "protein folding",
        "protein structure prediction",
        "machine learning"
      ],
      
      "terms": {
        "required": ["deep learning", "protein", "structure"],
        "optional": ["neural networks", "folding", "prediction", "AlphaFold", "computational biology"],
        "excluded": ["RNA folding", "DNA structure"]
      }
    },
    
    "grey_literature": {
      "broad_concepts": [
        "AI for protein research",
        "computational protein modeling",
        "machine learning in biology"
      ],
      "organizational_terms": [
        "protein structure initiatives",
        "computational biology programs"
      ],
      "geographic_variants": []
    }
  },
  
  "search_filters": {
    "publication_years": "2020-2026",
    "venues": "NeurIPS, Neural Information Processing Systems",
    "authors": [],
    "publication_types": ["Case control study", "Case report"],
    "fields_of_study": "Computer Science,Biology"
  },
  
  "terminology": {
    "primary_terms": [
      "deep learning",
      "protein folding",
      "protein structure prediction",
      "neural networks"
    ],
    
    "synonyms": {
      "deep learning": ["deep neural networks", "DNN", "machine learning"],
      "protein folding": ["protein structure prediction", "structural prediction", "tertiary structure"],
      "neural networks": ["artificial neural networks", "ANN", "deep networks"],
      "NeurIPS": ["Neural Information Processing Systems", "NIPS"]
    },
    
    "domain_specific": [
      "protein structure",
      "tertiary structure",
      "structural biology",
      "computational biology",
      "AlphaFold",
      "molecular dynamics"
    ],
    
    "colloquial": [
      "AI for protein research",
      "predicting protein shapes",
      "protein modeling"
    ]
  },
  
  "metadata": {
    "temporal": "2020-2026",
    "geographic": null,
    "source_types": ["conference papers"],
    "other": {
      "conference": "NeurIPS"
    }
  },
  
  "processing_log": {
    "preserved": [
      "'machine learning' from original input",
      "'protein folding' from original input",
      "'NeurIPS' venue specification"
    ],
    
    "normalized": [
      "Expanded 'NeurIPS' to include full name 'Neural Information Processing Systems'"
    ],
    
    "integrated": [
      "Combined 'machine learning' with 'deep learning neural networks' methodology",
      "Integrated 'protein folding' with 'protein structure prediction' application domain",
      "Maintained NeurIPS venue constraint"
    ],
    
    "expanded": [
      "Search filters: Extracted 'recent' → 2020-2026",
      "Search filters: Extracted venue 'NeurIPS'",
      "Search filters: Mapped to Computer Science, Biology fields",
      "Semantic: Added computational biology context",
      "Keywords: Added related terms (AlphaFold, structural prediction)",
      "Terminology: Included both technical and accessible variants"
    ]
  }
}
```

---

## QUALITY CHECKS

Verify before finalizing:

- Synthesized_statement preserves user intent and terminology  
- Semantic query 40-80 words, natural language, all key concepts  
- Keyword Boolean syntax correct with parentheses  
- Search filters accurately extracted:
  - Publication years in YYYY-YYYY format or empty
  - Venues exact as mentioned
  - Fields mapped to allowed list
- All details represented in search variants  
- Grey literature uses accessible language  
- Terminology comprehensive  
- No contradictions between variants  
- Processing log documents filter extraction

---

Now synthesize the research input and clarifying details above.
"""