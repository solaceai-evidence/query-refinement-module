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
- **Quantity:** 4–6 options showing the dimension's full valid range; fewer only for binary/ternary choices
- **Quality:** Each is a complete, standalone answer the user can submit as-is (≤10 words)
- **Scope:** Span what this dimension *accepts*, not just the user's query components — show variety across the full specification space
- **No duplication:** Never include the value already in `current` or restate the original query
- **Order:** Most specific → most broad, or most → least common
- **Example:** For climate adaptation populations: `["subsistence farmers in arid regions", "coastal fishing communities", "urban low-income residents", "pastoralist groups"]` — shows population diversity; not `["farmers", "farmers in Africa", "smallholder farmers"]` (too similar/granular)

---

"""
