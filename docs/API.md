# API Guide

All endpoints are versioned under `/api/v1` unless noted.

## Authentication

- `POST /api/v1/auth/register` (available only when `ALLOW_REGISTRATION=true`; returns 403 when disabled)
- `POST /api/v1/auth/login`
- `GET /api/v1/auth/me`
- `GET /api/v1/auth/me/status`
- `POST /api/v1/auth/logout`

Browser logins set an httpOnly auth cookie by default. For non-browser clients, the same JWT can be sent as `Authorization: Bearer <token>` after extracting it from that cookie.

For server-to-server integrations, refinement workflow endpoints also support `X-API-Key: <integration-api-key>` when `INTEGRATION_API_KEY` is configured on the API service.

## Agent integration guide

This section is the primary reference for building agents or automated integrations. It describes the state machine, decision logic, quick-reply handling, and RAG field mapping needed to drive the full workflow programmatically.

### The three-phase pipeline

```
Phase 1 — Discover               GET  /frameworks
Phase 2 — Refine (loop)          POST /start  →  loop: POST /answer
Phase 3 — Synthesize (core)      POST /synthesize  (Agents A → B → C, orchestrated)
           or call individually:  POST /normalize   (Agent A only)
                                  POST /represent   (Agent B only)
                                  POST /construct   (Agent C only)
Phase 4 — Expand (optional)      POST /expand  (Agent D, standalone)
```

### Authentication for agents

Use the `X-API-Key` header for all requests:

```
X-API-Key: <value of INTEGRATION_API_KEY env var>
```

The integration service user must have explicit framework access. Grant it once on the server:

```bash
poetry run python scripts/create_user.py \
  --username api_integration_service \
  --framework <framework_name>
```

### State machine

```
POST /start
  │
  ├─ ready_for_synthesis = true  ──────────────────────────────────► POST /synthesize
  │
  └─ next_prompt ≠ null
       │
       ▼
   ┌──────────────────────────────────────────────────┐
   │  REFINEMENT LOOP                                  │
   │                                                   │
   │  1. Present next_prompt.question to user          │
   │  2. Optionally render next_prompt.examples        │
   │     as clickable buttons                          │
   │  3. Collect answer (free text or clicked example) │
   │  4. POST /answer  { "answer": "<string>" }        │
   │                                                   │
   │  Response branch:                                 │
   │  ├─ ready_for_synthesis = true ──────────────────►│── POST /synthesize
   │  ├─ next_prompt ≠ null  (loop continues) ────────►│── back to step 1
   │  └─ next_prompt = null && !ready_for_synthesis    │
   │       (no more questions, force synthesize) ─────►│── POST /synthesize
   └──────────────────────────────────────────────────┘

POST /synthesize
  │
  └─ structured_output ──► RAG retrieval (see field mapping below)
                      └──► POST /expand  (optional broadening levels, Agent D)
```

### Minimal integration loop (pseudocode)

```python
BASE = "http://localhost:8001/api/v1"
HEADERS = {"X-API-Key": API_KEY, "Content-Type": "application/json"}

# Phase 1 — pick a framework
frameworks = GET(f"{BASE}/refinement/frameworks")["frameworks"]
framework_name = frameworks[0]   # or let the user choose

# Phase 2 — start and refine
r = POST(f"{BASE}/refinement/start", {
    "original_query": user_query,
    "framework_name": framework_name,
    "source": "api_integration",
})
query_id = r["query_id"]

while not r.get("ready_for_synthesis"):
    prompt = r.get("next_prompt")
    if not prompt:
        break  # no more questions

    question  = prompt["question"]       # plain prose question
    examples  = prompt["examples"]       # list[str] — quick-reply options (may be empty)
    aspect_id = prompt["aspect_id"]

    # Present question + examples to user (or have agent select)
    answer = agent_or_user_select(question, examples)

    r = POST(f"{BASE}/refinement/queries/{query_id}/answer", {"answer": answer})

# Phase 3 — synthesize
synthesis = POST(f"{BASE}/refinement/synthesize", {"query_id": query_id})
```

### Synthesis agents

Each agent is an independent LLM call with a defined input/output contract and its own HTTP endpoint. They are designed to be called in sequence (A → B → C → D), but each can be invoked individually.

```
Agent A  POST /normalize   Normalization — session → clarified_query
Agent B  POST /represent   Semantic Representation — statement → queries + concept_graph
Agent C  POST /construct   Search Construction — statement + concept_graph → keyword artifacts
Agent D  POST /expand      Search Expansion — statement → broadening levels (optional)
```

`POST /synthesize` is the **shortest path** — it orchestrates A → B → C in a single call and returns the full `structured_output`. Call the individual endpoints when you need only a subset of the pipeline or want to cache intermediate outputs.

#### Agent A — Normalization

**Endpoint:** `POST /api/v1/refinement/normalize`  
Also invoked automatically by `POST /api/v1/refinement/synthesize`.

**Input:** `{ "query_id": 123 }` — completed refinement session.

**Output:**

| Field | Description |
|---|---|
| `clarified_query` | Clarified research statement — the review anchor and Level 0 query |
| `dimensions_specifications` | Per-dimension refined values assembled deterministically from session state |

`clarified_query` is the primary human-readable output. If you only need the refined query (for display, QA forwarding, or logging), call `/normalize` — Agents B and C are not invoked and the session is not marked as synthesized.

Pass `clarified_query` as input to `/represent` (Agent B) or `/expand` (Agent D).

#### Agent B — Semantic Representation

