# Framework Authoring

Frameworks are defined in YAML and loaded from `REFINEMENT_FRAMEWORK_PATH`.
Default location: `./refinement_frameworks/frameworks.yaml`.

## Required Fields

Each aspect requires:

- `id`
- `aspect_name`
- `aspect_description`
- `refinement_instructions`

## Optional Fields

- `system_prompt`
- `examples`
- `response_format`
- `depends_on`
- `allow_follow_up`
- `max_follow_ups`
- `metadata`

## Minimal Example

```yaml
basic_framework:
  - id: population
    aspect_name: Population
    aspect_description: Who is being studied
    refinement_instructions: |
      Analyze the input: {input}
      Identify the target population.
```

## Tips

- Keep aspect instructions focused on one topic.
- Use `depends_on` to avoid repeating earlier questions.
- Use `examples` for common cases.
