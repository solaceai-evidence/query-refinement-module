# Dependency Management

Refinement frameworks support explicit dependencies between aspects so later dimensions can reason with the context produced by earlier ones. This guide covers authoring dependency graphs in YAML, the validation performed during framework loading, and the runtime behaviors that keep sessions consistent.

## Declaring Dependencies in YAML

Use the `depends_on` array on each `RefinementAspect`. List only the aspect identifiers that provide essential context for the current dimension.

```yaml
pico_enhanced:
  - id: population
    name: Population
    description: Define who is being studied
    depends_on: []

  - id: intervention
    name: Intervention
    description: Clarify the treatment or exposure
    depends_on: [population]

  - id: outcome
    name: Outcome
    description: Identify the endpoints that matter
    depends_on: [population, intervention]
```

When the framework is loaded through `query_refinement_module.schema.registry`, the dependency graph is validated and sorted so that `population` initializes first, `intervention` second, and `outcome` last.

## Load-Time Validation

Validation happens in `query_refinement_module.schema.dependencies.validate_dependencies` before the framework is accepted.

```yaml
# ✅ Linear chain
- id: a
  depends_on: []
- id: b
  depends_on: [a]
- id: c
  depends_on: [b]

# ❌ References missing node (raises ValueError)
- id: population
  depends_on: [nonexistent]
```

`sort_aspects_by_dependencies` runs after validation using `graphlib.TopologicalSorter`. Any cycle raises a `ValueError` with a readable explanation, keeping invalid frameworks out of the registry.

## Dependency-Aware Ordering

The manager always processes aspects in topological order. Regardless of how YAML is arranged, runtime execution becomes deterministic:

```text
Input order:   outcome, population, intervention
Sorted order:  population → intervention → outcome
```

Only aspects whose declared dependencies are complete (either refined or already clear) are eligible for processing.

## Runtime Context Injection

`QueryRefinementSession.get_dependency_context` collects final values for each dependency and passes them to `QueryAspectRefiner.get_prompts`. The user prompt receives a concise preamble so the LLM can reason with prior answers.

```text
Previous refinements:
- Population: Adults aged 18-65 with major depressive disorder

Determine if the intervention/treatment/exposure is clearly specified.
```

Context is only added for declared dependencies, preserving tokens and keeping prompts focused.

## Missing Context

If a dependency was skipped or never answered, the manager logs a warning similar to:

```text
refinement aspect 'intervention' depends on ['population'] but they have no values. Continuing without that context.
```

Processing continues so that human operators can decide how to resolve the gap.

## Cascade Invalidation

Navigating backwards automatically marks dependents for review. `QueryRefinementSession._invalidate_dependents` walks the dependency tree and sets `needs_review=True` while preserving conversation history.

```text
State: Population ✓ → Intervention ✓ → Outcome ✓
Command: /back
Result: Population reopened, Intervention and Outcome flagged for review
```

`/goto <step>` performs the same invalidation for the target step and every downstream aspect, ensuring new answers never rely on stale context.

## Best Practices

- Declare only the dependencies you truly need; avoid `depends_on: []` on aspects that clearly rely on upstream answers.
- Keep chains shallow. Prefer branching graphs (`population → {intervention, comparison}`) over long linear pipelines.
- Use dependencies to express domain logic, not presentation order. If an aspect can be reasoned about independently, leave `depends_on` empty.
- Iterate on frameworks with tests. `examples/test_dependencies.py` demonstrates expected ordering, validation failures, and missing-context warnings.

## Reference Implementation

Key functions and classes involved in dependency management:

```python
from query_refinement_module.schema.dependencies import sort_aspects_by_dependencies
from query_refinement_module.core import QueryRefinementSession

# Topological sorting during framework load
def load_framework(aspects):
    return sort_aspects_by_dependencies(aspects)

# Context building at runtime
session = QueryRefinementSession(original_query="...")
context = session.get_dependency_context(target_refinement_aspect_id="intervention")

# Cascade invalidation when answers change
session._invalidate_dependents(changed_refinement_aspect_id="population")
```

## Related Files

- `query_refinement_module/schema/dependencies.py`
- `query_refinement_module/core.py`
- `examples/pico_with_dependencies.yaml`
- `examples/test_dependencies.py`
