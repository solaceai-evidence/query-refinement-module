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

## Refinement Workflow

- `GET /api/v1/refinement/frameworks`
- `POST /api/v1/refinement/start`
- `POST /api/v1/refinement/queries/{query_id}/answer`
- `GET /api/v1/refinement/queries/{query_id}/status`
- `POST /api/v1/refinement/queries/{query_id}/resume`
- `POST /api/v1/refinement/synthesize`
- `POST /api/v1/refinement/queries/{query_id}/search-expand`
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
	"question": "Which population are you focusing on?",
	"description": "Target population characteristics"
}
```

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
- `integrated_statement`: the final refined statement
- `used_llm`: whether synthesis used the LLM path
- `structured_output`: optional structured result for clients that need search-ready fields

Canonical synthesis field names used by the API and internal runtime are:

- `integrated_statement`
- `dimensions_specifications`
- `search_optimized`
- `search_filters`
- `terminology`
- `metadata`
- `processing_log`

The query persistence schema now uses the same canonical synthesis names. The SQLAlchemy model exposes the `metadata` database column as `synthesis_metadata` because `metadata` is a reserved declarative attribute name.

The detailed `structured_output` contract is described below.

#### `POST /api/v1/refinement/queries/{query_id}/search-expand`

Generates optional search expansion levels from an already completed synthesis result. This endpoint is independent of `/refinement/synthesize`; synthesis must be called first, and search expansion reads the persisted synthesis fields from the query record.

Request body is optional:

```json
{
	"model": "optional-model-override"
}
```

Returns `SearchExpandResponse` with these fields:

- `query_id`: query record ID
- `search_expansion_levels`: Level 0 plus optional broader retrieval levels
- `metadata`: token and generation metadata for the search expansion call

Level 0 is deterministic and always preserves the canonical refined statement:

```json
{
	"level": 0,
	"label": "Exact clarified question",
	"search_query": "...same as integrated_statement...",
	"relaxed_dimensions": {},
	"rationale": "Exact clarified query preserved as the review anchor."
}
```

The LLM generates only Levels 1-N. If generation, parsing, or validation fails, the endpoint returns Level 0 only rather than failing the completed synthesis. If synthesis has not yet completed for the query, the endpoint returns `409 Conflict`.

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
		"question": "Which population are you focusing on?",
		"description": "Target population characteristics"
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
		"integrated_statement": "In adults, compare aspirin versus placebo for stroke prevention.",
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
		"description": "Target population characteristics"
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
		"question": "Which intervention are you comparing?",
		"description": "Intervention details"
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
		"description": "Target population characteristics"
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

```json
{
	"query_id": 123,
	"integrated_statement": "In adults over 65, compare aspirin versus placebo for stroke prevention.",
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
				"structured": "(aspirin OR acetylsalicylic acid) AND (placebo OR control) AND (stroke prevention OR cerebrovascular accident prevention)",
				"phrases": ["stroke prevention", "older adults", "aspirin trial"],
				"terms": {
					"required": ["aspirin", "stroke", "placebo"],
					"optional": ["acetylsalicylic acid", "cerebrovascular", "older adults"],
					"excluded": []
				}
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
- When present, `structured_output` is a JSON object with four sections:
  - `dimensions_specifications`: the refined value for each dimension, keyed by dimension id — assembled deterministically from session state, never from the LLM
  - `search_optimized`: retrieval-ready search text, including `semantic`, `keyword`, and optional `grey_literature`
  - `search_filters`: optional narrowing filters — `publication_years`, `venues`, `authors`, and `publication_types` are extracted deterministically from the query text; `fields_of_study` is LLM-generated and constrained to a permitted-values list
  - `terminology`: synonym mappings used to expand recall during search construction — LLM-generated
- `search_optimized.keyword.terms.required` contains the smallest set of anchors that should remain in the query.
- `search_optimized.keyword.terms.optional` contains precision-raising terms.
- `search_optimized.keyword.terms.excluded` contains only true confounders, not close variants of the target concept.

#### `POST /api/v1/refinement/queries/{query_id}/search-expand` (200)

```json
{
	"query_id": 123,
	"search_expansion_levels": [
		{
			"level": 0,
			"label": "Exact clarified question",
			"search_query": "In adults over 65, compare aspirin versus placebo for stroke prevention.",
			"relaxed_dimensions": {},
			"rationale": "Exact clarified query preserved as the review anchor."
		},
		{
			"level": 1,
			"label": "Broader older adult population",
			"search_query": "Studies comparing aspirin and placebo for stroke prevention in older adult populations.",
			"relaxed_dimensions": {
				"population": "older adult populations"
			},
			"rationale": "Broadens the exact age threshold to improve recall while preserving the intervention, comparator, and outcome."
		}
	],
	"metadata": {
		"used_llm": true,
		"status": "completed",
		"generated_level_count": 1,
		"accepted_dimension_count": 4,
		"prompt_tokens": 500,
		"completion_tokens": 120,
		"total_tokens": 620
	}
}
```

Notes:

- Call `/api/v1/refinement/synthesize` first. This endpoint reconstructs its input from the persisted synthesis fields and returns `409 Conflict` if synthesis has not completed.
- `search_expansion_levels[0].search_query` always equals the persisted `integrated_statement` exactly.
- Levels 1-N are optional search-only broadening variants. They do not update `integrated_statement` or redefine the review scope.
- If expansion generation fails validation, the response still returns Level 0 with warning metadata.

#### `POST /api/v1/refinement/queries/{query_id}/forward-to-qa` (200)

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

- `integrated_statement`
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

## Webhooks

- `GET /api/v1/webhooks/event-types`
- `POST /api/v1/webhooks`
- `GET /api/v1/webhooks`
- `GET /api/v1/webhooks/{webhook_id}`
- `PUT /api/v1/webhooks/{webhook_id}`
- `DELETE /api/v1/webhooks/{webhook_id}`
- `POST /api/v1/webhooks/{webhook_id}/regenerate-secret`
- `POST /api/v1/webhooks/{webhook_id}/test`
- `GET /api/v1/webhooks/{webhook_id}/deliveries`
- `GET /api/v1/webhooks/deliveries/recent`

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
