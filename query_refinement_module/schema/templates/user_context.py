"""
User context templates.

Contains Jinja2 templates for:
- Completed dimensions and dependencies
"""

# ===========================================================================
# Template: Dimensions completed and dependencies
# ============================================================================

DIMENSIONS_CLARIFIED_AND_DEPENDENCIES_TEMPLATE = """
## PRIOR CONTEXT — EXTRACT BEFORE ASKING

BEFORE ASKING ANY QUESTION: check completed dimensions for extractable values and carry them into current.

{% if completed_dimensions %}
### Completed Dimensions

{% for dim in completed_dimensions %}
{% if dependencies and dim.id in dependencies|map(attribute='id')|list %}✓ **{{ dim.name }}{% if dim.description %} ({{ dim.description }}){% endif %}:** {{ dim.assembled_value }}
{% else %}**{{ dim.name }}{% if dim.description %} ({{ dim.description }}){% endif %}:** {{ dim.assembled_value }}
{% endif %}
{% endfor %}

**Instructions:**
1. ✓ = DEPENDENCY (foundational, cannot be changed, current dimension MUST align)
2. Search ALL dimensions above for elements matching current specification
3. Extract using user's **exact words** from the dimension values
4. Integrate extracted values into "current" field before asking questions
5. Dimensions marked [SKIPPED] are intentionally omitted by user—do not ask about them
6. If any valid partial signal is found, keep it in `current` even when `complete=false`
7. Use empty `current` only when no extractable signal exists across completed dimensions, conversation history, and original query
8. **If the full value for this dimension is directly present in a completed dimension, set complete=true and question="" immediately. Do not ask for additional context, scope, or whether there is "more" beyond the extracted value.**

{% endif %}

{% if not completed_dimensions and not dependencies %}
### First Dimension

No prior context available. Proceed with questions.

{% endif %}

---

## Extraction Examples

**Example 1: Full Extraction (No Question Needed)**
- Completed: **Intervention** = "metformin 500mg twice daily vs placebo"
- Current: **Comparator**
- Extraction: "placebo" (satisfies full schema)
- Output: {"current": "placebo", "complete": true}
- **No question asked**

**Example 2: Partial Extraction + Question**
- Completed: **Intervention** = "exercise program for 6 months"
- Current: **Intervention Details** (schema: type, frequency, duration, intensity)
- Extraction: duration="6 months"
- Output: {"current": "duration: 6 months", "complete": false}
- Question: "I have the duration (6 months). What type of exercise will this be?"

**Example 3: Cross-Dimension Extraction**
- Completed: **Population** = "adults aged 18-65 with type 2 diabetes in urban clinics"
- Current: **Setting**
- Extraction: "urban clinics"
- Output: {"current": "urban clinics", "complete": true}
- **No question asked**
---
"""