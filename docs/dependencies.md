# Dependency Management

Refinement frameworks can model prerequisite relationships between aspects so that subsequent prompts reuse answers gathered earlier in the conversation. This page explains how to declare those dependencies in YAML, how the loader validates and orders aspects, and how `QueryRefinementSession` uses the graph at runtime.

## 1. Declaring Dependencies in YAML

Attach a `depends_on` list to any `RefinementAspect` that requires context from other aspects in the same framework. Each entry must match the `id` of another aspect.

```yaml
pico_enhanced:
  - id: population
    name: Population
    description: Define who is being studied
    depends_on: []            # optional; omit when empty

  - id: intervention
    name: Intervention
    description: Clarify the treatment or exposure
    depends_on:
      - population           # can read population answers when prompting

  - id: outcome
    name: Outcome
    description: Identify the endpoints that matter
    depends_on:
      - population
      - intervention
```

Keep the list as small as possible—every declared dependency increases prompt size and invalidation surface area when users change answers.

## 2. Loader Validation and Ordering

`query_refinement_module.schema.registry` loads frameworks through `sort_aspects_by_dependencies`, which performs two checks:

1. **Missing references** (`validate_dependencies`) – raises `ValueError` if an aspect lists an ID that does not exist in the framework.
2. **Cycles** (`graphlib.TopologicalSorter`) – raises `ValueError` with a readable cycle description if the graph is not acyclic.

Only frameworks that pass both checks are registered. After validation, the loader returns aspects in topological order regardless of their appearance in the YAML file, so the manager always initializes prerequisites first.

```text
YAML order:   outcome, population, intervention
Runtime order: population → intervention → outcome
```

## 3. Runtime Context Injection

`QueryRefinementSession.get_dependency_context(aspect_id)` builds a context dictionary before each prompt. For every declared dependency that has either:

- a refined value (`final_response`), or
- was determined to be “already clear” during initialization,

the session injects a `{name, value}` pair. `QueryRefinementManager` then forwards that context into the prompt builder so the LLM receives a short preamble, for example:

```text
Previous refinements:
- Population: Adults aged 18-65 with major depressive disorder

Determine if the intervention/treatment/exposure is clearly specified.
```

No other aspects are included, which keeps prompts focused and token usage predictable.

## 4. Handling Missing or Stale Context

If a dependency has no value (for example, it was skipped), the manager logs a warning and continues without injecting that entry. Operators can decide whether to revisit the missing aspect manually.

Whenever a user revisits or rewrites an upstream answer (via `/back`, `/goto`, or by editing responses programmatically), the session invokes `_invalidate_dependents`. This method walks the dependency tree, marks every subsequent step as `needs_review=True`, and preserves the conversation history so the LLM can reconsider prior exchanges with the updated context.

```text
State: Population ✓ → Intervention ✓ → Outcome ✓
Command: /back
Effect: Population reopens, Intervention and Outcome flagged for review
```

`/goto <n>` behaves similarly: all steps from `<n>` onward are soft-reset to prevent stale data from leaking into later prompts.

## 5. Best Practices

- **Model intent, not order.** If an aspect can be analyzed in isolation, leave `depends_on` empty even if it happens to run later.
- **Prefer shallow graphs.** Branching (`population → {intervention, comparison}`) is easier to maintain than long chains where every aspect depends on the previous one.
- **Guard edge cases in tests.** `tests/test_registry.py` and `tests/test_manager.py` exercise dependency sorting and invalidation; mirror those patterns when introducing new frameworks.
- **Watch the logs.** Loader errors and runtime warnings include the affected IDs to help diagnose malformed YAML quickly.

## 6. Key APIs

```python
from query_refinement_module.schema.dependencies import sort_aspects_by_dependencies
from query_refinement_module.core import QueryRefinementSession

# Load-time topological ordering
sorted_aspects = sort_aspects_by_dependencies(aspects)

# Runtime context in the manager
context = session.get_dependency_context("intervention")

# Soft invalidation when upstream answers change
invalidated = session._invalidate_dependents("population")
```

Related sources: `query_refinement_module/schema/dependencies.py`, `query_refinement_module/core.py`, and `examples/pico_with_dependencies.yaml` demonstrate the complete workflow.
