# Search Expansion Levels Plan

Status: Superseded — implemented with a fixed six-aspect ontology and two-stage pipeline (aspect assessment + expansion generation). See docs/API.md (`POST /api/v1/refinement/search-expand`) for the current contract: `advisory_dimensions` replaced `eligible_dimensions`, levels use `relaxed_aspects` and a `strategy` field, and a deterministic safety policy governs which aspects may be broadened. The notes below are retained for historical context.

## Scope

This feature is implemented in the **CLI** and **API** only. The web application is explicitly out of scope and requires no changes.

## Purpose

Add graduated search expansion levels after synthesis so downstream retrieval can broaden recall without changing the canonical refined question.

The preferred architecture is a dedicated post-synthesis search expansion stage, not another synthesis split-call. This keeps the synthesis prompt and split-call graph focused on producing the canonical refined query and baseline search artifacts.

Stage responsibilities:

- Refinement defines what the user means.
- Synthesis produces the canonical refined query and baseline search artifacts.
- Search expansion produces optional recall-broadening retrieval variants from the completed synthesis result.

## Critical Architecture Review

The earlier plan recommended adding search expansion as a sixth split-call inside `_run_split_synthesis()`. That would work technically, but it is not the cleanest design for this codebase.

### Why a Third Stage Is Preferable

1. It preserves synthesis simplicity.

   `_run_split_synthesis()` already coordinates statement generation, semantic phrasing, terminology, filter resolution, and keyword support. Adding expansion there would increase the cognitive load of an already dense method.

2. It uses richer context.

   A separate expansion stage can consume the completed `QueryRefinementResponse`, including `integrated_statement`, `dimensions_specifications`, `search_optimized`, `search_filters`, and `terminology`. A split-call inside synthesis would normally see only the intermediate statement and accepted dimensions unless more data were threaded through.

3. It creates a cleaner contract.

   Synthesis answers: what is the refined query? Search expansion answers: how can retrieval broaden without redefining the review scope?

4. It is easier to disable, retry, or expose separately.

   If expansion fails, the system can still return the synthesized query and deterministic Level 0. That failure mode is cleaner when expansion is its own stage.

5. It makes evaluation cleaner.

   Expansion outputs can be evaluated as search strategy artifacts without conflating them with synthesis quality.

### Main Tradeoff

The third-stage design adds one sequential LLM call after synthesis. That means slightly higher latency than running expansion in parallel with the existing synthesis split-calls. The tradeoff is acceptable because the prompt is simpler, the stage boundary is clearer, and failure handling is safer.

## Current System Observations

The current synthesis path is implemented in `QueryRefinementManager.synthesize_refined_query()` and `_run_split_synthesis()`.

Current split-call graph:

1. Statement call, serial: produces `integrated_statement`.
2. Semantic query call, parallel: produces `search_optimized.semantic`.
3. Terminology call, parallel: produces `terminology.synonyms`.
4. Filter resolution call, parallel: produces search filter suggestions.
5. Keyword support call, after terminology: produces phrases and required/optional/excluded terms.

The updated design leaves this graph unchanged.

Current API behavior:

- The shared route helper calls `manager.synthesize_refined_query(session)`.
- It persists `integrated_statement`, `dimensions_specifications`, `search_optimized`, `search_filters`, and `terminology` through `save_query_refinement_response()`.
- It emits `synthesis.started`, `synthesis.complete`, and final completion progress.

Current progress model:

- Public progress stages include `SYNTHESIZING`, `SYNTHESIS_COMPLETE`, and `COMPLETED`.
- There is no existing public search-expansion stage.

Current CLI behavior:

- The CLI displays the synthesized statement, refined dimensions, and search-optimized query artifacts from `manager.synthesize_refined_query(session)`.

## New Logical Pipeline

1. Refinement stage: collect and validate dimension values.
2. Synthesis stage: produce `QueryRefinementResponse` using the existing split synthesis graph.
3. Search expansion stage: generate `search_expansion_levels` from the completed synthesis result.

## Target Output Shape

Add a new top-level API and persistence field:

```json
{
  "search_expansion_levels": [
    {
      "level": 0,
      "label": "Exact clarified question",
      "search_query": "...",
      "relaxed_dimensions": {},
      "rationale": "Exact clarified query preserved as the review anchor."
    },
    {
      "level": 1,
      "label": "Direct contextual broadening",
      "search_query": "...",
      "relaxed_dimensions": {
        "geography": "..."
      },
      "rationale": "..."
    }
  ]
}
```

