# Framework Authoring

Frameworks are defined in YAML and loaded from `REFINEMENT_FRAMEWORK_PATH`.
Default location: `./refinement_frameworks/frameworks.yaml`.

The current framework format is designed for non-technical editing as well as advanced customization. A framework starts with an optional `user_context` block followed by one or more dimension entries.

---

## Dimension Fields

### Required

| Field            | Type   | Description                                                                                             |
| ---------------- | ------ | ------------------------------------------------------------------------------------------------------- |
| `id`             | string | Unique identifier used by `depends_on` references and in API responses                                  |
| `name`           | string | Human-readable display name shown to the user                                                           |
| `description`    | string | One-line description of what this dimension clarifies                                                   |
| `specifications` | string | Evaluation instructions sent to the LLM. Supports `{query}`, `{statement}`, and `{input}` placeholders. |

### Optional

| Field             | Type        | Default    | Description                                                                                                                              |
| ----------------- | ----------- | ---------- | ---------------------------------------------------------------------------------------------------------------------------------------- |
| `strictness`      | string      | `moderate` | How completely the dimension must be specified before it is marked done. One of `strict`, `moderate`, or `permissive`.                   |
| `depends_on`      | list of ids | `[]`       | Dimension IDs whose values should be available before this dimension is asked. The registry uses topological sort to enforce this order. |
| `examples`        | mapping     | —          | Few-shot examples injected into the LLM prompt. See [Examples](#examples) below.                                                         |
| `allow_follow_up` | boolean     | `true`     | Whether the LLM may ask clarifying follow-up questions for this dimension.                                                               |
| `max_follow_ups`  | integer     | `50`       | Upper bound on follow-up turns per dimension.                                                                                            |
| `response_format` | mapping     | —          | Override the default structured output schema for this dimension. Rarely needed.                                                         |
| `metadata`        | mapping     | `{}`       | Arbitrary key-value data attached to the dimension for downstream use; not interpreted by the refinement engine.                         |

### Strictness levels

| Value        | Behaviour                                                                                                                                             |
| ------------ | ----------------------------------------------------------------------------------------------------------------------------------------------------- |
| `strict`     | Dimension is only marked complete when the user provides explicit, unambiguous detail. Useful for high-stakes fields (study design, outcome measure). |
| `moderate`   | Balanced threshold. Complete when a reasonable interpretation is available. **Default.**                                                              |
| `permissive` | Complete as soon as any plausible value is present. Good for optional or context-setting dimensions.                                                  |

---

## user_context Block

The `user_context` block is an optional first entry in a framework. It controls how the LLM adapts questions and feedback for the intended audience. It is copied to every dimension in the framework by the registry loader.

| Field           | Type            | Description                                                                   |
| --------------- | --------------- | ----------------------------------------------------------------------------- |
| `user_type`     | string          | Who the user is, e.g. `"MPH student"` or `"systematic reviewer"`              |
| `context`       | string          | Description of the user's situation and goals                                 |
| `tone`          | string          | Response tone: `educational`, `professional`, or `pragmatic`                  |
| `complexity`    | string          | Assumed expertise level: `novice`, `intermediate`, `advanced`, or `expert`    |
| `examples_from` | string          | Domain from which examples should be drawn                                    |
| `constraints`   | list of strings | Hard constraints the system should respect (e.g. timeline, ethics, resources) |
| `pitfalls`      | list of strings | Common errors to flag for this user type                                      |

### Two supported YAML formats for user_context

**Nested** (recommended — explicit and unambiguous):

```yaml
my_framework:
  - user_context:
      user_type: "researcher"
      context: "Systematic review planning"
      tone: "professional"
  - id: population
    ...
```

**Sibling** (legacy — all keys at the same level as `user_context`):

```yaml
my_framework:
  - user_context:
    user_type: "researcher"
    context: "Systematic review planning"
    tone: "professional"
  - id: population
    ...
```

Both formats produce identical behaviour. Prefer the nested form for clarity.

---

## Examples

The `examples` block provides few-shot guidance that is injected into the LLM prompt. It is a mapping of category names to lists of example objects.

```yaml
examples:
  clear:
    - statement: "Adults over 65"
      rationale: "Age group is specific and unambiguous"
  needs_refinement:
    - statement: "people"
      issue: "No age, condition, or setting specified"
      example_question: "Which group of people are you focusing on?"
  partial:
    - statement: "elderly patients"
      has: "Life stage identified"
      missing: "Specific age cutoff or clinical setting"
      example_question: "Do you mean adults over 65, or a specific clinical population?"
  vague_ambiguous:
    - statement: "everyone"
      issue: "Too broad to be clinically meaningful"
      example_question: "Is there a specific population you have in mind?"
  other:
    - statement: "healthy volunteers"
      note: "Valid for safety trials but unlikely in efficacy reviews"
      guidance: "Ask whether the focus is a disease population or healthy subjects"
```

### Example categories

| Category           | Use case                                                                                                                           |
| ------------------ | ---------------------------------------------------------------------------------------------------------------------------------- |
| `clear`            | Statements that are already well-specified. Fields: `statement`, `rationale`.                                                      |
| `needs_refinement` | Statements that are too vague. Fields: `statement`, `issue`, `example_question`.                                                   |
| `partial`          | Statements that have some but not all required detail. Fields: `statement`, `has`, `missing`, `example_question`.                  |
| `vague_ambiguous`  | Statements that are ambiguous or could be interpreted multiple ways. Fields: `statement`, `issue`, `example_question`, `guidance`. |
| `other`            | Edge cases or special handling notes. Fields: `statement`, `note`, `guidance`.                                                     |

All example fields are optional. The legacy `query` field is accepted as an alias for `statement` in all categories.

---

## Minimal Example

```yaml
basic_framework:
  - user_context:
      user_type: "MPH student"
      context: "Refining a dissertation topic"
      tone: "educational"
      complexity: "intermediate"
      examples_from: "public health"
      constraints:
        - "6-12 month timeline"
  - id: population
    name: Population
    description: Who is being studied
    strictness: moderate
    specifications: |
      Analyze the input: {query}
      Identify the target population.
    examples:
      clear:
        - statement: "adults over 65 in the UK"
          rationale: "Age range, country, and life stage are all present"
      needs_refinement:
        - statement: "people"
          issue: "No defining characteristics"
          example_question: "Which group of people are you focusing on — a specific age group, condition, or setting?"
```

## Full Example (with dependencies)

```yaml
pico_framework:
  - user_context:
      user_type: "systematic reviewer"
      context: "Evidence synthesis for clinical guidelines"
      tone: "professional"
      complexity: "expert"
      examples_from: "clinical medicine"
  - id: population
    name: Population
    description: The patient group or condition under study
    strictness: strict
    specifications: |
      **Research input:** {query}
      Identify the clinical population. Require at minimum: age group or condition.
  - id: intervention
    name: Intervention
    description: The treatment or exposure being evaluated
    strictness: strict
    depends_on:
      - population
    specifications: |
      **Research input:** {query}
      Identify the intervention. Use the population context: {population}
  - id: comparator
    name: Comparator
    description: What the intervention is being compared against
    strictness: moderate
    depends_on:
      - intervention
    specifications: |
      **Research input:** {query}
      Identify the comparator (placebo, usual care, active control).
  - id: outcome
    name: Outcome
    description: What is being measured
    strictness: strict
    depends_on:
      - population
      - intervention
    specifications: |
      **Research input:** {query}
      Identify the primary outcome measure.
```

---

## Tips

- Keep each dimension focused on one topic.
- Use `strictness: permissive` for context-setting dimensions that rarely need follow-up.
- Use `depends_on` so the LLM can reference already-collected values without repeating questions.
- Use `examples` to teach the LLM what "clear enough" looks like for your domain. Even two or three `clear` and `needs_refinement` examples significantly improve accuracy.
- Put the most important audience context in `user_context` so the wording adapts without changing the dimension logic.
- The `system_prompt` field is deprecated and ignored. Move dimension-specific framing into `specifications`.

---

## Dependency ordering

The registry validates `depends_on` references at load time. If a dimension references a non-existent ID, or if the dependency graph contains a cycle, the framework is rejected with a `FrameworkLoadError` and is excluded from the available frameworks list. Check the API startup logs if a framework you expect does not appear.

---

## Adding a new framework

1. Open `refinement_frameworks/frameworks.yaml`.
2. Add a new top-level key (the framework name) with a list of dimensions.
3. Restart the API or call `reload_from_env()` in the registry.
4. Confirm it appears: `GET /api/v1/refinement/frameworks`.
