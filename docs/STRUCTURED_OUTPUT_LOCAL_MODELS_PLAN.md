# Structured Output Strategy for Local Models

## Purpose

This document is a living design note for improving structured-output reliability when running the query refinement system with local or self-hosted open-source / open-weight LLMs.

It is not a final implementation guide. Its purpose is to:

- describe the current structured-output architecture
- identify where the current design places too much schema burden on the model
- compare architectural options for reducing that burden
- define the evidence required before choosing a final approach

## Scope

In scope:

- structured-output architecture for dimension evaluation and final synthesis
- local-model fit for the current workflow
- schema burden reduction strategies
- decision criteria for comparing candidate approaches

Out of scope for now:

- final model selection (deferred until the synthesis architecture is stabilised)
- provider migration
- changes to per-dimension refinement or non-synthesis pipeline (see Implementation Guardrail)

Note: this document lives on a feature branch where synthesis-only implementation is the next active work. Synthesis-scoped code changes are in scope once the prerequisite gate defined below is cleared.

## Current Problem Statement

The project depends on structured output in two distinct places:

1. Per-dimension refinement, where the model returns a very small schema.
2. Final synthesis, where the model returns a large nested schema that mixes multiple tasks into one response.

This distinction matters because smaller local models often fail not on context length, but on the combination of:

- nested JSON generation
- multiple semantic sub-tasks in one call
- strict field-level consistency across related output sections

The current synthesis path asks the model to do all of the following in one response:

- restate the integrated research question
- preserve dimension values in a structured map
- generate semantic search wording
- generate a Boolean query
- generate phrase lists and term buckets
- infer or normalize search filters
- generate terminology expansions

That makes the synthesis call significantly more fragile than the per-dimension evaluation call, especially for local 7B to 14B models.

## Current Architecture

### Canonical schema surfaces

- `query_refinement_module/schema/response.py`
  - `DimensionEvaluationResponse` is the per-dimension schema.
  - `QueryRefinementResponse` is the synthesis schema.

### Prompt contract

- `query_refinement_module/schema/templates/synthesis.py`
  - defines the synthesis prompt and expected JSON structure
  - currently carries a large amount of formatting and retrieval logic

### Orchestration and validation

- `query_refinement_module/core.py`
  - builds prompts for synthesis
  - calls the provider with `response_format=QueryRefinementResponse`
  - validates and parses the structured response
  - assembles the result payload returned to the rest of the application

### Provider behavior

- `query_refinement_module/providers/llm.py`
  - supports `response_format`
  - uses native structured output where supported
  - uses vLLM `guided_json` constrained decoding when enabled

### Documented operational behavior

- `README.md`
- `docs/OPERATIONS.md`
- `docs/DEPLOYMENT.md`
- `docs/API.md`

These files describe provider choices, local deployment behavior, and structured-output expectations.

## Immediate Architectural Risk: Prompt-Schema Drift

The current synthesis template and the canonical response model are not fully aligned.

Examples of drift to track:

- the synthesis template asks for `research_elements`
- the synthesis template asks for `terminology.hyponyms`
- the current `QueryRefinementResponse` model instead includes `grey_literature`
- the current `Terminology` model includes `primary_terms`, `domain_specific`, and `colloquial`

This is a first-order design issue. Any future model comparison will be misleading if the system prompt and the Pydantic schema are already asking for different things.

## Prerequisite Decision Gate: Align Contract Before Comparing Architectures

Prompt-schema alignment is not just one workstream among many.

It is the entry condition for any meaningful architecture comparison.

Before comparing monolithic synthesis, split synthesis, repair loops, or intermediate representations, the system must first define one canonical synthesis contract and make the prompt, response schema, validation logic, and documented examples agree with it.

Minimum alignment requirements:

- one canonical field set for synthesis output
- one canonical meaning for each field
- one canonical null or empty-value convention for each field
- one canonical owner for each field: deterministic assembler, rule engine, LLM, or hybrid pipeline
- one consistent example output that matches the actual schema

If this gate is not satisfied first, any benchmark or architecture comparison will mix together:

- model weakness
- prompt ambiguity
- schema mismatch
- downstream parsing behavior

That would make the evaluation results difficult to trust.

### Gate Exit Criteria

The alignment gate is satisfied when all five of the following artifacts exist and are independently verifiable:

1. A written canonical synthesis contract that names every output field, its type, its null/empty representation, and its assigned owner.
2. `query_refinement_module/schema/response.py` (`QueryRefinementResponse`) matches the contract exactly: no extra fields, no missing fields, no aliased ambiguity between prompt field names and model field names.
3. `query_refinement_module/schema/templates/synthesis.py` requests only fields present in the contract, using canonical field names and consistent null/empty conventions throughout.
4. At least two worked examples that cover different framework types and that are fully valid when parsed against the Pydantic schema.
5. A `pytest` test that loads those examples and confirms they parse cleanly against the current schema.

