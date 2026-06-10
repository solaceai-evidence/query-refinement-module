# Plan: End-to-End Pipeline Audit And Legacy Cleanup

Audit the full query-refinement and synthesis pipeline end-to-end, then simplify it by removing or consolidating legacy and duplicated paths. The goal is to end up with one authoritative runtime path for refinement prompts, one authoritative runtime path for synthesis/search generation, one canonical schema contract, and one consistent example/template rendering contract across all layers.

## Audit goals

- Identify every runtime and non-runtime path that constructs prompts, validates outputs, maps schemas, persists results, or serves API responses.
- Mark which surfaces are authoritative, which are compatibility layers, and which are likely dead or redundant.
- Remove or consolidate legacy paths only after cross-file contract checks and tests are aligned.
- Leave the system with one canonical source of truth per concern: framework schema, prompt rendering, synthesis building, response schema, persistence mapping, and template variant selection.

## Phases

- Phase 1: Runtime-path mapping and canonical-path decisions.
- Phase 2: Refinement pipeline audit and cleanup plan.
- Phase 3: Synthesis pipeline audit and cleanup plan.
- Phase 4: Schema/template/test alignment audit.
- Phase 5: Decommissioning plan.

## Steps

Map the live refinement runtime path file-by-file:

- query_refinement_module/api/routes/refinement.py
- query_refinement_module/core.py
- query_refinement_module/session_models.py
- query_refinement_module/schema/prompt_builder.py
- query_refinement_module/schema/templates/dimension.py
- query_refinement_module/schema/registry.py
- refinement_frameworks/frameworks.yaml
- Audit duplicated refinement prompt construction paths:

- compare the live Jinja path in prompt_builder.py and dimension.py
against the older formatter path in models.py
and the service facade in service.py

## Audit synthesis prompt construction and orchestration:

query_refinement_module/schema/synthesis.py
query_refinement_module/schema/prompt_builder.py
query_refinement_module/schema/templates/synthesis.py
query_refinement_module/core.py
Audit response schema and persistence mappings across:

query_refinement_module/schema/response.py
query_refinement_module/db/crud.py
query_refinement_module/db/models/query.py
query_refinement_module/api/routes/refinement.py
Audit schema/example alias handling across:

query_refinement_module/schema/models.py
query_refinement_module/schema/prompt_builder.py
query_refinement_module/schema/templates/dimension.py
refinement_frameworks/frameworks.yaml

## Audit template-variant selection and user-context rendering:

query_refinement_module/schema/templates/init.py
query_refinement_module/schema/templates/global_system.py
query_refinement_module/schema/templates/global_system_open_llm.py
query_refinement_module/schema/templates/user_context.py
query_refinement_module/schema/templates/user_context_open_llm.py

## Audit API/session/service cross-file overlaps:

query_refinement_module/api/routes/refinement.py
query_refinement_module/api/session_manager.py
query_refinement_module/service.py
query_refinement_module/session_models.py

## Audit test coverage and documentation assumptions:

tests/unit/test_split_synthesis.py
tests/unit/test_enhanced_synthesis.py
tests/api/test_synthesis_flow.py
tests/unit/test_template_variant_selection.py
tests/unit/test_template_model_alignment.py
tests/test_message_structure.py
tests/unit/test_synthesis_prompt.py
tests/unit/test_schema_synthesis.py
docs/API.md
docs/OPEN_LLM_PROMPT_REVISION_PLAN.md

## Produce a decommissioning order for legacy code. Likely targets:

- legacy synthesis builder surfaces in query_refinement_module/schema/synthesis.py
- legacy prompt methods in query_refinement_module/schema/prompt_builder.py
- older formatter helpers in query_refinement_module/schema/models.py, if no longer needed
- duplicate next-prompt builders in query_refinement_module/service.py
- stale compatibility aliases in query_refinement_module/schema/response.py
- Define cross-file consistency gates that must pass before and after cleanup:

framework YAML → registry → model parsing → prompt rendering
refinement response schema → persistence mapping → API response
synthesis prompt builder → orchestration → response model
template selection → message structure → open/private variant behavior

## Key decisions

- Optimize for one canonical runtime path per concern, not just local file cleanup.
- Remove legacy code only after a canonical replacement is identified and covered by tests.
- Treat cross-file contracts as first-class audit targets.
- Keep backward compatibility temporarily only where persistence or public APIs require it, and classify each case explicitly.

## High-priority risks

- Duplicate refinement and synthesis builders
- Large route/core functions hiding duplicate logic
- Schema alias drift across response, persistence, and API layers
- Template/model drift across example categories and variant selection
- Tests/docs still asserting old paths and field names