Level 0 is always deterministic and must exactly equal `integrated_statement`. The LLM generates only Levels 1 through N.

## Key Design Decisions

1. Level 0 is injected by code, not generated by the LLM.

   The synthesis stage already creates the canonical `integrated_statement`. The expansion prompt must not restate it. Code should guarantee:

   ```python
   search_expansion_levels[0].search_query == synthesis_response.integrated_statement
   ```

2. Per-level output uses `search_query`, not `integrated_statement`.

   `integrated_statement` remains the single canonical refined statement. Expansion levels are retrieval variants.

3. Per-level `keyword_phrases` are deferred.

   The existing keyword-support split-call already generates phrase and term support for the canonical query. Per-level keyword phrases can be added later if there is a confirmed downstream consumer.

4. Search expansion fails soft.

   If the expansion call fails, times out, or returns invalid levels after one repair attempt, return Level 0 only and preserve the synthesized result.

5. Contextual validation gets its own path.

   `_validate_split_result(call_name, result)` currently has no access to accepted dimension IDs. Invalid `relaxed_dimensions` keys should be checked by a dedicated search-expansion validator or by a wrapper around `_run_split_call()`.

## Implementation Plan

### Phase 1 - Response Models

File: `query_refinement_module/schema/response.py`

Add:

```python
class SearchExpansionLevel(BaseModel):
    level: int
    label: str
    search_query: str
    relaxed_dimensions: Dict[str, str] = Field(default_factory=dict)
    rationale: str


class SearchExpansionResponse(BaseModel):
    levels: List[SearchExpansionLevel] = Field(default_factory=list)
```

Validation expectations:

- LLM-generated `level` values must be greater than or equal to 1.
- `search_query` must be non-empty.
- `label` must be non-empty.
- `rationale` must be non-empty.
- `relaxed_dimensions` should map accepted dimension IDs to search-only relaxed values.
- Each LLM-generated level should relax at most two dimensions.

Update `__all__` to export both models.

### Phase 2 - Dedicated Prompt Module

Recommended new file: `query_refinement_module/schema/templates/search_expansion.py`

Add a standalone `SEARCH_EXPANSION_TEMPLATE` string. Do not add this to `SYNTHESIS_TEMPLATE`; the point of this design is to keep search expansion out of the synthesis prompt.

Prompt rules should require:

- Generate Levels 1 through N only.
- Never generate Level 0.
- Treat the supplied Level 0 anchor as fixed.
- Use the synthesis result as source context, not as permission to change review scope.
- Broaden only for search recall.
- Relax only one or two dimensions per level.
- Prefer meaningful dimension-level broadening in this order: geography hierarchy, setting class, adjacent population grouping, broader condition family, broader time phase.
- Avoid Cartesian combinations.
- Return zero additional levels if the question is already broad and has no narrow dimensions to relax.
- Return at most four additional levels.
- Explain what changed and why in each rationale.

Expected LLM schema:

```json
{
  "levels": [
    {
      "level": 1,
      "label": "...",
      "search_query": "...",
      "relaxed_dimensions": {},
      "rationale": "..."
    }
  ]
}
```

### Phase 3 - Dedicated Prompt Builder

Recommended new file: `query_refinement_module/schema/search_expansion.py`

Add `SearchExpansionPromptBuilder`:

```python
class SearchExpansionPromptBuilder:
    @staticmethod
    def get_system_prompt() -> str:
        from .templates.search_expansion import SEARCH_EXPANSION_TEMPLATE
        return SEARCH_EXPANSION_TEMPLATE

    @staticmethod
    def get_user_prompt(
        synthesis_response: QueryRefinementResponse,
        accepted_dimensions: Dict[str, Any],
        original_query: str,
    ) -> str:
        ...
```

The user prompt should include:

- Original query.
- Level 0 anchor: exact `synthesis_response.integrated_statement`.
- `dimensions_specifications` as JSON.
- Accepted dimensions as JSON.
- `search_optimized.semantic`, `search_filters`, and `terminology.synonyms` as supporting search context.
- A reminder that Level 0 is already established and must not be regenerated.

### Phase 4 - Core Third Stage

File: `query_refinement_module/core.py`

Leave `_run_split_synthesis()` unchanged.

Add a dedicated stage method, for example:

```python
async def generate_search_expansion_levels(
    self,
    *,
    original_query: str,
    synthesis_response: QueryRefinementResponse,
    accepted_dimensions: Dict[str, Any],
    model: Optional[str] = None,
    temperature: float = 0.2,
    max_tokens: int = 1536,
) -> Tuple[List[SearchExpansionLevel], Dict[str, Any]]:
    ...
```