No architecture comparison, benchmark run, or implementation work should begin until all five are in place.

## Field-by-Field Decomposition of the Synthesis Output

The first decision surface is not model choice. It is deciding which fields truly require generation.

| Output area                                       | Current role                                        | Recommended classification        | Notes                                                                                         |
| ------------------------------------------------- | --------------------------------------------------- | --------------------------------- | --------------------------------------------------------------------------------------------- |
| `integrated_statement`                            | Integrates original query with clarified dimensions | LLM-dependent                     | Requires careful language control and user-term preservation                                  |
| `dimensions_specifications`                       | Structured map of final dimension values            | Deterministic                     | Should be assembled from session state, preserving order and mapping skipped values to `null` |
| `search_optimized.semantic`                       | Natural-language retrieval query                    | LLM-dependent                     | Compact reasoning/generation task                                                             |
| `search_optimized.keyword.structured`             | Boolean query                                       | Hybrid                            | Could be generated by the LLM or compiled from a smaller intermediate representation          |
| `search_optimized.keyword.phrases`                | Exact phrase list                                   | Hybrid                            | Can be partly generated, partly extracted                                                     |
| `search_optimized.keyword.terms`                  | Required / optional / excluded term buckets         | Hybrid                            | Some buckets may be rule-derived; others need lexical judgment                                |
| `search_filters.publication_years`                | Temporal filter                                     | Rule-based                        | Often derivable from explicit phrases like "recent" or explicit year ranges                   |
| `search_filters.venues`                           | Venue filter                                        | Deterministic                     | Populate only when explicitly stated                                                          |
| `search_filters.authors`                          | Author filter                                       | Deterministic                     | Populate only when explicitly stated                                                          |
| `search_filters.publication_types`                | Study-design filter                                 | Rule-based                        | Can often be derived from dimension values                                                    |
| `search_filters.fields_of_study`                  | Disciplinary filter                                 | Hybrid                            | Sometimes derivable, sometimes needs judgment                                                 |
| `terminology.synonyms`                            | Retrieval variants                                  | LLM-dependent or retrieval-backed | Good candidate for curated or ontology-backed support                                         |
| subtype expansion if retained in canonical schema | Recall expansion                                    | LLM-dependent or retrieval-backed | Not part of the current canonical contract unless the prerequisite gate explicitly keeps it   |
| `grey_literature`                                 | Alternative retrieval framing                       | Hybrid                            | Canonical field name must remain `grey_literature` unless the schema is intentionally changed |

For implementation planning below, the canonical field names are the names in `QueryRefinementResponse` after the prerequisite gate is cleared. Placeholder labels such as "equivalent" or legacy names such as `terminology.hyponyms` must not appear in any new prompt, validator, or split-call schema unless the schema is intentionally changed first.

## Field Ownership Contract Required Before Implementation

The decomposition above is still not enough to guide implementation safely.

Before any code work begins, each synthesis field should have an explicit ownership contract with these properties:

- source of truth
- producing component
- transformation rules
- null or empty semantics
- conflict-resolution rule when deterministic evidence and generated output disagree

The contract below is the implementation-facing version of that ownership model. If any later section disagrees with this matrix, this matrix wins and the later section should be updated.

