# Response Format Guide

Every `RefinementAspect` automatically expects three base fields in the LLM response:

| Field | Type | Description |
| --- | --- | --- |
| `needs_refinement` | boolean | Whether the aspect still requires clarification |
| `explanation` | string | Short justification for the decision |
| `clarifying_question` | string | Follow-up question to ask (use an empty string when no refinement is needed) |

You do not need to mention these in your prompt; the manager always appends them to the generated instructions. The `response_format` section lets you extend the schema with additional fields without polluting the analysis prompt itself.

## 1. Why separate analysis and format?

- Prompts stay focused on the reasoning workflow.
- All aspects share the same baseline expectations, which simplifies validation.
- Updating the shape of the response no longer requires touching the prompt text.
- Tests can programmatically validate the JSON payload before it moves deeper into the pipeline.

## 2. Anatomy of `response_format`

`response_format` is an optional dictionary with two key parts:

```yaml
response_format:
  additional_fields:
    confidence: float
    priority: string
  field_descriptions:
    confidence: "Confidence score between 0.0 and 1.0 (optional)."
    priority: "Relative urgency: low, medium, high."
```

- **`additional_fields`** – map of field name ➝ type. Allowed types match the validator: `string`, `boolean`, `integer`, `float`, `array`, `object` (case-insensitive).
- **`field_descriptions`** – human-readable hints appended to the prompt. Keys should match the additional fields; extra entries simply trigger a warning.

Any other keys (for example `type` for documentation) are ignored by the validator but can be left in place if you find them helpful for readability.

## 3. Generated Instructions

When you call `RefinementAspect.get_user_prompt(...)`, the manager appends something like the following to your analysis prompt:

```text
Respond in the following JSON format:
```

```json
{
  "needs_refinement": <boolean>,
  "explanation": "<string>",
  "clarifying_question": "<string>",
  "confidence": <float>,
  "priority": "<string>"
}
```

Field descriptions:

- confidence (float) (optional): Confidence score between 0.0 and 1.0 (optional).
- priority (string) (optional): Relative urgency: low, medium, high.


The prompt always lists the base fields first, then the additional ones you declared, and tags everything that came from `additional_fields` as optional.

## 4. End-to-End Example

```yaml
- id: temporal_scope
  name: Temporal Scope
  description: Clarifies time period or timeframe
  refinement_instructions: |
    Analyze temporal clarity in the following query:

    Query: {query}

    Look for explicit ranges, ambiguous words like "recent", and implied periods.
    Decide if clarification is needed and propose exactly one follow-up question when it is.

  response_format:
    additional_fields:
      confidence: float
      detected_terms: array
    field_descriptions:
      confidence: "Confidence score 0.0-1.0 for the refinement decision."
      detected_terms: "Temporal expressions found in the query (if any)."

  allow_follow_up: true
  max_follow_ups: 2
```

At runtime, responses must include the base keys plus any optional extras you choose to emit. `RefinementAspect.validate_response()` ensures types line up and surfaces helpful error messages if values are missing or of the wrong type.

## 5. Validation Rules

`RefinementAspect._validate_response_format_structure()` runs during framework loading:

- `additional_fields` must be a dictionary of string → string.
- Types must belong to the allowed set (`string`, `boolean`, `integer`, `float`, `array`, `object`).
- `field_descriptions`, when present, must be a dictionary. Extra description keys trigger a warning but do not prevent loading.

During execution `validate_response()` enforces:

- All base fields exist and have the correct Python types (`bool` for `needs_refinement`, `str` for `explanation` and `clarifying_question`).
- Additional fields that appear in the LLM payload match the declared types. Unexpected fields are permitted but noted by `validate_response_strict()` as warnings.

## 6. Recommended Standard Payload

For most dimensions, a minimal yet informative extension is:

```yaml
response_format:
  additional_fields:
    confidence: float
  field_descriptions:
    confidence: "Confidence score between 0.0 (low) and 1.0 (high)."
```

This keeps schemas consistent, enables UI prioritization, and adds little extra weight to prompts.

## 7. Working with the API

```python
from query_refinement_module.schema.model import RefinementAspect

aspect = RefinementAspect.from_dict(yaml_payload)
system_prompt, user_prompt = aspect.get_prompts(query)

# After the LLM responds
payload = llm_response.json()
is_valid, error = aspect.validate_response(payload)
```

For complete YAML examples, check `examples/custom_schemas_with_response_format.yaml` and `examples/pico_advanced_complete.yaml`, both of which showcase complex domain-specific fields layered on top of the shared base schema.