**Endpoint:** `POST /api/v1/refinement/represent`  
Also invoked automatically by `POST /api/v1/refinement/synthesize`.

**Input:** `{ "statement": "..." }` — no session required. (Use `clarified_query` from POST /normalize.)

**Output:**

| Field | Description |
|---|---|
| `semantic_statement` | Dense embedding query (2-3 sentences, 50-70 words) for vector/semantic search. Information-need framing using document-side vocabulary. |
| `keyword_statement` | Natural-language keyword query (15-35 words) for BM25/simple keyword search. Key concepts + primary synonyms; no Boolean operators; no metadata filters. |
| `concept_graph` | Per-concept retrieval metadata — synonyms, abbreviations, domain terms, controlled vocabulary hints |

Both `semantic_statement` and `keyword_statement` are filter-free — they share the same `search_filters` produced by Agent C. Pass `concept_graph` to `/construct` (Agent C) and `/expand` (Agent D).

Each entry in `concept_graph`:

```json
{
  "query_role": "intervention_or_exposure_or_phenomenon",
  "true_synonyms": ["acetylsalicylic acid"],
  "abbreviations": ["ASA"],
  "spelling_variants": [],
  "lexical_variants": [],
  "domain_terms": ["antiplatelet agent"],
  "colloquial": ["blood thinner"],
  "controlled_vocabulary_hints": [
    { "vocabulary_name": "MeSH", "terms": ["Aspirin"], "confidence": "high" }
  ]
}
```

`domain_terms` are reserved for Agent D broadening (Levels 2–3) and are not included in the Agent C anchor Boolean query. `colloquial` terms are not used in formal database queries.

#### Agent C — Search Construction

**Endpoint:** `POST /api/v1/refinement/construct`  
Also invoked automatically by `POST /api/v1/refinement/synthesize`.

**Input:** `{ "statement": "...", "concept_graph": {...} }` — no session required. (Use `clarified_query` from POST /normalize and `concept_graph` from POST /represent.)

**Output:**

| Field | Description |
|---|---|
| `keyword.combined_blocks` | **Primary RAG artifact** — one AND-block per concept with `role`, `free_text` terms, and `controlled_vocabulary` |
| `keyword.structured` | Boolean anchor query (fallback) |
| `keyword.phrases` | Exact key phrases |
| `search_filters` | Metadata narrowing filters (`publication_years`, `publication_types`, etc.) — applies to both `semantic_statement` and `keyword_statement` from Agent B |

`combined_blocks` connector logic:
```
OR  free_text terms  within each block
OR  controlled_vocabulary terms  within each block
AND all blocks together
```

Use `controlled_vocabulary` only for indexed sources (PubMed → MeSH, WHO IRIS → DeCS). Use `free_text` alone for unindexed sources (OpenAlex, CORE, ReliefWeb).

#### Agent D — Search Expansion

**Endpoint:** `POST /api/v1/refinement/expand` (standalone, optional)

**Input:**

| Field | Source | Required |
|---|---|---|
| `statement` | Agent A output (`clarified_query`) | Yes |
| `search_context.concept_graph` | `concept_graph` from Agent B | No, but improves accuracy |

**Output:** `search_expansion_levels` — Level 0 (exact anchor) plus up to three broader retrieval levels. Use when initial retrieval yields insufficient results.

Each level carries a `strategy` field: `anchor` (Level 0 only), `lexical`, `conceptual_single_aspect`, or `conceptual_multi_aspect`. The `strategy` field is authoritative — do not infer broadening type from level number alone.

Calling agents individually in sequence:

```python
# Agent A
norm = POST(f"{BASE}/refinement/normalize", {"query_id": query_id})

# Agent B
sem = POST(f"{BASE}/refinement/represent", {
    "statement": norm["clarified_query"]
})

# Agent C
search = POST(f"{BASE}/refinement/construct", {
    "statement": norm["clarified_query"],
    "concept_graph": sem["concept_graph"]
})

# Agent D (optional)
expand = POST(f"{BASE}/refinement/expand", {
    "statement": norm["clarified_query"],
    "search_context": {"concept_graph": sem["concept_graph"]}
})
```

Or use the single-call orchestration path (POST /synthesize) to run A → B → C at once:

```python
synthesis = POST(f"{BASE}/refinement/synthesize", {"query_id": query_id})
so = synthesis["structured_output"]

expand = POST(f"{BASE}/refinement/expand", {
    "statement": synthesis["clarified_query"],
    "search_context": {"concept_graph": so["concept_graph"]}
})
```

### Quick-reply / examples field

Every `next_prompt` includes an `examples` list:

```json
"examples": ["elderly patients (65+)", "working-age adults (18–64)", "children under 12"]
```

- Each string is a **complete, standalone answer** — submit it verbatim as `answer`.
- Examples span the clarification range; they are not biased toward the LLM's guess.
- Empty list `[]` is valid — it means the question is open-ended or the aspect was auto-completed.
- A clicked example is submitted identically to a free-text answer:
  ```json
  POST /refinement/queries/{query_id}/answer
  { "answer": "elderly patients (65+)" }
  ```

### RAG field mapping

After `POST /synthesize`, `structured_output` contains all retrieval artifacts:

