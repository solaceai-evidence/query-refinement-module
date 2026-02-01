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

### MAIN SPECIFICATION STATES (other states possible)

| State | Action |
|-------|--------|
| **Clear** | All standards met → `is_complete: true` |
| **Needs Refinement** | Missing elements → ask `next_question` |
| **Partial** | Some elements present → ask `next_question` |
| **Ambiguous/Vague** | Not specific enough → ask for clarification |

---

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


{% if response_strategy %}
### Response Strategy
{{response_strategy }}

---
{% endif %}


### OUTPUT FORMAT AND REQUIREMENTS
Generate **ONLY** valid JSON matching this exact structure:

```json
{
  "is_complete": false,
  "reasoning": "",
  "next_question": null,
  "refinement_aspect_value": null
}
```
**Field Descriptions:**
- `is_complete` (boolean): Indicates if the dimension is fully specified (`true`) or requires further refinement (`false`).
- `reasoning` (string): Concise explanation of the current status, highlighting clear elements and identifying critical gaps.
- `next_question` (string or null): If `is_complete` is `false`, provide the next focused question to address remaining gaps; otherwise, set to `null`.
- `refinement_aspect_value` (string or null): If `is_complete` is `true`, provide the fully assembled dimension value using exact user words; otherwise, set to `null`.  

** Follow Value Assembly Rules from Global System Directive when constructing `refinement_aspect_value`. **

**Validation rules:**
- If `is_complete: true` → `refinement_aspect_value` must be non-null, `next_question` must be null
- If `is_complete: false` → `next_question` must be non-null, `refinement_aspect_value` can be null or partial

"""


# ============================================================================
# Template: Examples Section (standalone)
# ============================================================================

EXAMPLES_SECTION_TEMPLATE = """
## Examples

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
"""

# ============================================================================  
# Template: Initial User Input
# ============================================================================

INITIAL_USER_INPUT_TEMPLATE = """
## Conversation History
 
**Original User Input:**
```
{{ original_input }}
```
---

**EXECUTE REFINEMENT PROTOCOL** (no conversation history yet)
"""

# ============================================================================  
# Template: Follow-up User Input
# ============================================================================

FOLLOW_USER_INPUT_TEMPLATE = """
## Conversation History

**Original User Input:**
```
{{ original_input }}
```
 
**Conversation History:**
{% if conversation_history %}
{% for turn in conversation_history %}
Q{{ loop.index }}: {{ turn.question }}
A{{ loop.index }}: {{ turn.answer }}
{% endfor %}
{% else %}
(First refinement turn on this dimension)
{% endif %}

---

 Extract specification using priority order: (1) Original input first, (2) Conversation history second (all turns). Assemble following Step 5: ASSEMBLE from Global system directive. Evaluate against Dimension Specification Schema. Output JSON result.
"""
