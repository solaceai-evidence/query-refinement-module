# Custom Refinement Schemas

Design custom refinement frameworks in YAML so the module can orchestrate multi-step conversations tailored to your domain. This document reflects the current `query_refinement_module.schema` model and shows how to author validated schemas.

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
my_framework_1:
  - id: population
    aspect_name: Target Population
    aspect_description: Define who the question is about
    refinement_instructions: |
      # Analyze the following research input {input}:

      Determine whether information about the target population is missing.

      Consider demographics, clinical condition, and eligibility criteria.
      Request for one clarification at a time.
```

### 2.1 Required fields for every aspect

| Field                     | Type   | Purpose                                       |
| ------------------------- | ------ | --------------------------------------------- |
| `id`                      | string | Stable identifier unique inside the framework |
| `aspect_name`             | string | Human-readable label used in UIs/logs         |
| `aspect_description`      | string | Short explanation of what the aspect refines  |
| `refinement_instructions` | string | Prompt template for analysis instructions     |

The `refinement_instructions` may optionally include `{input}` as a placeholder. If present, the placeholder is replaced with the user's query at the specified location. If absent, the system automatically prepends `"Analyze this research input: {input}"` at the beginning of the prompt to ensure the LLM always has context about what it is analyzing.

### 2.2 Optional fields (add only what you need)

- `system_prompt` (string): Persona or role instructions injected as the system message when prompting the LLM. If you omit it, the chatbot falls back to a default prompt shown below.

#### Default system prompt (when `system_prompt` is omitted)

```text
You are a research advisor helping users refine their research topics by asking focused clarifying questions.

Your Job:
Users provide research interests (questions, statements, aims, or paragraphs). Clarify aspect: **{self.aspect_name}**, with definition: **{self.aspect_description}**. Focus ONLY on this aspect—ignore other research elements.

How to Engage:
1. **Acknowledge first**: Recognize what's already clear before requesting clarification.
2. **One element at a time**: Address 1-2 unclear points per turn.
3. **Mirror their language**: Use their terminology; avoid jargon unless it adds needed precision.
4. **Give examples**: Offer 2-4 concrete, aspect-specific examples they can adapt.
5. **Explain why**: Briefly note how this clarification strengthens their research input and improves their search.

When to Stop:
This aspect is sufficiently refined when the user's statement is specific, unambiguous, and actionable for evidence synthesis.

Boundaries:
- You clarify research descriptions, not search literature or write proposals.
- Stay within your assigned refinement aspect.
- Keep developing clarity, not fixing problems.