| Use case | Field path | Source agent |
|---|---|---|
| Dense / vector retrieval | `structured_output.search_optimized.semantic` | Agent B |
| **Primary RAG keyword search** | `structured_output.search_optimized.keyword.combined_blocks` | Agent C |
| Boolean anchor query (fallback) | `structured_output.search_optimized.keyword.structured` | Agent C |
| Exact key phrases | `structured_output.search_optimized.keyword.phrases` | Agent C |
| Controlled vocabulary (MeSH, DeCS) | `combined_blocks[i].controlled_vocabulary` | Agent C |
| Metadata narrowing filters | `structured_output.search_filters` | Agent C |
| Synonym expansion per concept | `structured_output.concept_graph.<concept>` | Agent B |
| Clarified research statement | `clarified_query` | Agent A |
| Keyword query (BM25 / simple keyword search) | `structured_output.keyword_statement` | Agent B |
| Per-dimension refined values | `structured_output.dimensions_specifications` | Agent A |
| Terminology / synonym map | `structured_output.terminology` | Agent B (legacy — prefer `concept_graph`) |
| Broadening fallback levels | `POST /expand` with `statement` + `concept_graph` | Agent D |

**`combined_blocks` connector rules:**

```
OR  free_text terms  within each block
OR  controlled_vocabulary terms  within each block
AND all blocks together
```

Use `controlled_vocabulary` only for indexed sources (PubMed → MeSH, WHO IRIS → DeCS).  
Use `free_text` alone for unindexed sources (OpenAlex, CORE, ReliefWeb).

### Error handling for agents

| HTTP code | Meaning | Action |
|---|---|---|
| 401 | Missing or invalid auth | Check `X-API-Key` or `Authorization` header |
| 403 | Framework access denied | Grant the integration user access to the framework |
| 404 | Query/session not found | Session may have expired — restart with `/start` |
| 409 | Already synthesized | Call `/status` to retrieve the existing result |
| 422 | Validation error | Check request body — see error envelope below |
| 503 | Session lock held | Retry after 1–2 s; concurrent request on same session |

Retry pattern for 503 (session contention):
```python
for attempt in range(3):
    r = POST(url, body)
    if r.status_code != 503:
        break
    time.sleep(1.5 ** attempt)
```

---

## Refinement Workflow

- `GET /api/v1/refinement/frameworks`
- `POST /api/v1/refinement/start`
- `POST /api/v1/refinement/queries/{query_id}/answer`
- `GET /api/v1/refinement/queries/{query_id}/status`
- `POST /api/v1/refinement/queries/{query_id}/resume`
- `POST /api/v1/refinement/normalize`
- `POST /api/v1/refinement/represent`
- `POST /api/v1/refinement/construct`
- `POST /api/v1/refinement/synthesize`
- `POST /api/v1/refinement/expand`
- `POST /api/v1/refinement/queries/{query_id}/forward-to-qa`
- `GET /api/v1/refinement/queries/{query_id}/command-history`
- `GET /api/v1/refinement/queries/{query_id}/inspect-messages`
- `GET /api/v1/refinement/queries/{query_id}/progress`
- `POST /api/v1/refinement/sessions/abandon`

Refinement workflow endpoints require either `Authorization: Bearer <token>` or `X-API-Key: <integration-api-key>`.

`X-API-Key` authentication resolves to the configured integration service user. That user must already have framework access assigned, or `/api/v1/refinement/start` will return `403` with `You are not authorized to use framework ...`.

`/api/v1/refinement/start` is **POST-only** (no GET variant is implemented).

`POST /api/v1/refinement/start` accepts:

- `original_query` (string)
- `framework_name` (string)
- `source` (optional: `gui` or `api_integration`, defaults to `gui`)
- `skip_refinement` (optional boolean, defaults to `false`) — when `true`, all refinement dimensions are skipped and synthesis is executed immediately as part of the same request. No per-dimension LLM calls are made; the response contains a `synthesis` object with the final result. Intended for API integrations that want a single-call workflow at the cost of refinement quality.

Start response includes: `session_id`, `query_id`, `summary`, optional `next_prompt`, `ready_for_synthesis`, `source`, and optional `synthesis` (populated only when `skip_refinement=true`).

`POST /api/v1/refinement/queries/{query_id}/answer` returns:

- `SubmitAnswerResponse` for normal answers (includes `ready_for_synthesis`)
- `CommandResponse` for slash commands (includes optional `synthesis_ready` when using `/submit` or `/end`)

### Refinement response shapes

The workflow endpoints return different response envelopes depending on the step.

#### `POST /api/v1/refinement/start`

Returns `StartRefinementResponse` with these fields:

- `session_id`: database session ID
- `query_id`: database query ID
- `summary`: initialization summary for the new workflow
- `next_prompt`: the first refinement question, or `null` if the workflow is already complete
- `ready_for_synthesis`: `true` when no more refinement questions are needed
- `source`: `gui` or `api_integration`
- `synthesis`: present only when `skip_refinement=true`; contains the same synthesis envelope returned by `/refinement/synthesize`

`summary` is a compact object that reports the overall workflow state. Clients should expect counts such as:

- `total_aspects`
- `aspects_needing_refinement`
- `aspects_clear`
- `is_complete`

`next_prompt` is the next question the client should display to the user. It uses this shape:

```json
{
	"aspect_id": "population",
	"name": "Population",
	"question": "Which population does your query target?",
	"description": "Target population characteristics",
	"examples": [
		"elderly patients (65+)",
		"working-age adults (18–64)",
		"children under 12",
		"all ages"
	]
}
```

- `question` — plain prose clarifying question, no embedded examples.
- `examples` — 0–4 concrete quick-reply strings that **span the clarification space**. Each string is a complete, standalone answer the user can select as-is. Intended to be rendered as clickable buttons. Empty when the question does not apply (e.g. the aspect was already clear) or when `complete=true`.

#### `POST /api/v1/refinement/queries/{query_id}/answer`

