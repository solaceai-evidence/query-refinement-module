# Examples Field Reference

`RefinementAspect.examples` accepts an `ExamplesDict` that provides few-shot guidance for the LLM. Each category is optional, but every example must contain a `query` string. All other fields are strings as well and will be validated at load time.

## 1. Category Cheat Sheet

| Category | Typical Use | Optional Fields |
| --- | --- | --- |
| `clear` | Fully specified queries the model should accept as-is | `explanation`, `user_answer` |
| `needs_refinement` | Queries missing critical detail | `issue`, `missing`, `suggested_question`, `user_answer` |
| `partial` | Queries with some detail but notable gaps | `has`, `missing`, `suggested_question`, `user_answer` |
| `ambiguous` | Queries containing vague or conflicting language | `issue`, `suggested_question`, `user_answer` |
| `other` | Edge cases or guidance that do not cleanly fit the buckets above | `note`, `guidance`, `suggested_question`, `user_answer` |

`user_answer` is especially helpful for providing context in examples, as it shows both the suggested question and a sample answer to illustrate the expected exchange.

## 2. Examples by Category

All snippets below are valid—the loader will reject anything that omits `query`, provides non-string values, or introduces unexpected keys.

```yaml
examples:
  clear:
    - query: "Efficacy of metformin in adults aged 40-65 with BMI > 30"
      explanation: "Age, BMI, and clinical population are all explicit."

  needs_refinement:
    - query: "Does exercise help with depression in adults?"
      issue: "'Adults' spans 18-80+ and setting is unspecified."
      clarifying_question: "Which age range and care setting should we target?"

  partial:
    - query: "Effects of diet intervention in women over 40"
      has: "Gender and minimum age are supplied."
      missing: "Upper age limit and geographic scope."
      clarifying_question: "Do you want to focus on a specific age band or region?"

  ambiguous:
    - query: "Intervention effectiveness in middle-aged adults"
      issue: "'Middle-aged' is subjective; clarify the numeric range."
      clarifying_question: "What exact ages define 'middle-aged' for this study?"

  other:
    - query: "Effectiveness of mindfulness training for exactly 40-year-old women with postpartum depression"
      note: "Hyper-specific demographic filters can shrink the candidate evidence base to almost nothing."
      guidance: "Confirm whether such granularity is really needed at the discovery stage or if a broader band (e.g., women 30-45) would be acceptable."
      clarifying_question: "Should we widen the age range or related qualifiers to capture more literature?"
```

## 3. Python Typing Helpers

For strongly typed authoring and auto-completion, the schema exposes lightweight TypedDicts:

```python
from query_refinement_module.schema.model import (
    ClearExample,
    NeedsRefinementExample,
    PartialExample,
    AmbiguousExample,
  OtherExample,
    ExamplesDict,
)

sample: ExamplesDict = {
    "partial": [
        PartialExample(
            query="Compare statins in adults",
            has="Intervention is clear",
            missing="Population age band",
            suggested_question="Which age range for adults?"
        )
  ],
  "other": [
    OtherExample(
      query="Outcomes for exactly 40-year-old women with hypertension",
      note="Overly narrow age filters can exclude relevant adjacent cohorts.",
      guidance="Ask if the researcher is open to a broader decade-based age band before proceeding."
    )
  ]
}
```

## 4. Validation Rules (Applied on Load)

- Categories must be one of `clear`, `needs_refinement`, `partial`, `ambiguous`, or `other`.
- Each category value must be a list of dicts.
- Each dict must contain `query` and every value must be a string.
- Unexpected keys trigger a warning (logged once per occurrence) so typos are easy to spot while remaining non-blocking.

If validation fails, the framework loader logs the offending aspect and rejects that example payload so you can fix the YAML before reloading.

## 5. Prompt Formatting Tips

- Provide at least two examples per active category to illustrate different failure modes.
- Mix `issue`/`missing` with `suggested_question` so the LLM sees both diagnosis and remediation patterns.
- Use realistic domain vocabulary; these examples are injected verbatim into prompts.
- Include `user_answer` when you want to demonstrate ideal user responses for coaching-style prompts.

For a complete end-to-end schema, review `examples/pico_advanced_complete.yaml`, which showcases all categories alongside dependency-aware prompts.