Stage behavior:

1. Build deterministic Level 0 from `synthesis_response.integrated_statement`.
2. If `accepted_dimensions` is empty, return Level 0 only.
3. Call the LLM with `SearchExpansionResponse` for Levels 1 through N.
4. Validate returned levels against accepted dimension IDs.
5. If validation or repair fails, return Level 0 only and include warning metadata.
6. Return `(search_expansion_levels, metadata)`.

Recommended deterministic Level 0:

```python
level_0 = SearchExpansionLevel(
    level=0,
    label="Exact clarified question",
    search_query=synthesis_response.integrated_statement,
    relaxed_dimensions={},
    rationale="Exact clarified query preserved as the review anchor.",
)
```

Recommended contextual validator:

```python
def _validate_search_expansion_result(
    result: SearchExpansionResponse,
    accepted_dimensions: Dict[str, Any],
) -> Optional[str]:
    ...
```

It should check:

- `levels` is a list.
- Every level has non-empty `search_query`, `label`, and `rationale`.
- LLM-generated levels are greater than or equal to 1.
- Level numbers are unique and sorted.
- `relaxed_dimensions` keys are accepted dimension IDs.
- Each level relaxes at most two dimensions.

There are two viable repair strategies:

1. Add an optional contextual validator argument to `_run_split_call()` so it can repair using the existing repair flow.
2. Keep `_run_split_call()` unchanged and implement a private `_run_search_expansion_call()` wrapper that performs one targeted repair attempt with accepted-dimension context.

The wrapper approach is lower risk because it avoids changing the shared split-call helper used by existing synthesis calls.

### Phase 5 - Orchestration

File: `query_refinement_module/core.py`

`synthesize_refined_query()` and its `result_dict` remain unchanged. Search expansion is not bundled into that method. It is always invoked separately — either from the CLI after a user confirmation prompt or from the dedicated API endpoint.

`generate_search_expansion_levels()` is a standalone public method on `QueryRefinementManager`, callable independently after synthesis has completed. It does not require the live `RefinementSession` object; callers reconstruct its inputs from the persisted synthesis result.

Metadata returned by `generate_search_expansion_levels()` should be self-contained:

```python
"metadata": {
    "prompt_tokens": ...,
    "completion_tokens": ...,
    "total_tokens": ...,
}
```

This keeps it independent of the synthesis metadata structure.

### Phase 6 - API Exposure

File: `query_refinement_module/api/routes/refinement.py`

Search expansion is exposed as a **dedicated, independent endpoint**. It is not bundled into `/synthesize` and `SynthesizeQueryResponse` is not changed.

The existing `/synthesize` endpoint and `_run_synthesis()` helper remain unchanged.

#### New endpoint

```
POST /api/v1/refinement/queries/{query_id}/search-expand
```

Authentication: same as the other refinement workflow endpoints (`Authorization: Bearer <token>` or `X-API-Key`).

Request body: none required (the query ID is in the path). An optional `model` override field may be accepted for consistency with other LLM-calling endpoints.

Behavior:

1. Resolve `query_id`; return 404 if not found, 403 if access denied.
2. Load the persisted synthesis result from the DB record (`refined_query` / `integrated_statement`, `dimensions_specifications`, `search_optimized`, `search_filters`, `terminology`). Return 409 if synthesis has not yet completed for this query.
3. Reconstruct `QueryRefinementResponse` and `accepted_dimensions` from the stored DB fields. `accepted_dimensions` is derived from `dimensions_specifications` by filtering out `[SKIPPED]` entries.
4. Call `manager.generate_search_expansion_levels(...)` with the reconstructed inputs.
5. Persist the result using `save_query_refinement_response()` update for the `search_expansion_levels` column (Phase 7).
6. Return a `SearchExpandResponse`.

#### Response model

```python
class SearchExpandResponse(BaseModel):
    query_id: int
    search_expansion_levels: List[Dict[str, Any]]
    metadata: Optional[Dict[str, Any]] = None
```

#### Progress and webhook behavior

Minimal first iteration: emit internal trace events `search_expansion_start` and `search_expansion_complete` only. No new public `ProgressStage` values are needed unless the frontend requires them. The web application is out of scope so no progress-stage changes are required.

### Phase 7 - Persistence

File: `query_refinement_module/db/models/query.py`

Add:

```python
search_expansion_levels = Column(JSON, nullable=True)
```

File: `query_refinement_module/db/crud.py`

