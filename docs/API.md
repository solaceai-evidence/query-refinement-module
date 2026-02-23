# API Guide

All endpoints are versioned under `/api/v1` unless noted.

## Authentication

- `POST /api/v1/auth/register` (available only when `ALLOW_REGISTRATION=true`; returns 403 when disabled)
- `POST /api/v1/auth/login`
- `GET /api/v1/auth/me`
- `GET /api/v1/auth/me/status`
- `POST /api/v1/auth/logout`

JWT access tokens use the `Authorization: Bearer <token>` header.

For server-to-server integrations, refinement workflow endpoints also support `X-API-Key: <integration-api-key>` when `INTEGRATION_API_KEY` is configured on the API service.

## Refinement Workflow

- `GET /api/v1/refinement/frameworks`
- `POST /api/v1/refinement/start`
- `POST /api/v1/refinement/queries/{query_id}/answer`
- `GET /api/v1/refinement/queries/{query_id}/status`
- `POST /api/v1/refinement/synthesize`
- `POST /api/v1/refinement/queries/{query_id}/forward-to-qa`
- `GET /api/v1/refinement/queries/{query_id}/command-history`
- `GET /api/v1/refinement/queries/{query_id}/inspect-messages`
- `GET /api/v1/refinement/queries/{query_id}/progress`
- `POST /api/v1/refinement/sessions/abandon`

Refinement workflow endpoints require either `Authorization: Bearer <token>` or `X-API-Key: <integration-api-key>`.

`/api/v1/refinement/start` is **POST-only** (no GET variant is implemented).

`POST /api/v1/refinement/start` accepts:

- `original_query` (string)
- `framework_name` (string)
- `source` (optional: `gui` or `api_integration`, defaults to `gui`)

Start response includes: `session_id`, `query_id`, `summary`, optional `next_prompt`, `ready_for_synthesis`, and `source`.

`POST /api/v1/refinement/queries/{query_id}/answer` returns:

- `SubmitAnswerResponse` for normal answers (includes `ready_for_synthesis`)
- `CommandResponse` for slash commands (includes optional `synthesis_ready` when using `/submit` or `/end`)

### Generic external integration snippet

```bash
curl -X POST http://localhost:8000/api/v1/refinement/start \
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
	"source": "api_integration"
}
```

Notes:

- `next_prompt` can be `null` when the session is already complete.
- `ready_for_synthesis=true` means the next call should be `/refinement/synthesize`.

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
		"search_optimized": {},
		"search_filters": {},
		"terminology": {}
	}
}
```

Notes:

- `structured_output` can be `null`.

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
