"""
Dimension refinement templates.

Contains Jinja2 templates for:
- Dimension evaluation criteria
- Examples sections
- Initial and follow-up user input prompts
- Output format requirements
"""

# ============================================================================
# Template: Dimension Refinement
# ============================================================================

DIMENSION_REFINEMENT_TEMPLATE = """
---

## DIMENSION SPECIFICATION SCHEMA

**Dimension:** {{ aspect_name }} 
**Description:** {{ aspect_description }}

---

### Criteria

{{ evaluation_criteria }}

---

{% if assembly_rules %}
### Assembly Rules for "current" Field

Examples of how to format the `current` field for this dimension:

{{ assembly_rules }}

---

{% endif %}
{% if examples_section %}
### Examples

{% if examples['clear'] %}
**Clear Specifications:**
{% for ex in examples['clear'] %}
- "{{ ex.statement or ex.query or ex['statement'] or ex['query'] }}"
{% if ex.rationale or ex['rationale'] %}
  Rationale: {{ ex.rationale or ex['rationale'] }}
{% endif %}

{% endfor %}
{% endif %}

{% if examples['needs_refinement'] %}
**Needs Refinement:**
{% for ex in examples['needs_refinement'] %}
- "{{ ex.statement or ex.query or ex['statement'] or ex['query'] }}"
{% if ex.issue or ex['issue'] %}
  Issue: {{ ex.issue or ex['issue'] }}
{% endif %}
{% if ex.missing or ex['missing'] %}
  Missing: {{ ex.missing or ex['missing'] }}
{% endif %}
{% if ex.example_question or ex['example_question'] %}
  Example Q: "{{ ex.example_question or ex['example_question'] }}"
{% endif %}

{% endfor %}
{% endif %}

{% if examples['partial'] %}
**Partial Specifications:**
{% for ex in examples['partial'] %}
- "{{ ex.statement or ex.query or ex['statement'] or ex['query'] }}"
{% if ex.has or ex['has'] %}
  Has: {{ ex.has or ex['has'] }}
{% endif %}
{% if ex.missing or ex['missing'] %}
  Missing: {{ ex.missing or ex['missing'] }}
{% endif %}
{% if ex.example_question or ex['example_question'] %}
  Example Q: "{{ ex.example_question or ex['example_question'] }}"
{% endif %}

{% endfor %}
{% endif %}

{% if examples['ambiguous'] %}
**Ambiguous/Vague:**
{% for ex in examples['ambiguous'] %}
- "{{ ex.statement or ex.query or ex['statement'] or ex['query'] }}"
{% if ex.issue or ex['issue'] %}
  Issue: {{ ex.issue or ex['issue'] }}
{% endif %}
{% if ex.guidance or ex['guidance'] %}
  Guidance: {{ ex.guidance or ex['guidance'] }}
{% endif %}
{% if ex.example_question or ex['example_question'] %}
  Example Q: "{{ ex.example_question or ex['example_question'] }}"
{% endif %}

{% endfor %}
{% endif %}

{% if examples['other'] %}
**Additional Guidance:**
{% for ex in examples['other'] %}
- "{{ ex.statement or ex.query or ex['statement'] or ex['query'] }}"
{% if ex.note or ex['note'] %}
  Note: {{ ex.note or ex['note'] }}
{% endif %}
{% if ex.guidance or ex['guidance'] %}
  Guidance: {{ ex.guidance or ex['guidance'] }}
{% endif %}

{% endfor %}
{% endif %}

---
{% endif %}


## Response Format

Output ONLY this JSON, nothing else before or after:

{"complete": <boolean>, "current": "<string>", "question": "<string>"}

If incomplete:
{"complete": false, "current": "adults over 40", "question": "Which clinical condition and setting—primary care, hospital, or community?"}

If complete:
{"complete": true, "current": "adults over 40 with type 2 diabetes in primary care settings", "question": ""}

**Fields:**
- **complete**: boolean, not quoted (false if gaps remain, true if all requirements met)
- **current**: FULL cumulative specification from all responses, using user's exact words with minimal connectors
- **question**: clarifying question if incomplete, empty string "" if complete

**Critical Rules:**
- If user gave shorthand (number/letter), expand to full content in "current"
- **ONLY include these 3 fields** - do not add extra fields like 'context', 'round', 'metadata', etc.

---

"""