| Field                                 | Source of truth                                           | Primary producer        | Transformation rule                                                                                                                                                                                                                                                                                                           | Null or empty semantics                                                                                                       | Conflict rule                                            |
| ------------------------------------- | --------------------------------------------------------- | ----------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------- |
| `dimensions_specifications`           | completed refinement session state                        | deterministic assembler | Iterate session steps in framework order. If `was_skipped`, emit `null`; else if `normalized_value` is present, emit `normalized_value_as_str`; else emit `null`. Every framework dimension must be present as a key.                                                                                                         | never omit a dimension key; skipped or unresolved values are `null`                                                           | deterministic state wins                                 |
| `integrated_statement`                | original query plus accepted dimension values             | LLM                     | Generate only from canonical synthesis input and assembled `dimensions_specifications`. Must preserve accepted constraints and may not widen scope.                                                                                                                                                                           | required non-empty string; if generation fails after repair, fall back to original query and mark degraded quality in tracing | deterministic inputs constrain output                    |
| `search_filters.authors`              | explicit query text or accepted dimension values          | deterministic assembler | Extract only explicitly named people. No inference, alias expansion, or role-based guessing.                                                                                                                                                                                                                                  | `[]` when absent                                                                                                              | deterministic state wins                                 |
| `search_filters.venues`               | explicit query text or accepted dimension values          | deterministic assembler | Extract only explicitly named journals, conferences, or venues. No inference.                                                                                                                                                                                                                                                 | `[]` when absent                                                                                                              | deterministic state wins                                 |
| `search_filters.publication_years`    | explicit phrases plus normalization rules                 | rule-based assembler    | Match explicit year ranges first. For relative phrases, use the benchmark anchor year in fixtures and request year in production. Map `recent` in health/medicine to `2020–anchor_year`, `recent` elsewhere to `2021–anchor_year`, `last decade` to `{anchor_year-10}–{anchor_year}`, and `since YYYY` to `YYYY–anchor_year`. | `""` when absent                                                                                                              | rules win unless there is no explicit evidence           |
| `search_filters.publication_types`    | explicit phrases or framework-derived rules               | rule-based or hybrid    | Use framework-declared study design if present; else map explicit phrases to permitted values; else emit empty. Hybrid generation is allowed only when the rule engine returns no result and the output is constrained to the permitted-values list.                                                                          | `[]` when absent                                                                                                              | deterministic or rule evidence wins over free generation |
| `search_filters.fields_of_study`      | accepted topic plus permitted-values list                 | hybrid                  | Apply deterministic mapping first. If no match, allow a constrained LLM suggestion from the permitted-values list only.                                                                                                                                                                                                       | `[]` when unresolved                                                                                                          | permitted-values list and deterministic mapping win      |
| `search_optimized.semantic`           | integrated meaning of accepted inputs                     | LLM                     | Generate from approved `integrated_statement` and accepted dimensions only. Must not add constraints absent from approved inputs.                                                                                                                                                                                             | required non-empty string; repair once on validation failure, else fail the slice                                             | validated against deterministic scope                    |
| `search_optimized.keyword.structured` | concept-group inventory plus terminology output           | hybrid                  | Build a deterministic concept inventory first, then compile or constrain Boolean generation against that inventory.                                                                                                                                                                                                           | required non-empty string; if generation fails, compile a minimal deterministic Boolean expression from inventory             | compiled structure dominates formatting                  |
| `search_optimized.keyword.phrases`    | `integrated_statement` plus terminology output            | hybrid                  | Deterministically extract verbatim phrases first, then allow additive LLM supplementation grounded in approved concepts.                                                                                                                                                                                                      | `[]` when none                                                                                                                | deterministic extractions cannot be contradicted         |
| `search_optimized.keyword.terms`      | concept inventory plus explicit exclusions                | hybrid                  | Populate `excluded` deterministically from explicit exclusions; allow LLM to propose `required` and `optional` buckets only from grounded concepts.                                                                                                                                                                           | empty buckets are `[]`                                                                                                        | deterministic exclusions and hard constraints win        |
| `terminology.synonyms`                | accepted concepts plus external resources where available | LLM or retrieval-backed | Expand only concepts present in the approved `integrated_statement`. Drop any candidate not traceable to an approved concept.                                                                                                                                                                                                 | `{}` when none                                                                                                                | deterministic resources win when authoritative           |
| `grey_literature`                     | framework context plus accepted dimension values          | hybrid                  | Determine applicability first. Only if applicable may a narrow LLM populate content fields under the canonical `grey_literature` shape.                                                                                                                                                                                       | `null` when not applicable                                                                                                    | applicability rule wins                                  |

The specific implementation may change, but any code change that violates this contract should be treated as a design change and reviewed explicitly.

### Null and Empty Semantics

These must be settled before implementation. Mixing `null`, `""`, and `[]` without a defined convention causes silent validation mismatches that are difficult to trace at runtime.

| Field                                 | When absent or empty                                   | Canonical representation                          |
| ------------------------------------- | ------------------------------------------------------ | ------------------------------------------------- |
| `dimensions_specifications`           | not applicable — every framework dimension must appear | `null` per skipped dimension; never an absent key |
| `integrated_statement`                | not permitted — always required                        | n/a                                               |
| `search_filters.authors`              | no author constraint stated                            | `[]`                                              |
| `search_filters.venues`               | no venue constraint stated                             | `[]`                                              |
| `search_filters.publication_years`    | no temporal constraint                                 | `""`                                              |
| `search_filters.publication_types`    | no study-design constraint                             | `[]`                                              |
| `search_filters.fields_of_study`      | no disciplinary constraint                             | `[]`                                              |
| `search_optimized.semantic`           | not permitted — always required                        | n/a                                               |
| `search_optimized.keyword.structured` | not permitted — always required                        | n/a                                               |
| `search_optimized.keyword.phrases`    | no phrase extractions possible                         | `[]`                                              |
| `search_optimized.keyword.terms.*`    | no terms in that bucket                                | `[]`                                              |
| `terminology.synonyms`                | no synonym expansion generated                         | `{}`                                              |
| `grey_literature`                     | grey-lit support not applicable                        | `null`                                            |

