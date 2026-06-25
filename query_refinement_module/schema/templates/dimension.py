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

### MANDATORY PRE-CHECK — Read before processing the input or asking any question

Before reading the user query or asking any question:

1. **Scan the completed dimensions in the PRIOR CONTEXT system message.**
2. If this dimension's value (or a component of it) appears there, extract it as `current`.
3. If the extracted value fully satisfies this dimension's specification, set `complete=true` and `question=""`. Do NOT ask.
4. Only proceed to the user query and conversation history if genuinely missing.

**Example (domain-agnostic):**
- Completed dimension: **Population** = "farmers in low-income countries, subsistence-based, in tropical regions"
- Current dimension: **Geography**
- Action: extract "tropical regions" → `{"complete": true, "current": "tropical regions", "question": "", "examples": []}`
- Do NOT ask "Which geography?" — the answer is already there.

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
{"complete": <boolean>, "current": "<string>", "question": "<string>", "examples": [<string>, ...]}
```

**Field definitions:**
- `complete` (boolean): true if this dimension is fully specified; false if gaps remain
- `current`: FULL cumulative specification in user's exact words + minimal connectors
- `question`: plain prose clarifying question (no inline examples embedded here)
- `examples`: quick-reply strings; return `[]` only when `complete=true`

**Rules for generating `examples` (when `complete=false`):**
- **Purpose:** Examples help users quickly select from a broad range of valid answers for the current dimension. Each example should be usable as-is without modification.
- **Quantity:** 4–6 options
- **Breadth:** Span the full valid range of the dimension — not just variations on the user's query. Show diversity within the context.
- **Context focus:** Each option must be specific to the current context and answerable by the user right now. Do not use hypotheticals or examples the user cannot evaluate.
- **No prior-dimension repetition:** Never repeat values from completed dimensions. If Context is "displacement camp in Ethiopia", options should be `["Children", "Adolescents","Pregnant women", "All residents"]`, not `["Children in camp", "Pregnant women in camp", ...]`.
- **Distinct options:** No overlapping or redundant options. Not `["Refugees", "All residents"]` (redundant in camp context); use `["Children", "Pregnant women", "Adolescents", "All residents"]` (distinct).
- **Catch-all:** Always include one "no restriction" option (e.g., "Any level", "All groups", "No specific preference"). Place it last.
- **Order:** Most specific → most broad, or most → least common
- **Example (right):** When Context is "displacement camp": `["Children under 5", "Pregnant and lactating women", "Adolescents", "Older adults", "All residents"]` — distinct groups, no location repetition, includes catch-all
- **Example (wrong):** `["Mental health cases", "Substance misuse cases", "Co-occurring cases", "All mental health cases"]` — repeats the Condition; has redundant overlap

---

"""
