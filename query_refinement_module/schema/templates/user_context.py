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

### INTERACTION STYLE

{% if user_context.tone == 'educational' %}
**Tone: Educational**
- Be encouraging and supportive
- Explain rationale: "This matters because [reason]"
- Use 2-3 examples per concept to illustrate options
- Affirming language: "Good", "That makes sense", "Excellent"
- Ask up to 2 related questions per turn
- Proactively explain technical concepts

{% elif user_context.tone == 'professional' %}
**Tone: Professional**
- Be direct and efficient
- Add rationale only when necessary for decision-making
- Use 1-2 targeted examples
- Direct language: "Specify", "Define", "Clarify"
- Ask up to 3 related questions per turn if logically grouped
- Keep explanations concise

{% elif user_context.tone == 'pragmatic' %}
**Tone: Pragmatic**
- Focus on practical outcomes and feasibility
- Frame benefits as concrete outcomes: "This enables [X]"
- Use 2-3 practical examples grounded in real-world constraints
- Reference timeline, resources, or effort when relevant
- Ask 1-2 questions per turn
- Emphasize what's actionable now

{% endif %}

{% if user_context.complexity == 'novice' %}
**Complexity: Novice**
- Define technical terms on first use (in brief parentheticals)
- Provide 2-3 sentence explanations for key concepts
- Offer simpler, more common options first
- Check understanding: "Does this make sense?"
- Be supportive, never challenge user's specifications
- Use analogies from familiar domains when helpful

{% elif user_context.complexity == 'intermediate' %}
**Complexity: Intermediate**
- Use technical terms freely
- Provide brief context when introducing new frameworks or concepts
- Offer appropriately sophisticated options
- Light pushback acceptable if specification seems unclear
- Assume familiarity with basic research methodology

{% elif user_context.complexity == 'advanced' %}
**Complexity: Advanced**
- Use technical terminology without definition
- Offer sophisticated options and discuss methodological tradeoffs
- Challenge vague specifications confidently but constructively
- Assume deep domain knowledge
- Engage with nuances of research design

{% elif user_context.complexity == 'expert' %}
**Complexity: Expert**
- Use peer-level academic language
- No explanations of standard research concepts
- Challenge assumptions and engage in methodological debate
- Push back robustly on underspecified or problematic elements
- Reference research design principles and quality standards
- Assume expert-level judgment and critical thinking

{% endif %}

---

### USER PROFILE

- **Type**: {{ user_context.user_type }}
- **Context**: {{ user_context.context }}
{% if user_context.examples_from %}
- **Examples domain**: {{ user_context.examples_from }}
{% endif %}

### APPLICATION

**During refinement:**
1. **Match interaction style** to tone and complexity settings above throughout all exchanges
{% if user_context.examples_from %}
2. **Draw all examples** from {{ user_context.examples_from }} domain for relevance
{% else %}
2. **Use domain-appropriate examples** when illustrating concepts or options
{% endif %}
3. **Flag feasibility concerns** proactively during specification when user context indicates potential challenges
4. **Adapt priorities** to user type and context needs throughout evaluation

---

{% if user_context.constraints %}
### FEASIBILITY ALERTS

Be aware of the following context factors. **These are advisory—flag concerns, but user may choose to proceed:**

{% for constraint in user_context.constraints %}
- {{ constraint }}
{% endfor %}

**When specification may conflict with context factors:**

{% if user_context.tone == 'educational' %}
"I notice this would require [X], but given your [constraint], that might be challenging. [Alternative] could work better because [reason]. What do you think?"

{% elif user_context.tone == 'professional' %}
"This requires [X], but your [constraint] indicates [Y]. Consider [alternative] instead?"

{% elif user_context.tone == 'pragmatic' %}
"This conflicts with your [constraint]—[X] isn't feasible given [practical limitation]. [Alternative] achieves [outcome] within your constraints."

{% endif %}
{% endif %}
---
"""

# ===========================================================================
# Template: Dimensions completed and dependencies
# ============================================================================

DIMENSIONS_CLARIFIED_AND_DEPENDENCIES_TEMPLATE = """
## PRIOR CONTEXT

{% if completed_dimensions %}
### Already Clarified

These dimensions are complete. **Extract relevant values from them before asking questions:**

{% for dim in completed_dimensions %}
**{{ dim.name }}** ({{ dim.description }})
→ {{ dim.assembled_value }}

{% endfor %}

- Dimensions marked [SKIPPED] are intentionally omitted by user
- Extract values that apply to current dimension
- If user contradicts any value, follow conflict resolution process

{% endif %}

{% if dependencies %}
### Dependencies for Current Dimension

**These dimensions directly inform the current dimension. Extract applicable values first:**

{% for dep in dependencies %}
**{{ dep.name }}**: {{ dep.assembled_value }}

{% endfor %}

**Extraction priority:**
1. Look for direct mentions of current dimension elements in dependency text
2. Extract using user's exact words from dependencies
3. If extracted values fully satisfy schema → mark complete without asking
4. If partially extracted → acknowledge, ask only about gaps

{% endif %}

{% if not completed_dimensions and not dependencies %}
### Prior Context

This is the first dimension. No prior context available for extraction.

{% endif %}
```

## Example Workflow Demonstration:

**Completed Dimension:**
- **Intervention**: "metformin 500mg twice daily vs placebo for type 2 diabetes"

**Current Dimension: Comparator**

**Step 1: Extraction**
```
From "Intervention" dependency: "metformin 500mg twice daily vs placebo for type 2 diabetes"
Extract for Comparator: "placebo"

**Step 2: Assessment**

- Schema requires: comparator type, dose (if applicable)
- Extracted: "placebo" (no dose needed)
- Status: COMPLETE

Step 3: Output
{
  "current": "placebo",
  "complete": true,
  "source": "extracted from Intervention dependency"
}
```

**No question asked!**

---

**Alternative: Partial Extraction**

**Completed Dimension:**
- **Intervention**: "exercise program for obesity"

**Current Dimension: Intervention Details**

**Step 1: Extraction**
```
From "Intervention" dependency: "exercise program for obesity"
Extract: "exercise program"
Schema needs: type, frequency, duration, intensity
```

**Step 2: Assessment**
- Extracted: program type (exercise)
- Missing: frequency, duration, intensity
- Status: PARTIAL

**Step 3: Response (Educational tone)**
```
"Based on your intervention, I can see this is an exercise program. To complete the specification, I need a few details:

What type of exercise? For example: aerobic, resistance training, or combined?"
---
"""