### Transformation Rules

These rules must be explicit before the deterministic assembler is built. "Derive from session state" is not a rule; the exact derivation must be specified.

| Field                              | Rule                                                                                                                                                                                                                                                                                                                                                                                                                             |
| ---------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `dimensions_specifications`        | Iterate session steps in framework order. For each step: if `was_skipped`, emit `null`; else if `normalized_value` is present, emit `normalized_value_as_str`; else emit `null`. Every dimension must appear as a key. Order must match framework registration order.                                                                                                                                                            |
| `search_filters.publication_years` | Match explicit year ranges first. Apply phrase map using an explicit anchor year: benchmark fixtures must carry `anchor_year` in fixture metadata, and production requests use the request year in UTC. Then map "recent" in health/medicine → `"2020–anchor_year"`, "recent" elsewhere → `"2021–anchor_year"`, "last decade" → `"anchor_year-10–anchor_year"`, and "since YYYY" → `"YYYY–anchor_year"`. If no match, emit `""`. |
| `search_filters.authors`           | Extract only if a person's name is explicitly stated in query or accepted dimension values. No inference.                                                                                                                                                                                                                                                                                                                        |
| `search_filters.venues`            | Extract only if a journal or conference name is explicitly stated. No inference.                                                                                                                                                                                                                                                                                                                                                 |
| `search_filters.publication_types` | Use framework-declared study design if present in dimension values. Else extract explicit phrases matched against the permitted-values list. Else emit `[]`.                                                                                                                                                                                                                                                                     |
| `integrated_statement`             | LLM receives the assembled `dimensions_specifications` as canonical input. The model may not independently reconstruct dimension values from raw session history. Dimension values override conflicting original-query content.                                                                                                                                                                                                  |
| `search_optimized.semantic`        | Derived from approved `integrated_statement`. Must not widen scope beyond stated dimension values. Must not introduce constraints absent from `integrated_statement`.                                                                                                                                                                                                                                                            |
| `search_optimized.keyword.*`       | All keyword artifacts must be grounded in the approved `integrated_statement` and terminology output. The assembler discards any term not traceable to an accepted concept.                                                                                                                                                                                                                                                      |
| `terminology.*`                    | Expand only concepts present in the approved `integrated_statement`. If a candidate term is not grounded in an accepted concept, drop it.                                                                                                                                                                                                                                                                                        |

## Fields That Should Likely Leave the Main Generative Path

This does not mean these fields should disappear from the final response.

It means they should stop being regenerated by the synthesis model when the application already has the authoritative values.

For `dimensions_specifications` specifically, the required behavior should remain unchanged at the API level:

- every dimension in the selected refinement framework must still appear in the final output
- the output must preserve framework order
- the output must preserve the exact accepted value for each completed dimension
- dimensions explicitly skipped by the user should still be represented as `null`

The proposed change is only about field ownership.

Instead of asking the synthesis model to recreate `dimensions_specifications`, the system should assemble it directly from the existing refinement session state that already stores:

- the framework dimensions in order
- the final accepted value for each dimension
- whether a dimension was skipped

This preserves the same external result as before while reducing synthesis fragility and avoiding a second model pass over data the application already knows.

The strongest immediate candidates for deterministic or rule-based assembly are:

1. `dimensions_specifications`
2. explicit `authors`
3. explicit `venues`
4. explicit year ranges and common year phrases
5. publication types when directly implied by a framework dimension

Removing these from the main synthesis prompt reduces schema burden without reducing semantic quality.

## Hybrid Field Composition Model

Five fields are classified as hybrid in the decomposition table. "Hybrid" is not an implementation model. For each hybrid field the following must be specified: which component runs first, whether the second component is additive or replacing, what the final assembler does when both produce output, and what happens when the hybrid fails partially.

