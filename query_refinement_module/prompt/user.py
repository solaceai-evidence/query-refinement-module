EVALUATION_CRITERIA_PROMPT = """
**Original Research Input:** "{original_input}"

**Current research dimension to evaluate:** {aspect_name} 

**Dimension description:** {aspect_description}

---

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
# SYNTHESIS EXECUTION PROTOCOL

## TASK DEFINITION
Transform user research input and clarified dimension specifications into structured search assets.

## INPUT DATA
**Original:** "{original_input}"
**Dimensions:** {aspects_section} ([SKIPPED] = omit from output)

## OUTPUT REQUIREMENTS
Generate valid JSON with this exact structure:
```json
{
  "synthesized_statement": "",
  "detail_values": {},
  "search_optimized": {
    "semantic": "",
    "keyword": {
      "structured": "",
      "phrases": [],
      "terms": {"required": [], "optional": [], "excluded": []}
    },
    "grey_literature": {
      "broad_concepts": [],
      "organizational_terms": [],
      "geographic_variants": []
    }
  },
  "search_filters": {
    "publication_years": "",
    "venues": "",
    "authors": [],
    "publication_types": [],
    "fields_of_study": ""
  },
  "terminology": {
    "primary_terms": [],
    "synonyms": {},
    "domain_specific": [],
    "colloquial": []
  },
  "metadata": {
    "temporal": null,
    "geographic": null,
    "source_types": [],
    "other": {}
  },
  "processing_log": {
    "preserved": [],
    "normalized": [],
    "integrated": [],
    "expanded": []
  }
}
"""