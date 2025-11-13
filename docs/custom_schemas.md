# Custom Refinement Schemas

Design custom refinement frameworks in YAML so the module can orchestrate multi-step conversations tailored to your domain. This document reflects the current `query_refinement_module.schema` model and shows how to author complete, validated schemas.

## 1. Setup Checklist

- Install PyYAML in the same environment as the module: `pip install pyyaml`.
- Create a YAML file (for example `custom_frameworks.yaml`) that contains all of your frameworks.
- Point the module to the file by setting `REFINEMENT_FRAMEWORK_PATH`:
  - macOS/Linux `export REFINEMENT_FRAMEWORK_PATH=/absolute/path/custom_frameworks.yaml`
  - Windows PowerShell `$env:REFINEMENT_FRAMEWORK_PATH="C:\\path\\custom_frameworks.yaml"`
  - `.env` file `REFINEMENT_FRAMEWORK_PATH=/absolute/path/custom_frameworks.yaml`
- Reload at runtime with `registry.reload_from_env()` if you change the file while a process is running.

## 2. YAML File Anatomy

Each top-level key represents a framework name. The value is an ordered list of `RefinementAspect` definitions. Dependencies defined through `depends_on` automatically drive topological ordering at load time.

```yaml
my_framework:
  - id: population
    name: Target Population
    description: Define who the question is about
    analysis_prompt: |
      Analyze the following query and decide whether information about the population is missing.

      Query: {query}

      Consider demographics, clinical condition, and eligibility restrictions.
      Only ask for one clarification at a time.
```

### 2.1 Required fields for every aspect

| Field | Type | Purpose |
| --- | --- | --- |
| `id` | string | Stable identifier unique inside the framework |
| `name` | string | Human-readable label used in UIs/logs |
| `description` | string | Short explanation of what the aspect refines |
| `analysis_prompt` | string | Prompt template **must contain `{query}`** |

If `{query}` is missing the loader raises `ValueError` and the aspect is skipped.

### 2.2 Optional fields (add only what you need)

- `system_prompt` (string): Persona or role instructions injected as the system message when prompting the LLM. If you omit it, the manager falls back to a default prompt shown below.

#### Default system prompt (when `system_prompt` is omitted)

```text
You refine scientific queries by analyzing: {aspect.name} ({aspect.description}).
Determine if this aspect is missing, incomplete, or ambiguous. If yes, ask ONE specific question to clarify.
```

The manager substitutes `{aspect.name}` and `{aspect.description}` at runtime. Provide an explicit `system_prompt` when you need stricter tone, role-play, or domain vocabulary.

- `examples` (dict): Few-shot guidance, grouped by clarity category. Structure described in §4.
- `response_format` (dict): Structured response contract. Details in §3.
- `depends_on` (list[str]): IDs of earlier aspects this one needs context from. The manager passes previous answers in `dependency_context`.
- `allow_follow_up` (bool, default `false`): Whether the manager may ask multiple rounds.
- `max_follow_ups` (int, default `3`): Hard cap on follow-up rounds when enabled.
- `metadata` (dict): Free-form structured data for dependent logic (priority, domain, UI hints, etc.).

## 3. Response Format Contracts

The module always expects the base schema fields below and validates every LLM response against them:

| Field | Type | Notes |
| --- | --- | --- |
| `needs_refinement` | boolean | Required; instructs the manager to ask the user |
| `explanation` | string | Required; short diagnostic or acknowledgement |
| `suggested_question` | string | Required; single follow-up question or empty when not needed |

To extend the schema, supply `response_format.additional_fields` with allowed types `string`, `boolean`, `integer`, `float`, `array`, or `object`. Pair custom fields with user-facing descriptions via `response_format.field_descriptions`.

```yaml
response_format:
  additional_fields:
    priority: string
    confidence: float
  field_descriptions:
    priority: "Urgency level: high, medium, or low"
    confidence: "Self-reported confidence 0.0-1.0"
```

During prompting the manager synthesises a JSON example that merges the base schema and your additional fields, then lists field descriptions. `RefinementAspect.validate_response()` enforces types at runtime, so type mismatches immediately surface as validation failures.

See also `docs/response_format_guide.md` for deeper guidance and advanced validation patterns.

## 4. Example Library (Few-shot Guidance)

The `examples` field accepts any combination of five clarity categories. Each category is a list; every item must supply a `query` string and may add optional string metadata shown below.

| Category key | Optional fields |
| --- | --- |
| `clear` | `explanation`, `user_answer` |
| `needs_refinement` | `issue`, `missing`, `suggested_question`, `user_answer` |
| `partial` | `has`, `missing`, `suggested_question`, `user_answer` |
| `ambiguous` | `issue`, `suggested_question`, `user_answer` |
| `other` | `note`, `guidance`, `suggested_question`, `user_answer` |

Example:

```yaml
examples:
  clear:
    - query: Does aspirin reduce MI risk in adults with prior infarction?
      explanation: Specifies population, intervention, comparison, and outcome.
  needs_refinement:
    - query: Does aspirin reduce heart attack risk?
      issue: No population context or comparison group provided.
      suggested_question: "Which patient group and comparator should we focus on?"
  partial:
    - query: Compare metformin to placebo for cognition in older adults with diabetes.
      has: Population and comparison supplied.
      missing: Define cognitive outcome measure and timeframe.
      suggested_question: "Which cognitive assessment and follow-up horizon matter most?"
  ambiguous:
    - query: Evaluate new therapy for high-risk patients.
      issue: "High-risk" is undefined.
      suggested_question: "What criteria define high-risk in this context?"
  other:
    - query: Evaluate treatment outcomes for exactly 40-year-old women with postpartum depression.
      note: Hyper-specific qualifiers risk excluding useful evidence.
      guidance: Encourage the user to confirm whether a broader cohort (e.g., 30-45) is acceptable before proceeding.
```