| Field                                 | First component                                                                                                  | Second component                                               | Composition pattern                                                                                 | Assembler rule                                                                                             | Partial failure handling                                                                           |
| ------------------------------------- | ---------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------- | --------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------- |
| `search_optimized.keyword.structured` | Deterministic: build concept-group inventory from accepted dimension values and terminology output               | LLM: generate Boolean expression constrained to inventory      | LLM uses inventory as input constraint; must not introduce concepts absent from inventory           | Assembler validates top-level AND-blocks against declared concepts; drops non-grounded blocks              | If LLM fails, assembler compiles a minimal Boolean expression from inventory directly              |
| `search_optimized.keyword.phrases`    | Deterministic: extract verbatim phrases from `integrated_statement`                                              | LLM: add established equivalents from terminology output       | Additive — LLM supplements; does not replace deterministic extractions                              | Assembler deduplicates; deterministic extractions take precedence                                          | If LLM fails, emit deterministic extractions only                                                  |
| `search_optimized.keyword.terms`      | Deterministic: populate `excluded` from explicit exclusions in accepted dimension values                         | LLM: populate `required` and `optional` from concept inventory | LLM cannot add to `excluded` without explicit evidence; `required` and `optional` are LLM-generated | Assembler enforces that no term appears in more than one bucket; deterministic `excluded` is authoritative | If LLM fails for `required`/`optional`, emit `[]` for those buckets; `excluded` is unaffected      |
| `search_filters.fields_of_study`      | Rule: derive if field is unambiguously entailed by the accepted topic, matched against the permitted-values list | LLM: invoked only when rule returns no match                   | Rule runs first; LLM only invoked on no-result                                                      | Assembler enforces permitted-values list regardless of source; rejects LLM output not in the list          | If both rule and LLM fail or disagree, emit `[]`                                                   |
| `grey_literature` / equivalent        | Rule: determine applicability from framework context and accepted dimension values                               | LLM: populate content fields if applicable                     | Rule gates whether the field is populated at all; LLM only generates if rule returns applicable     | Assembler emits `null` if rule returns not-applicable, regardless of LLM output                            | If LLM fails but rule returned applicable, emit a minimal valid empty structure rather than `null` |

If a hybrid field's composition cannot be specified at this level of precision before implementation starts, reclassify it as LLM-dependent for the initial version and revisit after the core synthesis split is stable.

## Implementation Guardrail

The current refinement pipeline is working well and should be preserved unless a change is strictly necessary for synthesis handling.

The planning assumption for future implementation should therefore be:

- avoid changing per-dimension refinement flow
- avoid changing step collection, session progression, skip handling, or dependency handling
- avoid changing non-synthesis pipeline behavior unless synthesis-only changes cannot achieve the target result
- prefer changes that are isolated to synthesis prompt construction, synthesis field ownership, synthesis validation, and final synthesis response assembly

Small supporting refactors may still be acceptable when they are strictly required to preserve correctness, traceability, or compatibility.

Examples that may be acceptable:

- adding synthesis-only helpers for deterministic field assembly
- adding synthesis-specific validation utilities
- adding tracing or test fixtures needed to observe split synthesis behavior
- making small response-assembly adjustments required to preserve the existing API contract

Examples that should remain out of scope unless proven necessary:

- redesigning the refinement step workflow
- changing dependency resolution semantics
- changing skip semantics outside the synthesis contract
- refactoring unrelated provider behavior

In practical terms, the preferred direction is to narrow the responsibility of synthesis rather than redesign the broader refinement pipeline.

## Candidate Strategy Set

### Option A: Keep monolithic synthesis, use a stronger model

Description:

- preserve the current architecture
- rely on a stronger local or remote model to handle the full synthesis schema

Advantages:

- lowest implementation effort
- minimal orchestration changes

Limitations:

- expensive in model quality requirements
- fragile for smaller local models
- prompt-schema drift still causes failures

### Option B: Keep monolithic synthesis, add stronger constrained decoding

Description:

- preserve the current architecture
- rely on grammar or schema-constrained decoding to enforce structure

Advantages:

- improves structural validity
- reduces malformed JSON

Limitations:

- does not improve semantic quality on its own
- a weak model can still produce low-value but structurally valid output

### Option C: Split synthesis into multiple smaller typed calls

Description:

- separate the final synthesis into smaller structured tasks
- examples: one call for integrated statement, one for retrieval expansions, one for terminology

Advantages:

- smaller prompts
- narrower task definitions
- easier retries and targeted validation

Limitations:

- more orchestration complexity
- more moving parts to trace and test

### Option D: Deterministic assembly plus smaller LLM subcalls

Description:

- assemble all deterministic fields from session state and explicit inputs
- reserve the LLM for the fields that actually require synthesis or lexical reasoning

Advantages:

- best fit for smaller local models
- simplest way to reduce schema burden
- easier to explain and test

Limitations:

- requires clearer ownership of each field
- may expose prompt-schema drift that is currently hidden

### Option E: Validation and repair loop

Description:

- let the model produce an initial result
- validate with Pydantic
- send only invalid or weak fields back for repair

Advantages:

- targeted retries
- lower cost than full regeneration
- good complement to other options

Limitations:

- adds orchestration complexity
- can mask deeper design problems if overused

### Option F: Intermediate DSL or slot-filling representation