This endpoint is polymorphic. The response depends on whether the submitted text is a normal answer or a slash command.

Normal answers return `SubmitAnswerResponse`:

- `refinement_step_id`: refinement step record ID
- `followup_id`: follow-up record ID
- `is_complete`: whether the current aspect is complete
- `next_prompt`: the next question, or `null` if no follow-up is needed
- `ready_for_synthesis`: `true` when all aspects are complete and the workflow can move to synthesis

Slash commands return `CommandResponse`:

- `command_type`: the parsed command name such as `status`, `back`, `skip`, `submit`, or `steps`
- `success`: whether the command executed successfully
- `message`: human-readable feedback
- `next_prompt`: the next question after the command, or `null`
- `invalidated_aspects`: aspect IDs that were reset or marked for review
- `synthesis_ready`: `true` when `/submit` or `/end` has completed the workflow
- `step_summary`: present for `/status`
- `step_list`: present for `/steps`
- `force_required`: `true` when the command needs `force=true` to continue

`next_prompt` uses the same shape as the start response. When returned after a command, it can be used directly by the UI without extra transformation.

#### `POST /api/v1/refinement/queries/{query_id}/resume`

Returns `ResumeRefinementResponse` (extends `GetRefinementStatusResponse`) with the same fields as the status endpoint. Use this to explicitly regenerate the next prompt after a server restart or Redis session eviction. The endpoint does not advance the workflow — it only ensures the session is loaded and the active prompt is ready. Returns 404 if the query does not exist, 403 if access is denied, and 503 if the session lock is temporarily held by another request.

#### `GET /api/v1/refinement/queries/{query_id}/status`

- `query_id`: query record ID
- `original_query`: the original user question
- `refined_query`: the latest refined statement, or `null` if synthesis has not completed
- `is_complete`: whether the workflow is fully complete
- `current_aspect`: the current aspect being refined, or `null`
- `aspects_summary`: overall workflow summary
- `next_prompt`: the next question, or `null`
- `ready_for_synthesis`: `true` when synthesis can be started
- `aspects`: per-aspect status records
- `conversation_history`: the UI restoration history for the session

The `aspects` array contains lightweight status objects such as:

```json
{
	"aspect_id": "population",
	"name": "Population",
	"is_complete": false,
	"needs_review": false,
	"was_skipped": false,
	"status": "active"
}
```

The `conversation_history` array is ordered and contains the visible interaction trail. Typical items include:

- `type`: `query`, `question`, or `answer`
- `content`: the message text
- `aspectId`: optional aspect identifier
- `aspectName`: optional display label

#### `POST /api/v1/refinement/synthesize`

Returns `SynthesizeQueryResponse` with these fields:

- `query_id`: query record ID
- `clarified_query`: the final clarified statement
- `used_llm`: whether synthesis used the LLM path
- `structured_output`: optional structured result for clients that need search-ready fields

Canonical synthesis field names used by the API and internal runtime are:

- `clarified_query` (Agent A output; called `statement` when passed as input to Agents B, C, D)
- `dimensions_specifications`
- `search_optimized`
- `search_filters`
- `terminology`
- `metadata`
- `processing_log`

The query persistence schema now uses the same canonical synthesis names. The SQLAlchemy model exposes the `metadata` database column as `synthesis_metadata` because `metadata` is a reserved declarative attribute name.

The detailed `structured_output` contract is described below.

#### `POST /api/v1/refinement/expand`

