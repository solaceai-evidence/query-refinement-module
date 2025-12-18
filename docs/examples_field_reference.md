# Examples Field Reference

`RefinementAspect.examples` accepts an `ExamplesDict` that provides few-shot guidance for the LLM. Each category is optional, but every example must contain a `statement` string. All other fields are strings as well and will be validated at load time.

## 1. Category Cheat Sheet

| Category | Typical Use | Optional Fields |
| --- | --- | --- |
| `clear` | Fully specified queries the model should accept as-is | `rationale` |
| `needs_refinement` | Queries missing critical detail | `issue`, `missing`, `example_question` |
| `partial` | Queries with some detail but notable gaps | `has`, `missing`, `example_question` |
| `vague_ambiguous` | Queries containing vague or conflicting language | `issue`, `example_question` |
| `other` | Edge cases or guidance that do not cleanly fit the buckets above | `note`, `guidance`, `example_question` |

## 2. Examples by Category

All snippets below are valid. The loader will reject anything that omits `statement`, provides non-string values, or introduces unexpected keys.

```yaml
examples:
  clear:
    - statement: "Efficacy of metformin in adults aged 40-65 with BMI > 30"
      rationale: "Age, BMI, and clinical population are all explicit."

  needs_refinement:
    - statement: "Does exercise help with depression in adults?"
      issue: "'Adults' spans 18-80+ and setting is unspecified."
      example_question: "Which age range and care setting should we target?"

  partial:
    - statement: "Effects of diet intervention in women over 40"
      has: "Gender and minimum age are supplied."
      missing: "Upper age limit and geographic scope."
      example_question: "Do you want to focus on a specific age band or region?"

  vague_ambiguous:
    - statement: "Intervention effectiveness in middle-aged adults"
      issue: "'Middle-aged' is subjective; clarify the numeric range."
      example_question: "What exact ages define 'middle-aged' for this study?"

  other:
    - statement: "Effectiveness of mindfulness training for exactly 40-year-old women with postpartum depression"
      note: "Hyper-specific demographic filters can shrink the candidate evidence base to almost nothing."
      guidance: "Confirm whether such granularity is really needed at the discovery stage or if a broader band (e.g., women 30-45) would be acceptable."
      example_question: "Should we widen the age range or related qualifiers to capture more literature?"
```

## 3. Validation Rules (Applied on Load)

- Categories must be one of `clear`, `needs_refinement`, `partial`, `vague_ambiguous`, or `other`.
- Each category value must be a list of dicts.
- Each dict must contain `statement` and every value must be a string.
- Unexpected keys trigger a warning (logged once per occurrence) so typos are easy to spot while remaining non-blocking.

If validation fails, the framework loader logs the offending aspect and rejects that example payload so you can fix the YAML before reloading.

## 4. Prompt Formatting Tips

- Provide at least two examples per active category to illustrate different failure modes.
- Mix `issue`/`missing` with `example_question` so the LLM sees both diagnosis and remediation patterns.
- Use realistic domain vocabulary; these examples are injected verbatim into prompts.

For a complete end-to-end schema, review `examples/pico_advanced_complete.yaml`, which showcases all categories alongside dependency-aware prompts.