Description:

- ask the model for a smaller intermediate state instead of the final schema
- compile the final JSON from that state

Advantages:

- easier tasks for smaller models
- clearer separation between reasoning and formatting

Limitations:

- requires design of the intermediate representation
- additional translation layer to maintain

### Option G: Retrieval-backed terminology expansion

Description:

- use curated lexicons, ontologies, or framework-specific resources for synonyms and subtype expansion
- use the LLM only when needed for gaps or ranking

Advantages:

- better recall control
- lower hallucination risk
- reduces burden on local models

Limitations:

- domain resource maintenance cost
- harder to generalize across all frameworks if no common vocabulary exists

## Option Decision Status

Not all options remain equally live. This table records which are ruled out, which are adopted, and which are deferred, so that the candidate set is a decision record rather than an open brainstorm.

| Option                                         | Status                              | Rationale                                                                                                                                                                                                                               |
| ---------------------------------------------- | ----------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| A — stronger model, monolithic synthesis       | **Ruled out as primary strategy**   | Increases infrastructure cost without addressing schema burden; prompt-schema drift causes failures regardless of model capability; viable only as a fallback cloud provider                                                            |
| B — constrained decoding, monolithic synthesis | **Ruled out as primary strategy**   | Structural enforcement alone does not improve semantic quality; a structurally valid but semantically weak output is still a failure; may still be used as a supporting mechanism within the chosen architecture                        |
| C — split synthesis calls                      | **Adopted in part**                 | Narrow calls for `integrated_statement`, semantic phrasing, and lexical expansion are part of the target hybrid architecture                                                                                                            |
| D — deterministic assembly plus LLM subcalls   | **Adopted as primary strategy**     | Best fit for synthesis-only scope; reduces schema burden; preserves the refinement pipeline                                                                                                                                             |
| E — validation and repair loop                 | **Adopted as supporting mechanism** | Complement to D and C; repair must be scoped to generated fields only and must not overwrite deterministic outputs                                                                                                                      |
| F — intermediate DSL or slot-filling           | **Deferred**                        | Requires designing and maintaining an intermediate representation; not necessary if the concept-group inventory approach for keyword compilation proves sufficient; revisit if keyword quality is poor after the initial implementation |
| G — retrieval-backed terminology               | **Deferred**                        | High value for recall quality but requires domain resource investment; revisit after the core synthesis split is stable and terminology quality is measurable                                                                           |

## Comparison Criteria

These criteria apply during option selection, before implementation work begins. They are for relative comparison of candidate strategies, not for post-implementation acceptance. Acceptance thresholds are defined separately in the Evidence and Evaluation section.

Each option should be evaluated against the same criteria:

1. Local feasibility on the target machine
2. Structural reliability
3. Semantic usefulness
4. Implementation complexity
5. Latency
6. Observability and debuggability
7. Testability
8. Tolerance to schema drift
9. Compatibility with open-source and open-weight local models

## Current Working Hypothesis

The current leading hypothesis is:

- use deterministic assembly for fields that do not require generation
- split the remaining synthesis work into smaller tasks where helpful
- keep validation and selective repair as supporting mechanisms

In short, the likely best direction is not merely a stronger model. It is a smaller generative surface.

This is a working hypothesis, not a final decision.

## Target Hybrid Architecture to Evaluate

The most promising candidate architecture to evaluate later is:

1. Build a canonical internal state from completed refinement steps.
2. Assemble deterministic fields programmatically, including `dimensions_specifications`, while preserving the current external response contract.
3. Use a small number of narrow LLM calls for:
   - `integrated_statement`
   - semantic retrieval phrasing
   - lexical expansion where deterministic resources are insufficient
4. Compile or assemble the final response object.
5. Validate against Pydantic.
6. Repair only the fields that fail validation or are demonstrably weak.

The hypothesis is that this architecture will make 8B to 14B local models viable for the synthesis step by narrowing the generative surface to tasks these models handle reliably. This hypothesis will be confirmed or rejected by the benchmark defined in the Evidence and Evaluation section. It should not be assumed true before that evidence exists.

### Proposed Minimal Call Graph

The target architecture still needs a concrete orchestration model.

The intended minimal shape should be:

1. Read completed refinement session state.
2. Build a canonical synthesis input object from:
  - original query
  - ordered framework dimensions
  - accepted dimension values
  - skipped-dimension markers