Generates optional search expansion levels from a standalone request payload. The endpoint does not depend on a persisted query or a completed synthesis result. Callers provide the exact Level 0 statement (from Agent A's `clarified_query`) and optional search context with filters and synonyms.

The service runs a two-stage pipeline:

1. **Aspect assessment** — the anchor query is assessed against a fixed internal ontology of six search aspects: `topic_or_condition`, `population_or_entity`, `intervention_or_exposure_or_phenomenon`, `setting_or_context`, `geography`, and `time_scope`. For each detected aspect, the assessment records the value as expressed in the anchor and an ordered list of strict-superset broadening candidates.
2. **Expansion generation** — a deterministic safety policy classifies each detected aspect as `safe`, `conditional` (`topic_or_condition` and `intervention_or_exposure_or_phenomenon`), or `avoid` (undetected aspects). Expansion levels may relax only safe or conditional aspects, at most two per level, and at most one conditional aspect per level.

Request body:

```json
{
	"statement": "In adults over 65, compare aspirin versus placebo for stroke prevention.",
	"search_context": {
		"filters": {
			"publication_types": ["randomized controlled trial"]
		},
		"concept_graph": {"...": "structured_output.concept_graph from POST /synthesize"}
	},
	"model": "optional-model-override"
}
```

The `statement` parameter is required and must be provided. Optional parameters:
- `search_context`: optional retrieval context. Set `search_context.concept_graph` to `structured_output["concept_graph"]` from a prior `/represent` or `/synthesize` call for best results.
- `model`: optional LLM model override.

`search_context.concept_graph` should be set to `structured_output["concept_graph"]` from a prior `/synthesize` call. It provides the full lexical context (synonyms, domain terms, controlled vocabulary hints) for each concept, enabling more accurate broadening candidates. Without it, Agent D falls back to aspect detection from the anchor query text alone.

Returns `SearchExpandResponse` with these fields:

- `search_expansion_levels`: Level 0 plus up to three broader retrieval levels (Levels 1-3)
- `metadata`: token and generation metadata, including the aspect assessment summary

Each level includes a `strategy` field describing how it broadens retrieval: `anchor` (Level 0 only), `lexical` (spelling/morphological variants, no conceptual broadening), `conceptual_single_aspect`, or `conceptual_multi_aspect`. The `strategy` field is authoritative — do not infer broadening type from the level number alone.

Level 0 is deterministic and always preserves the supplied anchor query:

```json
{
	"level": 0,
	"label": "Exact clarified question",
	"strategy": "anchor",
	"search_query": "...same as statement...",
	"relaxed_aspects": {},
	"rationale": "Exact clarified query preserved as the review anchor."
}
```

The LLM generates only Levels 1-N. The `metadata.status` field reports the outcome: `completed`, `skipped_no_assessable_aspects` (no safe or conditional aspects detected — Level 0 only), or `failed_level_0_only` (generation, parsing, or validation failed — Level 0 only rather than failing the request).

### Generic external integration snippet

```bash
curl -X POST http://localhost:8001/api/v1/refinement/start \
	-H 'Content-Type: application/json' \
	-H 'X-API-Key: <integration-api-key>' \
	-d '{
		"original_query": "effects of aspirin in older adults",
		"framework_name": "pico_advanced",
		"source": "api_integration"
	}'
```

### Expected response structures (integration)

The following are the expected response envelopes for external integrations.

#### `GET /api/v1/refinement/frameworks` (200)

```json
{
	"frameworks": ["pico_advanced", "mph_dissertation"],
	"count": 2
}
```

#### `POST /api/v1/refinement/start` (201)

```json
{
	"session_id": 101,
	"query_id": 123,
	"summary": {
		"total_aspects": 4,
		"aspects_needing_refinement": 3,
		"aspects_clear": 1,
		"is_complete": false
	},
	"next_prompt": {
		"aspect_id": "population",
		"name": "Population",
		"question": "Which population does your query target?",
		"description": "Target population characteristics",
		"examples": ["elderly patients (65+)", "working-age adults (18–64)", "children under 12"]
	},
	"ready_for_synthesis": false,
	"source": "api_integration",
	"synthesis": null
}
```

Notes:

- `next_prompt` can be `null` when the session is already complete.
- `ready_for_synthesis=true` means the next call should be `/refinement/synthesize`.
- `synthesis` is `null` in normal flow. When `skip_refinement=true` it is populated with the same envelope as `/refinement/synthesize` so no follow-up call is needed.

##### `POST /api/v1/refinement/start` with `skip_refinement=true` (201)

```bash
curl -X POST http://localhost:8001/api/v1/refinement/start \
	-H 'Content-Type: application/json' \
	-H 'X-API-Key: <integration-api-key>' \
	-d '{
		"original_query": "effects of aspirin in older adults",
		"framework_name": "pico_advanced",
		"source": "api_integration",
		"skip_refinement": true
	}'
```

```json
{
	"session_id": 101,
	"query_id": 124,
	"summary": {
		"total_aspects": 4,
		"aspects_needing_refinement": 0,
		"aspects_clear": 4,
		"is_complete": true
	},
	"next_prompt": null,
	"ready_for_synthesis": true,
	"source": "api_integration",
	"synthesis": {
		"query_id": 124,
		"clarified_query": "In adults, compare aspirin versus placebo for stroke prevention.",
		"used_llm": true,
		"structured_output": null
	}
}
```

Notes:

- All dimensions are recorded as skipped in the database (audit trail preserved).
- A subsequent call to `/refinement/synthesize` will return `409 Conflict` because synthesis was already performed.
- The `/refinement/synthesize` endpoint remains available for normal (non-skip) workflows.

#### `POST /api/v1/refinement/queries/{query_id}/answer` (200)

Request body (for both regular answers and slash commands):

```json
{ "answer": "elderly patients aged 65 and over" }
```

To submit a quick-reply example, send its string verbatim:

```json
{ "answer": "elderly patients (65+)" }
```

Slash commands use the same field:

```json
{ "answer": "/skip" }
{ "answer": "/back" }
{ "answer": "/status" }
{ "answer": "/done" }
{ "answer": "/submit" }
```

This endpoint has two response types.

**A) Regular answer (`SubmitAnswerResponse`)**

```json
{
	"refinement_step_id": 88,
	"followup_id": 351,
	"is_complete": false,
	"next_prompt": {
		"aspect_id": "population",
		"name": "Population",
		"question": "Any age range constraints?",
		"description": "Target population characteristics",
		"examples": ["all ages", "adults only (18+)", "elderly (65+)"]
	},
	"ready_for_synthesis": false
}
```

**B) Slash command (`CommandResponse`)**

```json
{
	"command_type": "status",
	"success": true,
	"message": "Session status retrieved",
	"next_prompt": {
		"aspect_id": "intervention",
		"name": "Intervention",
		"question": "Which intervention does your query examine?",
		"description": "Intervention details",
		"examples": ["drug therapy", "surgical procedure", "behavioural intervention"]
	},
	"invalidated_aspects": null,
	"synthesis_ready": null,
	"step_summary": {
		"total": 4,
		"completed": 2,
		"active": 1,
		"needs_review": 0
	},
	"step_list": null,
	"force_required": null
}
```

Command-specific fields to expect:

- `/status` -> `step_summary` populated
- `/steps` -> `step_list` populated
- `/submit`, `/end` -> `synthesis_ready=true`, `next_prompt=null`
- `/back`, `/restart` -> `invalidated_aspects` may be populated
- force confirmation required -> `force_required=true`

#### `POST /api/v1/refinement/queries/{query_id}/resume` (200)

