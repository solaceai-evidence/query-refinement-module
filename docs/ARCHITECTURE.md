# Architecture Guide

This document explains the current backend layering for the refinement system and where external contributors should extend behavior.

## Design goals

The refinement backend is organized to keep transport concerns separate from workflow orchestration and to make it obvious where new behavior belongs.

The target layering is:

```text
HTTP routes
  -> transport schemas
  -> application facade
  -> focused workflow services
  -> core/session logic + persistence + infrastructure
```

## Refinement backend map

### 1. Route adapters

File: `query_refinement_module/api/routes/refinement.py`

Responsibilities:

- Define FastAPI endpoints
- Bind dependencies such as database sessions, settings, and session manager
- Convert service payloads into transport response models
- Preserve a small number of compatibility helpers used directly by tests

What should not live here:

- Multi-step workflow orchestration
- Session reconstruction logic
- Agent pipeline decisions
- Business rules for command handling or synthesis

### 2. Transport schemas

File: `query_refinement_module/api/refinement_schemas.py`

Responsibilities:

- Request and response models for refinement endpoints
- Response compatibility shims such as `integrated_statement`

Extend here when:

- An endpoint contract changes
- A new response payload requires serialization/validation rules

### 3. Application facade

File: `query_refinement_module/application/refinement_api_service.py`

Responsibilities:

- Provide the stable entry point used by the route layer
- Delegate to narrower collaborators without exposing that split to callers

This file should remain thin. If it starts accumulating orchestration logic again, move that logic into one of the focused services below.

### 4. Focused workflow services

#### Lifecycle workflows

File: `query_refinement_module/application/refinement_lifecycle_service.py`

Owns:

- `start_workflow`
- `get_status_payload`
- `resume_workflow`
- `submit_answer`
- Command handling and command response shaping
- Synthesis execution and persistence

Add logic here when the change affects the refinement dialogue state machine, synthesis flow, or command semantics.

#### Agent workflows

File: `query_refinement_module/application/refinement_agent_service.py`

Owns:

- `normalize_workflow`
- `represent_workflow`
- `construct_workflow`
- `expand_workflow`

Add logic here when introducing or changing a statement-to-artifact transform in the A/B/C/D pipeline.

#### Utility workflows

File: `query_refinement_module/application/refinement_utility_service.py`

Owns:

- QA forwarding
- Command history retrieval
- Message inspection
- Session abandonment
- Query progress payloads

Add logic here when the endpoint is refinement-adjacent but not part of the main dialogue/synthesis loop.

#### Shared support

File: `query_refinement_module/application/refinement_service_support.py`

Owns:

- Shared dependency bundle
- Query ownership guards
- Framework resolution
- Session initialization
- Session reconstruction from database state

Add logic here only when it is genuinely cross-cutting and used by multiple workflow services.

## Core workflow helpers

File: `query_refinement_module/application/refinement_workflow.py`

This module contains shared helper functions for rebuilding or advancing session state, including next-prompt generation and prompt persistence. Use it for small reusable functions, not for owning endpoint workflows.

## Where to change what

### Add a new refinement endpoint

1. Add request/response models in `query_refinement_module/api/refinement_schemas.py` if needed.
2. Add a route in `query_refinement_module/api/routes/refinement.py`.
3. Add a façade method in `query_refinement_module/application/refinement_api_service.py` only if the route needs a new entry point.
4. Implement the behavior in the appropriate focused service.

### Change the question/answer loop

Start in `query_refinement_module/application/refinement_lifecycle_service.py`.

Typical examples:

- New command semantics
- New synthesis readiness rule
- New persistence side effect after answer submission
- New reconstruction behavior after cache miss

### Change Agent A/B/C/D behavior

Start in `query_refinement_module/application/refinement_agent_service.py` or in the underlying manager/core layer, depending on whether the change is orchestration or model logic.

### Change prompt generation or prompt persistence

Start in `query_refinement_module/application/refinement_workflow.py`.

### Change session reconstruction

Start in `query_refinement_module/application/refinement_service_support.py` and validate cache-miss flows.

## Testing guidance

Use focused validation first, then widen:

- Refinement surface: `poetry run pytest tests/unit/test_refinement_api_service.py tests/api/test_refinement_endpoints.py tests/api/test_frontend_contracts.py tests/api/test_refinement_reconstruction.py tests/api/test_command_history.py tests/api/test_abandon_session.py tests/api/test_progress.py tests/unit/test_refinement_synthesis_readiness.py tests/unit/test_generated_question_persistence.py tests/unit/test_ssrf_guard.py -q`
- Full suite: `poetry run pytest -q`

Preserve compatibility seams when tests patch route-local or facade-local helpers. Several tests intentionally patch those seams instead of the deeper collaborators.

## Current extension rule of thumb

If a change begins with “when this endpoint is called, the system should...”, it belongs in the application layer.

If it begins with “when this prompt is generated...” or “when this agent transforms input...”, it likely belongs in prompt/schema or manager/core logic instead.