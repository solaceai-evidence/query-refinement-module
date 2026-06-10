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
| `specifications` | string | Evaluation instructions sent to the LLM. Supports only `{query}`, `{statement}`, and `{input}` placeholders. |

### Optional

| Field             | Type        | Default | Description                                                                                                                              |
| ----------------- | ----------- | ------- | ---------------------------------------------------------------------------------------------------------------------------------------- |
| `depends_on`      | list of ids | `[]`    | Dimension IDs whose values should be available before this dimension is asked. The registry uses topological sort to enforce this order. |
| `examples`        | mapping     | —       | Few-shot examples injected into the LLM prompt. See [Examples](#examples) below.                                                         |
| `allow_follow_up` | boolean     | `true`  | Whether the LLM may ask clarifying follow-up questions for this dimension.                                                               |
| `max_follow_ups`  | integer     | `50`    | Upper bound on follow-up turns per dimension.                                                                                            |
| `response_format` | mapping     | —       | Override the default structured output schema for this dimension. Rarely needed.                                                         |
| `metadata`        | mapping     | `{}`    | Arbitrary key-value data attached to the dimension for downstream use; not interpreted by the refinement engine.                         |

### Completeness Rules

Completeness is defined directly inside each dimension's `specifications` text.

Recommended structure:

```yaml
specifications: |
  **Task:** Evaluate and assemble the population specification.

  **Elements to track:**
  - Named population group
  - Age range or life stage
  - Setting or exposure group when relevant

  **Required:**
  - A concrete population anchor

  **Required if applicable:**
  - Age when the intervention or evidence base is age-dependent
  - Exposure group when the question is about a specific hazard pathway

  **Not required unless raised:**
  - Ethnicity or race
```

Use the dimension text to encode the actual behavior you want:

- `Required:` elements that must be present before the dimension can be complete.
- `Required if applicable:` elements that become mandatory only when triggered by the query, prior context, or user answer.
- `Not required unless raised:` elements that should be extracted if present but should not trigger unnecessary probing.
- `Specificity thresholds:` optional guidance describing what counts as insufficient, sufficient, or over-specified.

This keeps the completeness rule close to the domain logic instead of forcing every dimension into the same global tier.

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

### Supported placeholders in `specifications`

Only the following placeholder tokens are substituted in the live runtime path:

- `{query}`
- `{statement}`
- `{input}`

These all resolve to the current user query text for the dimension under evaluation.

Previously completed dimensions are not interpolated into `specifications` with arbitrary placeholders such as `{population}`. Instead, completed dimension values are provided separately in the prior-context system message, and the model is expected to extract from that context when relevant.

---

## Examples

The `examples` block provides few-shot guidance that is injected into the LLM prompt. It is a mapping of category names to lists of example objects.

```yaml
examples:
  clear:
    - statement: "adults over 65"
      rationale: "Population anchor and age range are explicit"
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
      issue: "Too broad to guide retrieval"
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
    specifications: |
      **Task:** Analyze the input and identify the target population.

      **Required:**
      - A concrete population anchor

      **Required if applicable:**
      - Age range when age materially affects the evidence base
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
    specifications: |
      **Research input:** {query}

      **Required:**
      - A named clinical population or condition

      **Required if applicable:**
      - Age group when the evidence base is age-dependent
  - id: intervention
    name: Intervention
    description: The treatment or exposure being evaluated
    depends_on:
      - population
    specifications: |
      **Research input:** {query}

      **Required:**
      - A named intervention or exposure

      **Required if applicable:**
      - Dose or delivery details when the label is otherwise ambiguous
  - id: comparator
    name: Comparator
    description: What the intervention is being compared against
    depends_on:
      - intervention
    specifications: |
      **Research input:** {query}

      **Required:**
      - A comparator anchor such as placebo, usual care, or active control
  - id: outcome
    name: Outcome
    description: What is being measured
    depends_on:
      - population
      - intervention
    specifications: |
      **Research input:** {query}

      **Required:**
      - A named outcome or endpoint

      **Required if applicable:**
      - Measurement instrument or timepoint when needed to distinguish materially different outcomes
```

---

## Tips

- Keep each dimension focused on one topic.
- Encode completeness rules directly in `specifications` rather than relying on a global tier.
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