Returns the same JSON envelope as `GET /api/v1/refinement/queries/{query_id}/status`. The endpoint reconstructs the session from the database if it is not in Redis, regenerates the active prompt if one is missing, and returns the current workflow state. Idempotent — safe to call multiple times.

#### `GET /api/v1/refinement/queries/{query_id}/status` (200)

```json
{
	"query_id": 123,
	"original_query": "effects of aspirin in older adults",
	"refined_query": null,
	"is_complete": false,
	"current_aspect": "Population",
	"aspects_summary": {
		"total_aspects": 4,
		"aspects_needing_refinement": 2,
		"aspects_clear": 2,
		"is_complete": false
	},
	"next_prompt": {
		"aspect_id": "population",
		"name": "Population",
		"question": "Any age range constraints?",
		"description": "Target population characteristics",
		"examples": ["all ages", "adults only (18+)", "elderly (65+)"]
	},
	"ready_for_synthesis": false,
	"aspects": [
		{
			"aspect_id": "population",
			"name": "Population",
			"is_complete": false,
			"needs_review": false,
			"was_skipped": false,
			"status": "active"
		}
	],
	"conversation_history": [
		{"type": "query", "content": "effects of aspirin in older adults"},
		{"type": "question", "content": "Which population are you focusing on?", "aspectId": "population", "aspectName": "Population"},
		{"type": "answer", "content": "Adults over 65", "aspectId": "population"}
	]
}
```

#### `POST /api/v1/refinement/synthesize` (200)

Request body:

```json
{ "query_id": 123 }
```

Response:

```json
{
	"query_id": 123,
	"clarified_query": "In adults over 65, compare aspirin versus placebo for stroke prevention.",
	"used_llm": true,
	"structured_output": {
		"dimensions_specifications": {
			"population": "Adults over 65",
			"intervention": "Aspirin",
			"comparator": "Placebo",
			"outcome": "Stroke prevention"
		},
		"search_optimized": {
			"semantic": "Studies of aspirin compared with placebo for stroke prevention in adults over 65.",
			"keyword": {
				"structured": "(aspirin OR acetylsalicylic acid OR ASA) AND (placebo OR control OR sham) AND (stroke prevention OR cerebrovascular accident prevention OR stroke prophylaxis)",
				"phrases": ["stroke prevention", "older adults", "aspirin trial"],
				"terms": {
					"required": ["aspirin", "stroke", "placebo"],
					"optional": ["acetylsalicylic acid", "cerebrovascular", "older adults"],
					"excluded": []
				},
				"combined_blocks": [
					{
						"role": "topic_or_condition",
						"free_text": ["stroke prevention", "cerebrovascular accident prevention", "stroke prophylaxis"],
						"controlled_vocabulary": {
							"MeSH": ["Stroke", "Brain Ischemia", "Cerebrovascular Disorders"]
						}
					},
					{
						"role": "population_or_entity",
						"free_text": ["adults over 65", "older adults", "elderly"],
						"controlled_vocabulary": {
							"MeSH": ["Aged", "Aged, 80 and over"]
						}
					},
					{
						"role": "intervention_or_exposure_or_phenomenon",
						"free_text": ["aspirin", "acetylsalicylic acid", "ASA"],
						"controlled_vocabulary": {
							"MeSH": ["Aspirin", "Platelet Aggregation Inhibitors"]
						}
					}
				]
			},
		},
		"concept_graph": {
			"aspirin": {
				"query_role": "intervention_or_exposure_or_phenomenon",
				"true_synonyms": ["acetylsalicylic acid"],
				"abbreviations": ["ASA"],
				"spelling_variants": [],
				"lexical_variants": [],
				"domain_terms": ["antiplatelet agent", "salicylate"],
				"colloquial": ["blood thinner"],
				"controlled_vocabulary_hints": [
					{"vocabulary_name": "MeSH", "terms": ["Aspirin", "Platelet Aggregation Inhibitors"], "confidence": "high"}
				]
			},
			"stroke prevention": {
				"query_role": "topic_or_condition",
				"true_synonyms": ["cerebrovascular accident prevention", "stroke prophylaxis"],
				"abbreviations": [],
				"spelling_variants": [],
				"lexical_variants": [],
				"domain_terms": ["ischaemic stroke prevention", "TIA prevention"],
				"colloquial": ["clot prevention"],
				"controlled_vocabulary_hints": [
					{"vocabulary_name": "MeSH", "terms": ["Stroke", "Brain Ischemia"], "confidence": "high"}
				]
			},
			"adults over 65": {
				"query_role": "population_or_entity",
				"true_synonyms": ["older adults", "elderly"],
				"abbreviations": [],
				"spelling_variants": [],
				"lexical_variants": [],
				"domain_terms": ["geriatric population", "senior adults"],
				"colloquial": ["elderly people"],
				"controlled_vocabulary_hints": [
					{"vocabulary_name": "MeSH", "terms": ["Aged", "Aged, 80 and over"], "confidence": "high"}
				]
			}
		},
		"search_filters": {
			"publication_years": "2020-2026",
			"venues": [],
			"authors": [],
			"publication_types": [],
			"fields_of_study": ["Medicine", "Public Health"]
		},
		"terminology": {
			"synonyms": {
				"aspirin": ["acetylsalicylic acid", "ASA"],
				"placebo": ["sham", "control"],
				"stroke prevention": ["cerebrovascular prevention", "stroke prophylaxis"]
			}
		}
	}
}
```

Notes:

