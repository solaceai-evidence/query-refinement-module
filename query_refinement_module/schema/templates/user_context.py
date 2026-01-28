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
## USER CONTEXT ADAPTATION (EXECUTE)

**Parameters - Apply:**
```
tone: {{ user_context.tone }}
complexity: {{ user_context.complexity }}
domain: {{ user_context.examples_from }}
user_type: {{ user_context.user_type }}
{% if user_context.constraints %}
constraints:
{% for constraint in user_context.constraints %}
  - {{ constraint }}
{% endfor %}
{% endif %} 
{% if user_context.pitfalls %}
pitfalls: 
{% for pitfall in user_context.pitfalls %}
  - {{ pitfall }}
{% endfor %}
{% endif %}
```

**Context:** {{ user_context.context }}

---

## ADAPTATION RULES (MANDATORY)

### Tone Execution

**educational:**
- Add rationale to every suggestion: "because [reason]"
- 2-4 examples per concept
- Affirming language ("Good", "That works")
- Max 1 question/turn

**professional:**
- Omit rationale unless needed
- 2-3 examples max
- Direct language ("Specify", "Define")
- Max 3 questions/turn if related

**pragmatic:**
- Frame as outcomes: "This enables [X]"
- Emphasize timeline/resource implications
- 2-4 practical examples
- Max 1-2 questions/turn

### Complexity Calibration

**novice:** Define terms on first use, 2-3 sentence explanations, simpler options first, check understanding

**intermediate:** Use technical terms freely, 1 sentence context, appropriate-level options

**advanced:** No explanations, technical terminology, sophisticated options, discuss tradeoffs

**expert:** Peer-level language, challenge assumptions, methodological debates, no hand-holding

### Domain Examples

Draw ALL examples from `{{ user_context.examples_from }}` domain:

- **public health:** epidemiology, interventions, RCTs, cohort studies, disease prevention
- **legal:** precedent, jurisdiction, case law, statutory interpretation, judicial review  
- **computer science:** algorithms, systems, performance, empirical benchmarking
- **policy:** stakeholders, program evaluation, impact assessment, cost-benefit analysis
- **Other domains:** Use domain-specific terminology and standard methods

{% if user_context.constraints %}
### Constraint Validation

**Parse constraints:**
- "X-month timeline" → Flag if scope exceeds X months
- "Budget: $Y" → Flag if methods require >$Y
- "Skills: [list]" → Flag if methods need unlisted skills

**Format:** "This requires [X] but constraint is [Y]. Alternatives: [A, B, C]"
{% endif %}

{% if user_context.pitfalls %}
### Pitfall Detection

**IF user input matches pitfall pattern → FLAG:**
```
"I notice [quote]. [Risk]. Would [alternative] work better given [constraint]?"
```

**Patterns:**
- "overly ambitious" → detect: "comprehensive", "all", "everything", "entire"
- "unclear question" → detect: "explore", "investigate", "look at", "general"
- "beyond skills" → detect: "complex statistical", "machine learning", "advanced"
- "ignoring constraints" → detect: "large dataset", "longitudinal", "multi-site"
{% endif %}

---

## EXECUTION CHECKLIST

Before responding:
- [ ] Tone behaviors applied
- [ ] Complexity level matched
- [ ] Examples from specified domain
{% if user_context.constraints %}
- [ ] Constraints validated
{% endif %}
{% if user_context.pitfalls %}
- [ ] Pitfalls scanned
{% endif %}

---
"""

# ===========================================================================
# Template: Dimensions completed and dependencies
# ============================================================================

DIMENSIONS_CLARIFIED_AND_DEPENDENCIES_TEMPLATE = """
## Clarified Dimensions

{% if completed_dimensions %}
**Clarified Dimensions:** 
{% for dim in completed_dimensions %}
- {{ dim.name }} ({{ dim.description }}): "{{ dim.assembled_value }}"
{% endfor %}
{% else %}
**No dimensions specifications clarified yet**
{% endif %}

{% if dependencies %}

## Dependencies

**This dimension relies on the specifications of:** 
{% for dep in dependencies %}
- {{ dep.name }}
{% endfor %}

**Critical:** 
- **Do not re-ask about clarified dimensions** (unless conflict arises). Use for consistency checking and to avoid redundancy only.
- **Ensure alignment** of this dimension with dependencies. Flag conflicts immediately.
- **Reference dependencies** in question construction when logically relevant.
{% endif %}

"""
