"""
User prompt templates for dimension evaluation.

These are formatted with Python .format() method (not Jinja2) for backward compatibility
with the existing RefinementAspect model.
"""

EVALUATION_CRITERIA_PROMPT = """
# Dimension Evaluation: {aspect_name}

**Dimension Description:** {aspect_description}

---

## Original User Input

{original_input}

---

{conversation_section}

{dependency_section}

## Evaluation Criteria

{evaluation_instructions}

---

{examples_section}

---

{output_format_section}
"""
