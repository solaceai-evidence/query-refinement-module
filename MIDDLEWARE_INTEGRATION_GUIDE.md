# Middleware Integration Guide for External Q&A Systems

## Overview

This guide describes how to use the Query Refinement Module as a middleware layer in front of an external Q&A service.

The middleware:

1. Collects clarifications across refinement dimensions
2. Synthesizes a final integrated query
3. Optionally forwards that query to your external Q&A endpoint
4. Returns the downstream response with refinement metadata

All API routes in this guide are under `/api/v1`.

## End-to-End Flow

1. Authenticate user
2. Start refinement (`/refinement/start`)
3. Repeat status/answer loop until `ready_for_synthesis=true`
4. Synthesize (`/refinement/synthesize`)
5. Forward to external QA (`/refinement/queries/{query_id}/forward-to-qa`)

## Endpoint Contracts

### 1) Start refinement

`POST /api/v1/refinement/start`

Request:

```json
{
  "original_query": "effects of aspirin",
  "framework_name": "pico_advanced"
}
```

### 2) Submit answer (or slash command)

`POST /api/v1/refinement/queries/{query_id}/answer`

Request:

```json
{
  "answer": "adults over 65",
  "force": false
}
```

Notes:

- `answer` may be natural language or a slash command (for example `/back`, `/status`)
- Use `force=true` only for commands that explicitly require confirmation

### 3) Check status

`GET /api/v1/refinement/queries/{query_id}/status`

Integration-critical fields:

- `ready_for_synthesis` (boolean gate for synthesize call)
- `next_prompt` (next question payload)
- `is_complete` (workflow status)

### 4) Synthesize

`POST /api/v1/refinement/synthesize`

Request:

```json
{
  "query_id": 123
}
```

Response includes:

- `integrated_statement` (canonical refined output)
- `structured_output` (optional JSON decomposition when available)

### 5) Forward to external QA

`POST /api/v1/refinement/queries/{query_id}/forward-to-qa`

Request:

```json
{
  "qa_system_url": "https://your-qa-system.com/api/query",
  "qa_system_auth": {
    "Authorization": "Bearer your-qa-token"
  },
  "timeout_seconds": 30,
  "include_refinement_metadata": true,
  "forward_original_query": false
}
```

Validation constraints:

- `timeout_seconds` must be between `5` and `120`
- Forwarding requires synthesis to be complete (`refined_query` present)
- Query ownership is enforced per authenticated user

Response:

```json
{
  "query_id": 123,
  "refined_query": "aspirin vs placebo for stroke prevention in adults over 65",
  "original_query": null,
  "qa_system_url": "https://your-qa-system.com/api/query",
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

## Error and Retry Strategy

### API status behavior

- `400`: incomplete synthesis or invalid payload
- `403`: authenticated user does not own this query
- `404`: query not found
- `502`: downstream QA system connection/request failure
- `504`: downstream QA timeout
- `500`: unexpected middleware failure

### Recommended client retry policy

- Do not retry `400`, `403`, `404`
- Retry `502`/`504` with exponential backoff and jitter
- Use bounded retries (`2..3` attempts) and log correlation IDs
- Make downstream Q&A endpoint idempotent when possible

## Minimal Python Integration Example

```python
import requests

API = "http://localhost:8000/api/v1"
TOKEN = "your-token"
HEADERS = {"Authorization": f"Bearer {TOKEN}"}

# 1) Start refinement
start = requests.post(
    f"{API}/refinement/start",
    json={"original_query": "effects of aspirin", "framework_name": "pico_advanced"},
    headers=HEADERS,
)
start.raise_for_status()
query_id = start.json()["query_id"]

# 2) Iterate until ready_for_synthesis
while True:
    status = requests.get(f"{API}/refinement/queries/{query_id}/status", headers=HEADERS)
    status.raise_for_status()
    state = status.json()

    if state.get("ready_for_synthesis"):
        break

    next_prompt = state.get("next_prompt")
    if not next_prompt:
        raise RuntimeError("No next prompt and not ready_for_synthesis")

    answer_res = requests.post(
        f"{API}/refinement/queries/{query_id}/answer",
        json={"answer": "example user answer", "force": False},
        headers=HEADERS,
    )
    answer_res.raise_for_status()

# 3) Synthesize
synth = requests.post(
    f"{API}/refinement/synthesize",
    json={"query_id": query_id},
    headers=HEADERS,
)
synth.raise_for_status()

# 4) Forward to external QA
forward = requests.post(
    f"{API}/refinement/queries/{query_id}/forward-to-qa",
    json={
        "qa_system_url": "https://your-qa-system.com/api/query",
        "qa_system_auth": {"Authorization": "Bearer qa-token"},
        "timeout_seconds": 30,
        "include_refinement_metadata": True,
        "forward_original_query": False,
    },
    headers=HEADERS,
)
forward.raise_for_status()
data = forward.json()

print(data["refined_query"])
print(data["qa_system_status_code"])
print(data["qa_system_response"])
```

## Webhooks (Optional, Event-Driven Integration)

Webhook management endpoints are under `/api/v1/webhooks`.

Typical event sequence for this workflow:

- `refinement.started`
- `refinement.step_completed`
- `refinement.complete`
- `synthesis.started`
- `synthesis.complete`
- `query.forwarded`

## Production Integration Notes

- Use `/api/v1` consistently across all clients and middleware adapters
- Keep `ALLOW_REGISTRATION=false` when users are provisioned administratively
- Set `ALLOWED_ORIGINS` to all browser-based callers
- Verify QA system URL is reachable from inside the API container network path
- Keep `timeout_seconds` conservative to avoid thread/worker starvation
- Persist logs in JSON format for observability (`LOG_FORMAT=json`)
