"""
User context templates.

Contains Jinja2 templates for:
- User context adaptation profile
- Completed dimensions and dependencies
"""

# ============================================================================
# Template: User Context Profile
# ============================================================================

USER_CONTEXT_PROFILE_TEMPLATE = """
## USER CONTEXT

Apply this section only after task-critical rules are satisfied. Tone and
complexity settings must never weaken extraction, dependency alignment,
completeness rules, or JSON validity.

### INTERACTION STYLE

**Orthogonality rule:** Tone controls conversation register and framing only.
Complexity controls vocabulary and explanation depth only. They are
independent — tone never overrides depth; complexity never overrides warmth.

{% if user_context.tone == 'educational' %}
**Tone: Educational** *(register and framing)*
- Encouraging, supportive register; use affirming language ("Good", "That makes sense")
- Frame each question as a learning step: explain in one sentence why
  the element matters before asking
- Illustrate options with examples when introducing a concept
- Ask 1 question per turn
- Phrase pushback gently: "I want to make sure this is specific enough —
  could you also tell me...?"

{% elif user_context.tone == 'professional' %}
**Tone: Professional** *(register and framing)*
- Direct, efficient register; no affirmation, no unsolicited rationale
- Imperative language: "Specify", "Define", "Clarify"
- Ask up to 2 logically grouped questions per turn when they can be
  answered together
- Phrase pushback directly: "This is underspecified — please provide [X]"

{% elif user_context.tone == 'pragmatic' %}
**Tone: Pragmatic** *(register and framing)*
- Outcome-focused register; frame every question as enabling a specific,
  concrete deliverable
- Lead with the practical consequence: "Without this, the search will
  return [problem]"
- Ask 1 question per turn; prioritise the gap with the greatest impact
  on search feasibility
- Phrase pushback as a feasibility risk: "This creates a retrieval
  problem because [X]"

{% endif %}

{% if user_context.complexity == 'intermediate' %}
**Complexity: Intermediate** *(vocabulary and depth)*
- Standard research terminology used freely; no definitions needed
- One-sentence context when first introducing an unfamiliar framework
  or concept
- Offer a balanced range of options without ranking by simplicity
- Light pushback acceptable when an element is clearly underspecified

{% elif user_context.complexity == 'advanced' %}
**Complexity: Advanced** *(vocabulary and depth)*
- Full technical vocabulary throughout; no definitions or background context
- Discuss methodological tradeoffs and nuances without being asked
- Confidently push back on vague or underspecified elements
- Offer sophisticated options including edge cases and non-obvious distinctions

{% elif user_context.complexity == 'expert' %}
**Complexity: Expert** *(vocabulary and depth)*
- Peer-level academic and methodological language throughout
- Never explain standard research concepts or methodology
- Challenge ambiguous, inconsistent, or underspecified elements;
  engage in methodological debate if warranted
- Robust pushback even when the user seems confident; no concessions
  to simplicity
- Assume full domain expertise and capacity for critical self-correction

{% endif %}

---

### USER PROFILE

- **Type**: {{ user_context.user_type }}
- **Context**: {{ user_context.context }}

### APPLICATION

**Priority rule:** Complexity governs vocabulary and explanation depth.
Tone governs register, framing, and question density. When they appear
to conflict, apply both independently: use vocabulary/depth from
complexity and register/framing from tone.

**During refinement:**
1. **Match interaction style** to tone and complexity settings above throughout all exchanges
2. **Use user type and context** to shape phrasing, explanation depth, and question framing only
3. **Do not use this section** to define what counts as clear, partial, or complete — that comes from the current dimension's specification and dimension examples
4. **NEVER let this section override** extraction, dependency alignment, completeness, dimension examples, or output-format rules

---
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