3. Deterministically assemble fields that already have authoritative values.
4. Run a narrow LLM call for `integrated_statement` using only canonical synthesis input.
5. Run retrieval asset generation using the approved `integrated_statement` and canonical synthesis input as shared context. These sub-steps are independent and can fail or be retried without affecting deterministic fields or each other:
   - a. Terminology call: generate `terminology.synonyms` for the top concepts in `integrated_statement`. Schema: `Dict[str, List[str]]`. Grounding constraint: only concepts traceable to `integrated_statement`.
   - b. Keyword compilation: build the concept-group inventory from accepted dimension values and terminology output; generate `keyword.structured`, `keyword.phrases`, and `keyword.terms` using the hybrid composition rules defined above. This may be one narrow LLM call over the inventory or a fully deterministic compilation if the inventory is sufficiently detailed.
   - c. Hybrid filter resolution: apply rule-based assembler for `publication_years`, `publication_types`, and `fields_of_study` using the transformation rules defined above; invoke a narrow LLM call only for `fields_of_study` when the rule cannot resolve, constrained to the permitted-values list.
   - d. Semantic query call: generate `search_optimized.semantic` from `integrated_statement` and accepted dimension values. Constraint: must not widen scope beyond stated inputs.
6. Assemble the final response object.
7. Validate the full object.
8. If repair is enabled, repair only the failing generated slice, not the entire response.

Important orchestration constraints:

- deterministic fields must not be overwritten during repair
- repair should operate on the smallest failing slice
- generated fields must consume canonical synthesized inputs, not independently reconstructed context
- the final assembler, not the model, should enforce the output contract

### Candidate Narrow Synthesis Calls

The document currently says "a small number of narrow LLM calls" but does not define them.

The minimum candidate split worth evaluating is:

1. Statement call:
  - input: original query plus canonical accepted dimensions
  - output: `integrated_statement`
2. Retrieval phrasing call:
  - input: `integrated_statement` plus canonical accepted dimensions
  - output: `search_optimized.semantic`
3. Terminology call:
  - input: `integrated_statement` plus concept inventory
  - output: `terminology.synonyms`
4. Keyword support call:
  - input: `integrated_statement` plus concept inventory and terminology output
  - output: `keyword.phrases` plus candidate `required` and `optional` term buckets
5. Deterministic or hybrid compilation step:
  - input: deterministic fields plus generated lexical assets
  - output: final structured response

This may still collapse to fewer calls, but the document should treat this as the minimum concrete candidate instead of an unspecified multi-call pattern.

### Split-Call Interface Contracts

The split architecture is only implementation-ready if each narrow call has its own typed contract, validator boundary, and repair scope. The final `QueryRefinementResponse` schema is not sufficient as the only schema surface.

| Call                          | Input contract                                                                                    | Output contract                                                                           | Validation boundary                                                         | Repair scope                       |
| ----------------------------- | ------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------- | --------------------------------------------------------------------------- | ---------------------------------- |
| Statement call                | `original_query`, ordered dimensions, accepted values, skipped markers, deterministic constraints | `StatementResponse { integrated_statement: str }`                                         | string must be non-empty and constraint-preserving against canonical inputs | rerun statement call only          |
| Retrieval phrasing call       | approved `integrated_statement`, ordered dimensions, accepted values                              | `SemanticQueryResponse { semantic: str }`                                                 | string must be non-empty and add no new constraints                         | rerun retrieval phrasing call only |
| Terminology call              | approved `integrated_statement`, concept inventory                                                | `TerminologyResponse { synonyms: Dict[str, List[str]] }`                                  | keys must map to approved concepts; values must be lists of strings         | rerun terminology call only        |
| Keyword support call          | approved `integrated_statement`, concept inventory, terminology output                            | `KeywordSupportResponse { phrases: List[str], required: List[str], optional: List[str] }` | all terms must be traceable to approved concepts and unique across buckets  | rerun keyword support call only    |
| Hybrid filter resolution call | canonical synthesis input, permitted-values lists, unresolved field markers                       | `FilterSuggestionResponse { fields_of_study: List[str] }`                                 | every value must be from the permitted-values list                          | rerun filter resolution call only  |

Implementation rules for these contracts:

- each call schema must live separately from the final response schema
- each call must be validatable in isolation without constructing the full final response
- repair must target one failed call at a time
- no repair step may rewrite a previously validated deterministic field or a previously validated generated slice unless that slice is the explicit repair target
- prompt examples for split calls must be versioned alongside their schema definitions

## Future Implementation Workstreams

These workstreams are sequenced. Each must be substantially complete before the next begins.

