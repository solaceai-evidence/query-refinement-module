"""Agent B: Semantic Representation prompt template."""

SEMANTIC_REPRESENTATION_TEMPLATE = """
# SEMANTIC REPRESENTATION

## Role
Extract retrieval-oriented semantic representations from the input.
Produce a natural-language embedding statement and a structured concept graph.
Do not assume any domain — derive all vocabulary and structure from the input.

Return exactly one valid JSON object and no other text.

## Output Schema

{
  "semantic_statement": "",
  "keyword_statement": "",
  "concept_graph": {
    "canonical_concept": {
      "query_role": "topic_or_condition",
      "true_synonyms": [],
      "abbreviations": [],
      "spelling_variants": [],
      "lexical_variants": [],
      "domain_terms": [],
      "colloquial": [],
      "controlled_vocabulary_hints": [
        {"vocabulary_name": "", "terms": [], "confidence": "high"}
      ]
    }
  }
}

---

## semantic_statement

A natural-language retrieval statement optimised for dense embedding or semantic search.
- 2-3 sentences, 50-70 words total. Do not compress all content into a single long sentence.
- Frame as an information need: what the user needs to find, not a topic description.
  Information-need framing encodes closer to how academic documents describe their own content.
- Cover all key aspects present in the statement: primary subject, any comparison or
  contrast, relevant population or entity, and contextual scope. Do not omit secondary aspects.
- Use vocabulary that appears in academic and domain-specific literature for the inferred field.
  Embedding models operate in the document representation space — document-side language reduces the encoding gap between the query and relevant documents.
- Include domain abbreviations when they function as primary retrieval signals in the field.
- Exclude venues, authors, publication types, and years (unless a year range is intrinsic to the statement itself).
- Do not include spelling variants or morphological forms — embedding models handle these.

---

## keyword_statement

A natural-language keyword query optimised for BM25 or simple keyword retrieval.
- 1 sentence or phrase, 15-35 words.
- Include the primary concept terms and their most established synonyms or abbreviations,
  written as space-separated terms or short phrases.
- No Boolean operators (AND, OR, NOT, parentheses).
- No controlled vocabulary headings (those belong in the concept_graph).
- No metadata filters (venues, publication types, years).
- Complement, not repeat, the semantic_statement: where semantic_statement frames the information need in prose, keyword_statement enumerates the key retrieval terms.
- Optimised for systems that tokenise on whitespace and score by term frequency
  (Elasticsearch query_string, Google Scholar, Semantic Scholar, CORE).

---

## concept_graph

Extract 6-8 core concepts from the input. Prioritize in order: primary subject or topic, key entities or groups, primary phenomena or interventions, contextual factors, then remaining concepts by centrality.

The key for each entry is the canonical form of the concept as it appears in the input.

### query_role

The concept's function in retrieval. One of:
  topic_or_condition | population_or_entity | intervention_or_exposure_or_phenomenon |
  setting_or_context | geography | time_scope | comparator | outcome | other

Assign based on retrieval function, not on the user's framework label.
Tiebreaker: when a concept is both the primary subject of the research AND a measured outcome (e.g. "antibiotic-resistant infections" in a study of stewardship programmes), assign topic_or_condition — retrieval scope takes precedence over measurement role.
Use null when genuinely ambiguous.

### true_synonyms

Exact equivalents only: same denotation, different lexical form. If substituted into a sentence, the meaning does not change.
Used in Boolean OR blocks. Do not include broader terms, narrower terms, or related-but-different concepts.

### abbreviations

Established, widely used short forms only. Used in both the Boolean query and the semantic_statement.
Do not include ad hoc or non-standard abbreviations.

### spelling_variants

Orthographic variants with no semantic distinction: regional spelling, hyphenation, diacritics.
Used in Boolean OR blocks only — do not add to semantic_statement.
Examples: "organisation" / "organization", "behaviour" / "behavior".

### lexical_variants

Morphological relatives useful in databases where stemming is not applied: nominalization, adjectival, participial forms.
Used in Boolean OR blocks only.
Examples: "adoption" → ["adopting", "adopted", "adoptive"].

### domain_terms

Related concepts that are NOT true equivalents but improve recall in retrieval broadening.
These must NOT appear in the anchor Boolean query — they widen scope.
They serve as broadening candidates for conceptual expansion (Levels 2–3).
The test: if you substituted a domain_term for the canonical concept, the query scope would widen.

### colloquial

Informal, lay, or vernacular equivalents.
Used for grey literature, practitioner reports, and non-academic sources.
Must NOT appear in the anchor Boolean query for academic bibliographic databases.

### controlled_vocabulary_hints

Infer which controlled vocabulary applies from the domain of the research statement.
Examples: "MeSH" for medicine, "PsycINFO Thesaurus" for psychology, "ERIC Thesaurus" for education,
"ACM Computing Classification System" for computer science, "CAB Thesaurus" for agriculture,
"UNESCO Thesaurus" for social science, "EMTREE" for pharmacology/pharmacovigilance.

Each entry:
- vocabulary_name: name of the controlled vocabulary system
- terms: your best inference of the applicable headings or descriptors
- confidence: "high" (heading exists in this exact or near-exact form), "medium" (a heading likely exists), "low" (uncertain)

Prefer an empty terms list over a hallucinated heading. These are hints for a specialist to verify, not authoritative lookups.
Include only vocabularies that are plausibly in use for the inferred domain.
If no controlled vocabulary applies or is known for the domain, return an empty list.

---

## Example — Medicine

Input:

Research Statement: "Recent studies about venous thromboembolism prophylaxis in patients undergoing major orthopedic surgery (total hip replacement, knee replacement, hip fracture surgery), comparing thromboprophylaxis interventions including antithrombotic medications and mechanical interventions such as compression stockings within and across classes."

Output:

{
  "semantic_statement": "Studies comparing prophylaxis interventions for venous thromboembolism in patients undergoing major orthopedic surgery, including hip and knee arthroplasty and hip fracture repair. The focus is on pharmacological thromboprophylaxis (antithrombotic and anticoagulant agents) versus mechanical prophylaxis (compression stockings, intermittent pneumatic compression), comparing effectiveness within and across intervention classes.",
  "keyword_statement": "venous thromboembolism VTE prophylaxis prevention major orthopedic surgery hip knee arthroplasty antithrombotic anticoagulant compression stockings intermittent pneumatic compression thromboprophylaxis",
  "concept_graph": {
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
}

Key distinctions demonstrated:
- "deep vein thrombosis" and "pulmonary embolism" are domain_terms (narrower types of VTE), not true_synonyms — substituting either would narrow the query scope.
- "total hip replacement" and "total knee replacement" are domain_terms (specific procedures), not true_synonyms of "major orthopedic surgery".
- Specific drugs (aspirin, heparin, warfarin) are domain_terms for "antithrombotic medications" — they are instances, not equivalents.
- "blood clot", "joint replacement surgery", "blood thinners", "compression socks" are colloquial — they belong in grey literature search, not the anchor Boolean query.
- MeSH is used throughout because the domain is medicine; in other domains a different vocabulary would be inferred.

---

## Hard Rules
- Output exactly one JSON object. No preamble, explanation, markdown fences, or comments.
- Extract only what is present in the research statement. Do not invent unstated concepts or vocabulary.
- query_role must be one of the listed values or null.
- domain_terms and colloquial must never appear in true_synonyms or abbreviations.
""".strip()

__all__ = ["SEMANTIC_REPRESENTATION_TEMPLATE"]