Tone: Supportive and collaborative. Be efficient—don't over-explain.
```

The system substitutes `{aspect.aspect_name}` and `{aspect.aspect_description}` at runtime. Provide an explicit `system_prompt` when you need stricter tone, role-play, or domain-specific vocabulary.

- `examples` (dict): Few-shot guidance, grouped by clarity category. Structure described in §4.
- `response_format` (dict): Structured response contract. Details in §3.
- `depends_on` (list[str]): IDs of earlier aspects this one needs context from. The chatbot passes previous answers in `dependency_context`.
- `allow_follow_up` (bool, default `true`): Whether the chatbot may ask multiple rounds of clarifying questions for this aspect.
- `max_follow_ups` (int, default `3`): Maximum number of follow-up rounds when enabled.
- `metadata` (dict): Free-form structured data for custom logic (priority, domain, UI hints, etc.).

## 3. Response Format Contracts

The module always expects the base schema fields below and validates every LLM response against them:

| Field              | Type    | Notes                                                                                      |
| ------------------ | ------- | ------------------------------------------------------------------------------------------ |
| `needs_refinement` | boolean | Required; instructs the chatbot to ask the user                                            |
| `explanation`      | string  | Required; short diagnostic or acknowledgement                                              |
| `example_question` | string  | Required; single follow-up question to clarify the specification, or empty when not needed |

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

During prompting the chatbot synthesises a JSON example that merges the base schema and your additional fields, then lists field descriptions. `RefinementAspect.validate_response()` enforces types at runtime, so type mismatches immediately surface as validation failures.

See also `docs/response_format_guide.md` for deeper guidance and advanced validation patterns.

## 4. Example Library (Few-shot Guidance)

The `examples` field accepts any combination of five clarity categories. Each category is a list where every item must include a `statement` field and may include optional metadata fields. Examples are formatted with bullet points and automatically ensure proper punctuation for improved readability.

| Category key       | Optional fields                        | Purpose                                                     |
| ------------------ | -------------------------------------- | ----------------------------------------------------------- |
| `clear`            | `rationale`                            | Examples demonstrating complete, unambiguous specifications |
| `needs_refinement` | `issue`, `missing`, `example_question` | Examples missing critical information                       |
| `partial`          | `has`, `missing`, `example_question`   | Examples with some but not all necessary details            |
| `vague_ambiguous`  | `issue`, `example_question`            | Examples with vague or unclear specifications               |
| `other`            | `note`, `guidance`, `example_question` | Edge cases or special guidance outside standard categories  |

Example:

```yaml
examples:
  clear:
    - statement: Does aspirin reduce MI risk in adults with prior infarction?
      explanation: Specifies population, intervention, comparison, and outcome.
  needs_refinement:
    - statement: Does aspirin reduce heart attack risk?
      issue: No population context or comparison group provided.
      example_question: "Which patient group and comparator should we focus on?"
  partial:
    - statement: Compare metformin to placebo for cognition in older adults with diabetes.
      has: Population and comparison supplied.
      missing: Define cognitive outcome measure and timeframe.
      example_question: "Which cognitive assessment and follow-up horizon matter most?"
  ambiguous:
    - statement: Evaluate new therapy for high-risk patients.
      issue: "High-risk" is undefined.
      example_question: "What criteria define high-risk in this context?"
  other:
    - statement: Evaluate treatment outcomes for exactly 40-year-old women with postpartum depression.
      note: Hyper-specific qualifiers risk excluding useful evidence.
      guidance: Encourage the user to confirm whether a broader cohort (e.g., 30-45) is acceptable before proceeding.
```

Examples are rendered in the prompt as formatted guidance with category headers (e.g., "CLEAR SPECIFICATIONS:", "NEEDS REFINEMENT:") followed by bulleted examples. The system automatically adds periods to field values that lack terminal punctuation, ensuring consistent formatting in the LLM prompt.

The loader validates structure and types at load time, raising errors for unknown category keys, missing `query` fields, or non-string field values.

## 5. Putting It All Together

### 5.1 Minimal two-aspect framework

```yaml
basic_project_scoping:
  - id: timeline
    aspect_name: Timeline
    aspect_description: Determine whether deadlines or milestones are specified.
    refinement_instructions: |
      Statement: {input}

      Identify if a timeline is provided. If not, request a specific date range or deadline.
    allow_follow_up: true
    max_follow_ups: 2

  - id: budget
    aspect_name: Budget Constraints
    aspect_description: Check for financial limitations.
    refinement_instructions: |
      Decide whether budget parameters are defined; otherwise ask for a range.
    depends_on:
      - timeline
```

Notice the `budget` aspect omits the `{input}` placeholder. The system automatically prepends `"Analyze this research input: <input>"` to ensure the LLM has the necessary context.

### 5.2 Comprehensive PICO-style aspect with dependencies

```yaml
pico_advanced:
  - id: population_core
    aspect_name: Population Fundamentals
    aspect_description: Capture demographic and clinical qualifiers for the study population.
    system_prompt: You specialize in clarifying population characteristics for evidence synthesis.
    refinement_instructions: |
      Evaluate whether the statement clearly specifies the study population.

      Statement: {input}

      Confirm age range, clinical condition, stage/severity, and notable inclusion/exclusion criteria.
      If one or more pillars are absent, return needs_refinement = true and propose a targeted question.
    examples:
      needs_refinement:
        - statement: Does immunotherapy help lung cancer patients?
          issue: Cancer stage and biomarker status unknown.
          example_question: "Which lung cancer subtype, stage, and biomarker profile are relevant?"
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
    aspect_name: Intervention Detail
    aspect_description: Clarify exact intervention components, doses, and schedules.
    refinement_instructions: |
      Statement: {input}

      Review the intervention description and confirm agent, dose, frequency, and delivery setting.
      Use dependency context to avoid asking about population again unless needed.
    depends_on:
      - population_core
    allow_follow_up: true
    metadata:
      domain: pico
      priority: high

  - id: outcome_measure
    aspect_name: Primary Outcome
    aspect_description: Determine the outcome metric and timeframe of interest.
    refinement_instructions: |
      Assess whether the query specifies measurable outcomes and follow-up duration.
      
      Statement: {input}
      
      Consider clinical endpoints, surrogate markers, and observation periods.
      Use dependency context from previous aspects to avoid redundant questions.
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
    metadata:
      domain: pico
      priority: high
