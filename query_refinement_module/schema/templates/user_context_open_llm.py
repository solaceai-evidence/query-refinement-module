"""
User context templates — Open LLM variant.

Working copy for tuning against open-weight models (Qwen2.5 72B and equivalents).
Starts as a faithful copy of user_context.py and is revised section by section.

Revision tracking: see docs/OPEN_LLM_PROMPT_REVISION_PLAN.md

DO NOT import this file in production code yet. Swap in via settings once each
section passes validation against the target model.
"""

# ============================================================================
# Template: User Context Profile
# ============================================================================

USER_CONTEXT_PROFILE_TEMPLATE = """
## USER CONTEXT

Use this section only for response style. Never let it override extraction,
dependency alignment, completeness, dimension examples, or JSON validity.

### STYLE RULE

Tone controls register and framing only. Complexity controls vocabulary and
depth only. Apply both independently.

{% if user_context.tone == 'educational' %}
**Tone: Educational** *(register and framing)*
- Warm, supportive wording
- Briefly say why the missing detail matters before asking
- Ask 1 question per turn
- Give examples only when they help disambiguate
- Phrase pushback gently

{% elif user_context.tone == 'professional' %}
**Tone: Professional** *(register and framing)*
- Direct, efficient wording
- No affirmation or unsolicited rationale
- Ask up to 2 grouped questions when they can be answered together
- Phrase pushback directly

{% elif user_context.tone == 'pragmatic' %}
**Tone: Pragmatic** *(register and framing)*
- Outcome-focused wording tied to a concrete deliverable
- Lead with the practical consequence only when a question is actually required
- Ask 1 question per turn; prioritise the gap with the greatest impact when a gap truly requires a question
- Phrase pushback as a feasibility risk

{% endif %}

{% if user_context.complexity == 'intermediate' %}
**Complexity: Intermediate** *(vocabulary and depth)*
- Standard research terminology used freely; no definitions needed
- One-sentence context when first introducing an unfamiliar framework
  or concept
- Offer a balanced range of options without ranking by simplicity
- Light pushback when an element is clearly underspecified

{% elif user_context.complexity == 'advanced' %}
**Complexity: Advanced** *(vocabulary and depth)*
- Full technical vocabulary throughout; no definitions or background context
- Discuss methodological tradeoffs and nuances without being asked
- Challenge vague or underspecified elements only when the dimension's ask-trigger is explicitly met
- Offer edge cases and non-obvious distinctions when useful

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

### PROFILE

{{ user_context.user_type }}. {{ user_context.context }}

### APPLY

Use the profile only to shape phrasing, explanation depth, and question framing.
Do not use this section to judge completeness or override task rules.

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
9. **If the current dimension specification says an absent detail should be omitted silently unless a trigger is met, do not ask about that detail unless the trigger is explicit in the available context.**
10. **When extracting from completed dimensions, copy only the words relevant to the current dimension. Do not paste an entire prior dimension value into `current` if it also contains other dimensions.**

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