Update `save_query_refinement_response()` to persist the new field when present.

Add an Alembic migration for the new JSON column.

Decision point: if persistence is not required for the first iteration, this phase can be deferred. If the API returns expansion levels but does not persist them, document that explicitly to avoid evaluation confusion.

### Phase 8 - CLI Output

File: `query_refinement_module/cli.py`

After synthesis completes and the result is displayed, prompt the user interactively:

```
Would you like to generate search expansion levels? [y/N] 
```

Implementation notes:

- Use `await asyncio.to_thread(input, ...)` consistent with how user input is read elsewhere in the CLI.
- Default to No if the user presses Enter without typing.
- Accept `y` or `yes` (case-insensitive) as confirmation; anything else skips expansion.
- If confirmed, call `manager.generate_search_expansion_levels()` using the `synthesis` result dict and `accepted_dimensions` derived from the session steps.
- If the call fails, print a warning and continue — do not abort the CLI session.

Display format (keep concise):

```
────────────────────────────────────────────────────────────────────────────────
SEARCH EXPANSION LEVELS
────────────────────────────────────────────────────────────────────────────────
Level 0 — Exact clarified question
  <integrated_statement>

Level 1 — <label>
  <search_query>
  Relaxed: <dimension>: <value>
  Rationale: <rationale>

...
```

- Show Level 0 and each broader level.
- Show relaxed dimensions and rationale for each level.
- Avoid printing raw JSON unless a verbose flag is already present.

### Phase 9 - Tests

Update `tests/unit/test_split_synthesis.py` only for regressions proving the existing synthesis graph remains unchanged.

Add `tests/unit/test_search_expansion.py`:

- `SearchExpansionPromptBuilder.get_system_prompt()` returns a non-empty prompt.
- `SearchExpansionPromptBuilder.get_user_prompt()` includes the exact integrated statement.
- `SearchExpansionResponse` parses valid LLM output.
- `generate_search_expansion_levels()` injects Level 0 exactly.
- Empty accepted dimensions return Level 0 only.
- `_validate_search_expansion_result(...)` accepts valid levels.
- `_validate_search_expansion_result(...)` rejects empty `search_query`.
- `_validate_search_expansion_result(...)` rejects duplicate level numbers.
- `_validate_search_expansion_result(...)` rejects invalid relaxed dimension keys.
- `_validate_search_expansion_result(...)` rejects levels relaxing more than two dimensions.

Manual scenario checks:

- Exact named setting: confirm Level 0 remains exact and Level 1 broadens only the setting class or geography.
- Hyperlocal single-site query: confirm the refined question is not broadened, only optional search levels are.
- Narrow time-window query: confirm time is broadened only in later levels and rationale explains why.
- Already broad query: confirm zero or one additional levels, not a forced five-level ladder.

## Recommended Acceptance Criteria

1. `_run_split_synthesis()` remains focused on canonical synthesis and is not expanded with search-expansion logic.
2. `search_expansion_levels[0].search_query` equals `integrated_statement` exactly.
3. The LLM never generates or edits Level 0.
4. Each Level 1-N entry names the dimensions it relaxes.
5. No level relaxes more than two dimensions.
6. Invalid relaxed dimension keys fail contextual validation or trigger repair.
7. Search expansion failure returns Level 0 only rather than failing synthesis.
8. The independent search expansion API response exposes `search_expansion_levels` after synthesis has completed.
9. Search expansion levels are saved in the dedicated `queries.search_expansion_levels` JSON column.
10. Existing synthesis tests still pass without requiring prompt changes to `SYNTHESIS_TEMPLATE`.

## Open Decisions

1. API: search expansion is an independent on-demand endpoint (`POST /queries/{query_id}/search-expand`), not bundled into `/synthesize`. CLI: search expansion runs only when the user confirms the interactive prompt. Web app: out of scope. No further decision needed on this point.
2. Persistence timing: implemented immediately with a dedicated DB column and Alembic migration.
3. Whether downstream consumers need per-level keyword support. The recommended first iteration omits it.
4. Public progress stages are not added in the first iteration; search expansion uses logging and internal trace events only.
5. Whether to keep flat token metadata for backward compatibility while adding nested per-stage metadata.

## Suggested Verification Commands

```bash
.venv/bin/pytest tests/unit/test_split_synthesis.py -q
.venv/bin/pytest tests/unit/test_search_expansion.py -q
.venv/bin/pytest tests/unit/test_template_model_alignment.py -q
```

Run the new `test_search_expansion.py` command after the implementation test file exists.