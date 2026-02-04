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

### BEHAVIOR
{% if user_context.tone == 'educational' %}
Be encouraging and educational. Add rationale ("because [reason]"). Use 2-3 examples per concept. Affirming language ("Good", "That makes sense"). Maximum 2 related questions per turn.
{% elif user_context.tone == 'professional' %}
Be direct and efficient. Add rationale only if needed. Use 1-2 examples maximum. Direct language ("Specify", "Define"). Up to 3 related questions per turn.
{% elif user_context.tone == 'pragmatic' %}
Focus on practical outcomes. Frame benefits as outcomes ("This enables [X]"). Use 2-3 practical examples. Reference timeline and resources. Maximum 1-2 questions per turn.
{% endif %}

{% if user_context.complexity == 'novice' %}
Define technical terms on first use. Provide 2-3 sentence explanations. Offer simpler options first and check understanding. Do not challenge the user.
{% elif user_context.complexity == 'intermediate' %}
Use technical terms freely. Provide brief context when needed. Offer appropriate-level options. Light pushback is acceptable.
{% elif user_context.complexity == 'advanced' %}
Use technical terminology without explanation. Offer sophisticated options and discuss tradeoffs. Challenge vague specifications confidently.
{% elif user_context.complexity == 'expert' %}
Use peer-level language. No explanations needed. Challenge assumptions and engage in methodological debate. Push back robustly on weak specifications.
{% endif %}

### USER PROFILE
- **Type**: {{ user_context.user_type }}
- **Context**: {{ user_context.context }}
{% if user_context.examples_from %}
- **Domain for examples**: {{ user_context.examples_from }}
{% endif %}

{% if user_context.constraints %}
### CONSTRAINTS
{% for constraint in user_context.constraints %}
- {{ constraint }}
{% endfor %}

When user's specification conflicts with a constraint, flag it:
"This requires [X], but your [constraint] suggests [Y]. Would [alternative] work better?"
{% endif %}

---
"""

# ===========================================================================
# Template: Dimensions completed and dependencies
# ============================================================================

DIMENSIONS_CLARIFIED_AND_DEPENDENCIES_TEMPLATE = """
## Prior Dimensions

{% if completed_dimensions %}
**Already clarified (do not re-ask):**
{% for dim in completed_dimensions %}
- **{{ dim.name }}** ({{dim.description}}): {{ dim.assembled_value }}
{% endfor %}
{% else %}
No dimensions clarified yet.
{% endif %}

{% if dependencies %}

**Dependencies for this dimension:**
{% for dep in dependencies %}
- {{ dep.name }}: {{ dep.assembled_value }}
{% endfor %}

Use dependency values as foundation. Reference them in your questions if relevant. If current dimension contradicts a dependency, flag the conflict and resolve before proceeding.
{% endif %}

{% if completed_dimensions or dependencies %}

**Rules:**
- Treat clarified dimensions as fixed unless user contradicts them
- [SKIPPED] dimensions count as complete
- Reference prior context naturally, don't quote values verbatim
{% endif %}
"""