1. Clear the prerequisite alignment gate: align prompt, schema, null/empty conventions, and worked examples; produce all five gate-exit artifacts.
2. Freeze the canonical contract: finalise the ownership matrix above, confirm exact field names, and remove any placeholder or legacy field labels from prompts and examples.
3. Define split-call contracts: create typed request and response schemas, validators, examples, and repair boundaries for every narrow call.
4. Implement deterministic assembly for fields with authoritative session-state values; validate that the external API response is identical to the current output.
5. Implement the minimal synthesis call graph: statement call, retrieval phrasing call, terminology call, keyword compilation step, hybrid filter resolution step.
6. Add field-level validation and narrow repair behaviour scoped to generated fields only; verify that repair cannot overwrite deterministic fields.
7. Add tests for field ownership correctness, deterministic assembly, split-call contract validity, structured-output reliability, and repair scope.
8. Freeze the benchmark pack and threshold document before any benchmark execution: fixture set, `anchor_year`, scoring rubric, baseline configuration, candidate configuration, and agreed thresholds.
9. Run the benchmark against candidate local models and then update provider capability documentation to reflect the validated synthesis architecture.

Implementation preference:

- keep code changes localized to synthesis handling wherever possible
- treat broader pipeline refactors as out of scope unless they are strictly required to preserve correctness

## Model Evaluation Principle

Model selection should be revisited after deciding how much of the final schema remains generative.

Comparing models only under the current monolithic synthesis design risks choosing a larger model to compensate for an avoidable architectural burden.

## Evidence Required Before Choosing a Final Option

Any eventual decision should be backed by evidence such as:

1. Pydantic success rate
2. malformed-output rate
3. field-level repair frequency
4. semantic usefulness of generated search assets
5. latency on the target Apple Silicon laptop
6. comparison against the current Claude-based baseline

That evidence should be made operational before benchmark execution begins.

Minimum evaluation design:

- a fixed benchmark set of at least 20 sessions drawn from real or realistic queries, covering all four primary frameworks: `mph_dissertation`, `pico_advanced`, `solaceai`, and `legal_research`; at least four sessions per framework; at least one session per framework with a skipped dimension; at least two sessions per framework representing high-complexity queries (multi-constraint, dependency chains, or deliberately ambiguous user answers)
- one baseline configuration: current monolithic synthesis with the current cloud provider, no changes
- one candidate configuration: synthesis-only changes as implemented, tested against both the cloud provider and Llama 3.1 8B locally
- scoring at field level, not whole-object pass/fail
- benchmark sessions and their expected field-level outputs stored in the test fixtures directory so they are re-runnable and version-controlled
- every benchmark fixture must include metadata for `framework_id`, difficulty tier, whether any dimensions were skipped, and `anchor_year` used by time-relative normalization rules
- acceptance thresholds agreed in writing before any benchmark run begins (see threshold process below)

Minimum metrics to track:

- whole-response validation pass rate
- field-level validation pass rate
- omission rate for required dimensions
- disagreement rate between deterministic truth and generated restatement
- repair invocation rate
- repair success rate
- median and p95 latency
- token usage per successful result
- qualitative score for `integrated_statement`
- qualitative score for search usefulness

Qualitative scoring protocol:

- use a fixed 1 to 5 rubric for `integrated_statement` and search usefulness
- score `integrated_statement` on fidelity to accepted dimensions, clarity, and absence of unsupported constraints
- score search usefulness on retrieval precision, recall-oriented coverage, and absence of obvious off-scope terms
- each case must be scored by two reviewers independently against the same rubric
- disagreements of more than one point require adjudication and a written note
- benchmark reports must include both the mean score and disagreement count

Suggested decision thresholds for an initial go or no-go check:

- deterministic fields must have zero disagreement with their source-of-truth inputs
- whole-response validation pass rate should be meaningfully improved or maintained relative to baseline
- repair rate should be low enough that the architecture is simpler in practice than keeping a stronger monolithic model
- median latency should remain acceptable for the intended interactive workflow
- search usefulness should not regress materially against the current baseline

Threshold ownership and process:

1. The engineer implementing the synthesis split proposes concrete threshold values in a short written decision note before the benchmark runs.
2. The project team reviews and agrees the thresholds before a single benchmark result is inspected. Thresholds must not be adjusted after seeing results.
3. The agreed thresholds are recorded alongside the benchmark results.
4. A go decision requires all hard thresholds to pass. A conditional go may proceed only if every failing metric has a concrete, time-bounded remediation plan attached.

The threshold document is a required output of workstream 8 and must exist before benchmark execution begins.

## Follow-up Documentation Likely Needed Later

Once a direction is chosen, these files will probably need updates:

- `README.md`
- `docs/OPERATIONS.md`
- `docs/DEPLOYMENT.md`
- `docs/API.md`

## Open Questions to Revisit Later

1. Should Boolean query construction remain generative, or be compiled from concept groups?
2. Should terminology expansion rely only on the LLM, or on hybrid resources?
3. Should this planning note remain one document, or later split into a design record plus implementation guide?