The loader validates structure and types, logging warnings for unexpected keys so you can catch typos early.

## 5. Putting It All Together

### 5.1 Minimal two-aspect framework

```yaml
basic_project_scoping:
  - id: timeline
    name: Timeline
    description: Determine whether deadlines or milestones are specified.
    analysis_prompt: |
      Query: {query}

      Identify if a timeline is provided. If not, request a specific date range or deadline.
    allow_follow_up: true
    max_follow_ups: 2

  - id: budget
    name: Budget Constraints
    description: Check for financial limitations.
    analysis_prompt: |
      Query: {query}

      Decide whether budget parameters are defined; otherwise ask for a range.
    depends_on:
      - timeline
```

### 5.2 Comprehensive PICO-style aspect with dependencies

```yaml
pico_advanced:
  - id: population_core
    name: Population Fundamentals
    description: Capture demographic and clinical qualifiers for the study population.
    system_prompt: You specialize in clarifying population characteristics for evidence synthesis.
    analysis_prompt: |
      Evaluate whether the query clearly specifies the study population.

      Query: {query}

      Confirm age range, clinical condition, stage/severity, and notable inclusion/exclusion criteria.
      If one or more pillars are absent, return needs_refinement = true and propose a targeted question.
    examples:
      needs_refinement:
        - query: Does immunotherapy help lung cancer patients?
          issue: Cancer stage and biomarker status unknown.
          suggested_question: "Which lung cancer subtype, stage, and biomarker profile are relevant?"
    response_format:
      additional_fields:
        specificity_score: float
      field_descriptions:
        specificity_score: "0-1 score estimating how fully the population is defined."
    allow_follow_up: true
    max_follow_ups: 3
    metadata:
      domain: pico
      priority: critical

  - id: intervention_detail
    name: Intervention Detail
    description: Clarify exact intervention components, doses, and schedules.
    analysis_prompt: |
      Query: {query}

      Review the intervention description and confirm agent, dose, frequency, and delivery setting.
      Use dependency context to avoid asking about population again unless needed.
    depends_on:
      - population_core
    allow_follow_up: true
    metadata:
      domain: pico
      priority: high

  - id: outcome_measure
    name: Primary Outcome
    description: Determine the outcome metric and timeframe of interest.
    analysis_prompt: |
      Query: {query}

      Use dependency context when crafting clarifying questions.
    depends_on:
      - population_core
      - intervention_detail
    response_format:
      additional_fields:
        outcome_type: string
        time_horizon: string
      field_descriptions:
        outcome_type: "Clinical endpoint to evaluate (e.g., mortality, symptom score)."
        time_horizon: "Observation period or follow-up duration."
    allow_follow_up: false
```

This example demonstrates system prompts, example usage, dependencies, custom response fields, and metadata. Review `examples/pico_template.yaml` for the full production-ready framework shipped with the repository.

## 6. Dependency Semantics

- Declare `depends_on` using aspect IDs; only named dependencies appear in `session.get_dependency_context()` when the LLM analyzes subsequent aspects.
- The loader validates that dependencies reference existing IDs and raises if cycles are detected.
- Dependencies let you tailor follow-up prompts to earlier answers (see `docs/dependencies.md` for operational details).

## 7. Follow-up Behaviour

- `allow_follow_up: true` permits the manager to loop over `max_follow_ups` iterations until `needs_refinement` flips to `false`.
- Use metadata to signal UI hints (for example `metadata.follow_up_style: "checkbox"`). The core manager treats metadata as opaque.

## 8. Validation Lifecycle

At load time each aspect runs through several guards:

- Missing required fields or wrong types raise `ValueError` and skip the aspect.
- Invalid response format definitions (unknown types, inconsistent descriptions) raise immediately.
- Example collections must be dicts of lists; each entry must be a dict containing `query`.
- Dependency references are checked for existence; cycles throw `FrameworkLoadError`.

Review logs if dimensions vanish; the loader records every rejection with context. You can also call `registry.get_last_load_error()` to retrieve the most recent error string.

## 9. Prompt Crafting Tips

- Lead with the decision objective (“Determine if outcome detail is sufficient”).
- Enumerate considerations in bullet or numbered form to encourage structured reasoning.
- Spell out edge cases, especially known trouble spots for your domain.
- Close with explicit formatting instructions reflecting your response schema.
- Keep prompts concise; split a large aspect into multiple focused ones if the instructions exceed ~120 lines or combine unrelated tasks (see `examples/pico_population_subdimensions.yaml`).

## 10. Troubleshooting Checklist

- **Framework missing**: ensure `REFINEMENT_FRAMEWORK_PATH` is set, readable, and points to a file.
- **YAML parse error**: run `yamllint` or an online validator to catch indentation or colon issues.
- **Aspect skipped**: check logs for a validation error (missing `{query}`, wrong type, invalid dependency).
- **Unexpected LLM output**: verify `response_format` matches what you expect and adjust prompt instructions accordingly.
- **Dependency context empty**: confirm `depends_on` lists the exact IDs of input aspects and that they were processed earlier in the list.

## 11. Additional References

- `docs/response_format_guide.md` — deep dive on structured outputs and validation helpers.
- `docs/examples_field_reference.md` — additional suggestions for crafting example payloads.
- `docs/dependencies.md` — operational behaviour of dependency contexts in sessions.
- `examples/` directory — end-to-end sample frameworks you can copy and adapt.