```

This example demonstrates system prompts, examples usage, dependencies, custom response fields, and metadata integration. Consult `examples/pico_template.yaml` and `examples/pico_advanced_complete.yaml` for production-ready frameworks included with the repository.

## 6. Dependency Semantics

- Declare `depends_on` using aspect IDs; only named dependencies appear in `session.get_dependency_context()` when the LLM analyzes subsequent aspects.
- The loader validates that dependencies reference existing IDs and raises if cycles are detected.
- Dependencies let you tailor follow-up prompts to earlier answers (see `docs/dependencies.md` for operational details).

## 7. Follow-up Behaviour

Follow-ups are enabled by default (`allow_follow_up: true`) with a limit of 3 rounds (`max_follow_ups: 3`). When enabled, the chatbot iteratively prompts the LLM for clarification until either:

- The LLM sets `needs_refinement` to `false`, indicating the aspect is sufficiently specified
- The maximum number of follow-up rounds is reached

Follow-up prompts automatically include:

- The original query (ensuring consistent context across all rounds)
- Conversation history for the aspect
- The user's most recent answer
- The aspect's analysis instructions and examples

Set `allow_follow_up: false` to disable iterative refinement for aspects requiring only a single assessment. Use metadata fields like `metadata.follow_up_style: "checkbox"` for UI-specific hints; the core chatbot treats metadata as opaque.

## 8. Validation Lifecycle

At load time, each aspect undergoes validation:

- **Required fields**: Missing `id`, `aspect_name`, `aspect_description`, or `refinement_instruction` raises `ValueError`.
- **Response format**: Invalid type specifications (types not in `string`, `boolean`, `integer`, `float`, `array`, `object`) or malformed structures raise errors immediately.
- **Examples structure**: Must be a dictionary of lists; each example requires a `statement` field. Unknown category keys or non-string field values trigger validation errors.
- **Dependencies**: References to non-existent aspect IDs or circular dependencies raise `FrameworkLoadError`.

If an aspect fails validation, the loader logs the error with context and skips that aspect. Call `registry.get_last_load_error()` to retrieve the most recent error message programmatically.

## 9. Prompt Crafting Best Practices

- **State the objective clearly**: Begin with the analysis goal (e.g., "Determine if the temporal scope is adequately specified").
- **Structure guidance systematically**: Use numbered lists or bullet points to enumerate evaluation criteria, encouraging methodical reasoning.
- **Address domain-specific edge cases**: Explicitly mention known ambiguities or pitfalls relevant to your field.
- **Leverage automatic query injection**: Include `{input}` where it fits naturally in your prompt flow, or omit it entirely to have the system prepend it automatically.
- **Keep prompts focused**: If analysis instructions exceed ~120 lines or combine orthogonal concerns, split into multiple targeted aspects (see `examples/pico_population_subdimensions.yaml`).
- **Avoid redundant format instructions**: The system automatically appends JSON format specifications based on your `response_format`, so focus your prompt on refinement instructions rather than output structure.

## 10. Troubleshooting Checklist

- **Framework missing**: ensure `REFINEMENT_FRAMEWORK_PATH` is set, readable, and points to a valid file.
- **YAML parse error**: run `yamllint` or an online validator to catch indentation or colon issues.
- **Aspect skipped**: check logs for validation errors (missing required fields, wrong types, invalid dependencies, or malformed response formats).
- **Unexpected LLM output**: verify `response_format` matches your expectations and adjust prompt instructions accordingly.
- **Dependency context empty**: confirm `depends_on` lists the exact IDs of prerequisite aspects and that they were processed earlier in the framework definition.

## 11. Additional References

- `docs/response_format_guide.md` — deep dive on structured outputs and validation helpers.
- `docs/examples_field_reference.md` — additional suggestions for crafting example payloads.
- `docs/dependencies.md` — operational behaviour of dependency contexts in sessions.
- `examples/` directory — end-to-end sample frameworks you can copy and adapt.
