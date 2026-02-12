# Middleware Integration Guide for External Q&A Systems

## Overview
This guide describes how to integrate the Query Refinement Module as a middleware layer in front of an external Q&A system.

The module runs a user-driven multi-turn refinement flow, synthesizes a refined query, and can forward the result to your external service.

All endpoints are versioned under `/api/v1`.

## Core Integration Flow
1. User starts refinement.
2. User answers follow-up questions across dimensions.
3. Client triggers synthesis.
4. Client calls forward-to-QA endpoint.
5. Middleware returns external QA response and metadata.

## Required Endpoints

### 1) Start refinement
`POST /api/v1/refinement/start`

Request:
```json
{
  "original_query": "effects of aspirin",
  "framework_name": "pico_advanced"
}
```

### 2) Submit answers and commands
`POST /api/v1/refinement/queries/{query_id}/answer`

Request:
```json
{
  "answer": "adults over 65",
  "force": false
}
```

### 3) Check status
`GET /api/v1/refinement/queries/{query_id}/status`

### 4) Synthesize refined query
`POST /api/v1/refinement/synthesize`

Request:
```json
{
  "query_id": 123
}
```

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

## Error Handling
- `400`: refinement not complete or invalid request
- `403`: unauthorized query access
- `404`: query not found
- `502`: external QA system unreachable
- `504`: external QA timeout

## Minimal Python Example
```python
import requests

API = "http://localhost:8000/api/v1"
TOKEN = "your-token"
HEADERS = {"Authorization": f"Bearer {TOKEN}"}

# 1) Start
start = requests.post(
    f"{API}/refinement/start",
    json={"original_query": "effects of aspirin", "framework_name": "pico_advanced"},
    headers=HEADERS,
).json()
query_id = start["query_id"]

# 2) Iterative refinement loop (example)
while True:
    status = requests.get(f"{API}/refinement/queries/{query_id}/status", headers=HEADERS).json()
    if status.get("ready_for_synthesis"):
        break

    prompt = status.get("next_prompt")
    if not prompt:
        break

    user_answer = "example user answer"
    requests.post(
        f"{API}/refinement/queries/{query_id}/answer",
        json={"answer": user_answer, "force": False},
        headers=HEADERS,
    )

# 3) Synthesize
requests.post(
    f"{API}/refinement/synthesize",
    json={"query_id": query_id},
    headers=HEADERS,
)

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
).json()

print(forward["refined_query"])
print(forward["qa_system_response"])
```

## Webhooks (Optional)
Webhook APIs are available at `/api/v1/webhooks` for event-driven integrations.

Typical events for this flow:
- `refinement.started`
- `refinement.step_completed`
- `refinement.complete`
- `synthesis.started`
- `synthesis.complete`
- `query.forwarded`

## Production Notes
- Use `/api/v1` consistently in clients and scripts.
- Use `ALLOW_REGISTRATION=false` when credentials are provisioned by admins.
- Ensure `ALLOWED_ORIGINS` includes frontend and middleware callers.
- Set `LOG_FORMAT=json` and `LOG_FILE` for operational visibility.
- Keep `timeout_seconds` conservative when forwarding to external systems.