- `structured_output` can be `null` when the service cannot derive a structured payload from the synthesis result.
- When present, `structured_output` is assembled from the three internal synthesis agents (A → B → C):
  - `clarified_query` (**Agent A**): clarified research statement — the review anchor and Level 0 query (passed as `statement` to Agents B, C, D)
  - `dimensions_specifications` (**Agent A**): the refined value for each dimension, keyed by dimension id — assembled deterministically from session state, never from the LLM
  - `search_optimized` (**Agents B + C**): retrieval-ready search artifacts:
    - `semantic` (**Agent B**): dense embedding query for vector search
    - `keyword.structured` (**Agent C**): Boolean anchor query for sparse/keyword search
    - `keyword.combined_blocks` (**Agent C**): **primary RAG artifact** — one entry per AND-block with `role`, `free_text` terms, and `controlled_vocabulary` (vocabulary name → headings). Source connectors: OR `free_text` with `controlled_vocabulary` within each block, then AND all blocks. Use `controlled_vocabulary` only for indexed databases (PubMed → MeSH, WHO IRIS → DeCS); use `free_text` alone for unindexed sources.
  - `concept_graph` (**Agent B**): per-concept retrieval metadata — pass as `search_context.concept_graph` to `/expand` for Agent D broadening levels. Each concept entry has: `query_role`, `true_synonyms`, `abbreviations`, `spelling_variants`, `lexical_variants`, `domain_terms`, `colloquial`, `controlled_vocabulary_hints`.
  - `search_filters` (**Agent C**): optional narrowing filters — `publication_years`, `venues`, `authors`, and `publication_types` are extracted deterministically from the query text; `fields_of_study` is LLM-generated and constrained to a permitted-values list
  - `terminology` (**Agent B**, legacy): synonym mappings — use `concept_graph` in preference to this for structured retrieval
- `search_optimized.keyword.terms.required` contains the smallest set of anchors that should remain in the query.
- `search_optimized.keyword.terms.optional` contains precision-raising terms.
- `search_optimized.keyword.terms.excluded` contains only true confounders, not close variants of the target concept.

#### `POST /api/v1/refinement/expand` (200)

```json
{
	"search_expansion_levels": [
		{
			"level": 0,
			"label": "Exact clarified question",
			"strategy": "anchor",
			"search_query": "In adults over 65, compare aspirin versus placebo for stroke prevention.",
			"relaxed_aspects": {},
			"rationale": "Exact clarified query preserved as the review anchor."
		},
		{
			"level": 1,
			"label": "Lexical variants",
			"strategy": "lexical",
			"search_query": "In adults over 65, compare aspirin or acetylsalicylic acid versus placebo for stroke prevention.",
			"relaxed_aspects": {},
			"rationale": "Adds synonym variants without conceptual broadening."
		},
		{
			"level": 2,
			"label": "Broader older adult population",
			"strategy": "conceptual_single_aspect",
			"search_query": "Studies comparing aspirin and placebo for stroke prevention in older adult populations.",
			"relaxed_aspects": {
				"population_or_entity": "older adult populations"
			},
			"rationale": "Broadens the exact age threshold to improve recall while preserving the intervention, comparator, and outcome."
		}
	],
	"metadata": {
		"used_llm": true,
		"status": "completed",
		"generated_level_count": 2,
		"allowed_aspect_count": 3,
		"aspect_assessment": {
			"assessed_aspects": ["..."],
			"safe_aspects": ["population_or_entity"],
			"conditional_aspects": ["topic_or_condition", "intervention_or_exposure_or_phenomenon"],
			"avoided_aspects": ["setting_or_context", "geography", "time_scope"]
		},
		"prompt_tokens": 500,
		"completion_tokens": 120,
		"total_tokens": 620
	}
}
```

Notes:

- `search_expansion_levels[0].search_query` always equals the supplied `statement` exactly.
- Levels 1-N are optional search-only broadening variants. They do not update `statement` or redefine the review scope.
- `relaxed_aspects` keys are always drawn from the fixed six-aspect ontology, never from framework dimension ids.
- `metadata.status` is one of `completed`, `skipped_no_assessable_aspects`, or `failed_level_0_only`; the latter two return Level 0 only with warning metadata.

#### `POST /api/v1/refinement/queries/{query_id}/forward-to-qa` (200)

Request body:

```json
{
	"qa_system_url": "https://qa.example.com/api/query",
	"qa_system_auth": { "Authorization": "Bearer <token>" },
	"timeout_seconds": 30,
	"include_refinement_metadata": true,
	"forward_original_query": false
}
```

- `qa_system_url` must be a public HTTPS URL — private/loopback IPs and RFC-1918 addresses are rejected.
- `qa_system_auth` accepts any custom HTTP headers except hop-by-hop headers (`host`, `connection`, etc.).
- `forward_original_query`: when `true`, the original unrefined query is also sent alongside the refined query.

Response:

```json
{
	"query_id": 123,
	"refined_query": "In adults over 65, compare aspirin versus placebo for stroke prevention.",
	"original_query": null,
	"qa_system_url": "https://qa.example.com/api/query",
	"qa_system_response": {
		"answer": "..."
	},
	"qa_system_status_code": 200,
	"response_time_ms": 1250,
	"refinement_metadata": {
		"framework": "pico_advanced",
		"total_steps": 4,
		"dimensions_refined": ["population", "intervention", "comparator", "outcome"],
		"query_id": 123
	}
}
```

Notes:

- `original_query` is only included when `forward_original_query=true`.
- `refinement_metadata` is only included when `include_refinement_metadata=true`.

#### `GET /api/v1/refinement/queries/{query_id}/command-history` (200)

