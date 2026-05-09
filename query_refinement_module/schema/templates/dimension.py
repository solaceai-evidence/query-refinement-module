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

## DIMENSION SPECIFICATION

**Dimension:** {{ name }} 
**Description:** {{ description }}

---

### MANDATORY PRE-CHECK — Read before processing the query

Before reading the user query or asking any question:

1. **Scan the completed dimensions listed in the PRIOR CONTEXT system message above.**
2. Look for any value in those dimensions that matches or contains the current dimension ({{ name }}).
3. If a matching value exists, extract it immediately into `current`. Do NOT ask a question.
4. If the extracted value fully satisfies this dimension's specification, set `complete=true` and `question=""`.

**Cross-dimension extraction example:**
- Completed dimension: **Population** = "adults aged 18-65 with type 2 diabetes in urban clinics"
- Current dimension: **Setting**
- Action: extract "urban clinics" → `{"complete": true, "current": "urban clinics", "question": ""}`
- Do NOT ask "Which specific setting do you mean?" — the answer is already present.

Only proceed to the query and conversation history after this check is complete.

---

### Specification

{{ specifications }}

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


---

## OUTPUT FORMAT
```json
{"complete": <boolean>, "current": "<string>", "question": "<string>"}
```

- `complete`: boolean (not quoted) - false if gaps remain, true if requirements met
- `current`: FULL cumulative specification, user's exact words + minimal connectors
- `question`: clarifying question if incomplete, empty string "" if complete
- Expand references to actual content (not "first one", "combination", "both")
- ONLY these 3 fields

---

"""
