# Framework Authoring

Frameworks are defined in YAML and loaded from `REFINEMENT_FRAMEWORK_PATH`.
Default location: `./refinement_frameworks/frameworks.yaml`.

The current framework format is designed for non-technical editing as well as advanced customization. A framework can begin with an optional `user_context` block, followed by the questions or dimensions that should be refined.

## Current Fields

Each dimension should include:

- `id`
- `name`
- `description`
- `specifications`

Optional fields:

- `strictness`
- `depends_on`
- `examples`
- `response_format`
- `allow_follow_up`
- `max_follow_ups`
- `metadata`

The optional `user_context` block can include:

- `user_type`
- `context`
- `tone`
- `complexity`
- `examples_from`
- `constraints`
- `pitfalls`

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
      Analyze the input: {query}
      Identify the target population.
```

## Tips

- Keep each dimension focused on one topic.
- Use `depends_on` to avoid repeating earlier questions.
- Use `examples` when you want the system to recognise common patterns.
- Put the most important context in `user_context` so the app can adapt the wording for the intended audience.
