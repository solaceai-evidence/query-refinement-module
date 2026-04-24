"""Mock vLLM server for constrained decoding integration testing.

Mimics the vLLM OpenAI-compatible REST API.  Does NOT require a GPU.

It inspects the ``guided_json`` field that the LiteLLM provider injects via
``extra_body`` and returns a minimal schema-conformant JSON response for the
two structured models used by this application:

- ``DimensionEvaluationResponse``  (complete / current / question)
- ``QueryRefinementResponse``      (synthesized_statement / dimensions_specifications / …)

Usage
-----
Start the mock server in a separate terminal::

    uvicorn tests.manual.mock_vllm_server:app --port 8000

Then configure the API service to use it::

    cp .env.vllm .env
    # Override the model to the mock identifier
    echo "QUERY_REFINEMENT_LLM_MODEL=mock-model" >> .env
    # Start the API (local dev or docker)
    poetry run uvicorn query_refinement_module.api.main:app --reload --port 8001

Run a smoke call::

    INTEGRATION_API_KEY=<key> curl -X POST http://localhost:8001/api/v1/refinement/start \\
      -H 'Content-Type: application/json' \\
      -H 'X-API-Key: <key>' \\
      -d '{"original_query":"effects of aspirin in older adults","framework_name":"pico_advanced","source":"api_integration"}'

What to look for
----------------
- The mock server console prints every incoming request and whether
  ``guided_json`` was present.
- The API service should complete the full refinement session, with each
  dimension cycling through until ``complete: true`` is returned.
- After several turns the synthesis step returns a ``QueryRefinementResponse``
  and the session ends with a refined statement.

To simulate a multi-turn conversation the mock returns ``complete: false`` for
the first two calls per connection (tracked in ``_call_counter``) and
``complete: true`` thereafter, so the session progresses naturally.
"""

import json
import time
import uuid
from collections import defaultdict

from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse

app = FastAPI(title="Mock vLLM server")

# Per-session call counter so we can simulate multi-turn behaviour.
# Key: first 8 chars of client host; value: call count.
_call_counter: dict[str, int] = defaultdict(int)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_completion(content: str, model: str = "mock-model") -> dict:
    return {
        "id": f"chatcmpl-{uuid.uuid4().hex[:8]}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": model,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": content},
                "finish_reason": "stop",
            }
        ],
        "usage": {
            "prompt_tokens": 120,
            "completion_tokens": 60,
            "total_tokens": 180,
        },
    }


def _response_for_schema(schema: dict, call_index: int) -> str:
    """Return a minimal valid JSON string for the given JSON Schema.

    Uses the schema ``properties`` keys to identify which Pydantic model is
    expected, then returns appropriate fixture data.
    """
    props = schema.get("properties", {})

    # DimensionEvaluationResponse: complete / current / question
    if "complete" in props and "current" in props and "question" in props:
        # First two calls per session are incomplete so the dialogue advances.
        is_complete = call_index >= 2
        return json.dumps(
            {
                "complete": is_complete,
                "current": "adults aged 18-65 with cardiovascular disease",
                "question": (
                    ""
                    if is_complete
                    else "Which geographic setting are you focusing on — UK, US, or global?"
                ),
            }
        )

    # QueryRefinementResponse: has synthesized_statement (by_alias) or integrated_statement
    if "synthesized_statement" in props or "integrated_statement" in props:
        key = "synthesized_statement" if "synthesized_statement" in props else "integrated_statement"
        return json.dumps(
            {
                key: (
                    "A cross-sectional study examining the association between "
                    "aspirin use and cardiovascular outcomes in adults aged 18-65 "
                    "with pre-existing cardiovascular disease in UK primary care."
                ),
                "dimensions_specifications": {
                    "population": "adults aged 18-65 with cardiovascular disease",
                    "intervention": "low-dose aspirin (75 mg daily)",
                    "comparator": "no aspirin / placebo",
                    "outcome": "major adverse cardiovascular events (MACE) at 12 months",
                },
                "search_optimized": (
                    "aspirin cardiovascular outcomes adults cardiovascular disease UK"
                ),
                "search_filters": {"study_design": "cross-sectional", "date_range": "2010-2024"},
                "terminology": ["aspirin", "cardiovascular disease", "MACE", "primary prevention"],
            }
        )

    # Generic fallback: fill every property with a placeholder string.
    fallback = {k: "mock value" for k in props}
    return json.dumps(fallback)


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.get("/v1/models")
async def list_models():
    return {
        "object": "list",
        "data": [
            {
                "id": "mock-model",
                "object": "model",
                "created": int(time.time()),
                "owned_by": "mock",
            }
        ],
    }


@app.post("/v1/chat/completions")
async def chat_completions(request: Request):
    body = await request.json()
    model = body.get("model", "mock-model")
    guided_json = body.get("guided_json")

    # Track call count per client IP for multi-turn simulation.
    client_key = (request.client.host if request.client else "unknown")[:16]
    call_index = _call_counter[client_key]
    _call_counter[client_key] += 1

    if guided_json is not None:
        print(
            f"[mock-vllm] guided_json present | client={client_key} "
            f"call_index={call_index} | schema keys: "
            f"{list((guided_json if isinstance(guided_json, dict) else {}).get('properties', {}).keys())}"
        )
        try:
            schema = guided_json if isinstance(guided_json, dict) else json.loads(guided_json)
            content = _response_for_schema(schema, call_index)
        except Exception as exc:
            raise HTTPException(status_code=422, detail=f"Could not parse guided_json: {exc}")
    else:
        print(f"[mock-vllm] NO guided_json | client={client_key} call_index={call_index}")
        content = (
            "I need more information about your research question. "
            "Could you describe the target population?"
        )

    return JSONResponse(_make_completion(content, model))


@app.delete("/v1/reset-counter")
async def reset_counter():
    """Test helper: reset the per-client call counter."""
    _call_counter.clear()
    return {"status": "reset"}
