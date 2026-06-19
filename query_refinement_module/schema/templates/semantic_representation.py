"""Agent B: Semantic Representation prompt template."""

SEMANTIC_REPRESENTATION_TEMPLATE = """
# SEMANTIC REPRESENTATION

## Role
Extract retrieval-oriented semantic representations from a normalized research statement.
Produce a natural-language embedding query and a structured concept graph.
Do not assume any domain — derive all vocabulary and structure from the research statement and dimensions.

Return exactly one valid JSON object and no other text.

## Output Schema

{
  "semantic_statement": "",
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

One natural-language retrieval query for embedding or semantic search.
- 50–90 words; target 60–75 words.
- Describe the core subject, phenomenon, and scope.
- Include domain abbreviations when they function as primary retrieval signals in the field.
- Exclude venues, authors, publication types, and years (unless the year range is intrinsic to the research question itself).
- Do not include spelling variants or morphological forms — embedding models handle these internally.
- One sentence only.

---

## concept_graph

Extract 6–8 core concepts from the research statement. Prioritize in order: primary subject or topic, key entities or groups, primary phenomena or interventions, contextual factors, then remaining concepts by centrality.

The key for each entry is the canonical form of the concept as it appears in the research statement.

### query_role

The concept's function in retrieval. One of:
  topic_or_condition | population_or_entity | intervention_or_exposure_or_phenomenon |
  setting_or_context | geography | time_scope | comparator | outcome | other

Assign based on retrieval function, not on the user's framework label.
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

## Hard Rules
- Output exactly one JSON object. No preamble, explanation, markdown fences, or comments.
- Extract only what is present in the research statement. Do not invent unstated concepts or vocabulary.
- query_role must be one of the listed values or null.
- domain_terms and colloquial must never appear in true_synonyms or abbreviations.
""".strip()

__all__ = ["SEMANTIC_REPRESENTATION_TEMPLATE"]