```json
{
	"query_id": 123,
	"total_commands": 2,
	"commands": [
		{
			"timestamp": "2026-02-23T10:00:00.000000",
			"event_id": 9001,
			"command": "status",
			"command_input": "/status",
			"argument": null,
			"active_dimension": "population",
			"success": true,
			"status": "success",
			"force_requested": false,
			"force_confirmation_needed": false,
			"cleared_aspects": null,
			"invalidated_aspects": null,
			"target_aspect": null,
			"deleted_db_records": null,
			"username": "api_integration_service",
			"request_id": "req_abc123"
		}
	]
}
```

#### `GET /api/v1/refinement/queries/{query_id}/inspect-messages` (200)

```json
{
	"query_id": 123,
	"current_dimension": "population",
	"message_count": 3,
	"messages": [
		{"role": "system", "content": "..."},
		{"role": "user", "content": "..."}
	],
	"user_context_detected": true,
	"user_context_preview": "User Context: ..."
}
```

#### `POST /api/v1/refinement/sessions/abandon` (200)

```json
{
	"status": "success",
	"session_id": 101,
	"deletion_counts": {
		"queries": 1,
		"refinement_steps": 4,
		"followups": 7,
		"feedback": 0
	},
	"message": "Session 101 abandoned successfully. Deleted 1 queries, 4 refinement steps."
}
```

#### `GET /api/v1/refinement/queries/{query_id}/progress` (200)

```json
{
	"query_id": "123",
	"stage": "generating_suggestions",
	"progress": 0.4,
	"message": "Generating refinement suggestions...",
	"started_at": "2026-02-23T10:30:00Z",
	"updated_at": "2026-02-23T10:30:08Z",
	"elapsed_seconds": 8.2,
	"turn_number": 2,
	"total_turns": 4,
	"llm_calls_made": 2
}
```

## Common error structure

Validation errors use a detailed envelope:

```json
{
	"detail": "Validation error",
	"errors": [
		{
			"field": "body -> original_query",
			"message": "Field required",
			"type": "missing"
		}
	]
}
```

Most non-validation API errors return:

```json
{
	"detail": "Human-readable error message"
}
```

## Queries and Sessions

- `POST /api/v1/queries/sessions`
- `GET /api/v1/queries/sessions`
- `GET /api/v1/queries/sessions/{session_id}`
- `POST /api/v1/queries/sessions/{session_id}/end`
- `POST /api/v1/queries`
- `GET /api/v1/queries/{query_id}`
- `PUT /api/v1/queries/{query_id}`
- `GET /api/v1/queries/sessions/{session_id}/queries`
- `POST /api/v1/queries/refinement-steps`
- `GET /api/v1/queries/{query_id}/refinement-steps`
- `POST /api/v1/queries/followups`
- `PUT /api/v1/queries/followups/{followup_id}`
- `GET /api/v1/queries/refinement-steps/{step_id}/followups`

When a query has already been synthesized, `QueryResponse` exposes the canonical synthesis fields:

- `clarified_query`
- `dimensions_specifications`
- `search_optimized`
- `search_filters`
- `terminology`
- `search_expansion_levels`
- `metadata`
- `processing_log`

`refined_query` remains available only as a legacy convenience field.

## Feedback

- `POST /api/v1/feedback`
- `GET /api/v1/feedback/my-feedback`
- `GET /api/v1/feedback/query/{query_id}`

## Audit Logs

Audit log endpoints require a superuser account.

- `GET /api/v1/audit/logs` — paginated log list; supports filters `event_type`, `user_id`, `start_date`, `end_date`
- `GET /api/v1/audit/logs/{audit_id}` — single log entry by ID
- `GET /api/v1/audit/stats` — aggregated event counts and activity summary
- `GET /api/v1/audit/event-types` — list of all known event type strings
- `GET /api/v1/audit/trace/{request_id}` — all log entries sharing a request ID (full request trace)
- `GET /api/v1/audit/export/csv` — download log entries as CSV
- `GET /api/v1/audit/export/json` — download log entries as JSON
- `DELETE /api/v1/audit/cleanup` — delete log entries older than a configurable retention period

## Monitoring

- `GET /api/v1/monitoring/llm-health`
- `GET /api/v1/monitoring/circuit-breakers`

## Frontend Logs

- `POST /api/v1/logs/frontend`
- `GET /api/v1/logs/frontend`
- `GET /api/v1/logs/frontend/stats`
- `GET /api/v1/logs/frontend/errors`
- `GET /api/v1/logs/frontend/trace/{request_id}`

## Metadata

- `GET /api/version` (unversioned)
- `GET /health`
- `GET /ready`

## User Commands

The frontend and API accept slash commands during refinement:

- `/back`, `/prev`
- `/restart`
- `/skip` (marks current dimension skipped, no final value persisted)
- `/done` (marks current dimension complete and persists captured current value, including partial values)
- `/submit`, `/end`
- `/status`
- `/steps`
- `/help`

## Admin Endpoints

Admin endpoints require a superuser account.

- Core admin routes use: `/api/v1/admin/...`
- Additional admin route groups are exposed under: `/api/v1/api/admin/...`

Current split:

- Sessions: `/api/v1/api/admin/sessions/...`
- Frameworks: `/api/v1/api/admin/frameworks/...`
- Analytics: `/api/v1/api/admin/analytics/...`

Notable analytics endpoint:

- `GET /api/v1/api/admin/analytics/dashboard`

If you are building a new integration, prefer non-admin workflow routes under `/api/v1/refinement/*`, `/api/v1/queries/*`, and `/api/v1/webhooks/*` unless superuser-level operations are required.
