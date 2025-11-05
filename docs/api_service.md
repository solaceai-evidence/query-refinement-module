# API Service Overview

This document outlines the suggested service layer for exposing the query refinement workflow as an API.

## Asynchronous First

- The public facade (`QueryRefinementService`) exposes **async methods** so it can be embedded into existing FastAPI/Quart/websocket stacks.
- Internally the service relies on `asyncio.to_thread` to bridge synchronous manager logic and storage backends. This keeps backwards compatibility with the current `QueryRefinementManager` while enabling non-blocking request handling.

## Endpoints / RPCs

| Endpoint | Method | Purpose |
| --- | --- | --- |
| `/sessions` | `POST` | Initialize a new refinement session with the original query and selected framework. |
| `/sessions/{id}/interactions` | `POST` | Submit a user turn. The service detects commands (prefixed with `/`) server-side. |
| `/sessions/{id}` | `GET` | Retrieve the session summary, next prompt, and optional history for dashboards or polling clients. |
| `/sessions/{id}` | `DELETE` | Cancel or purge a session. |

## Request / Response Models

The models live in `query_refinement_module/api_models.py`:

- `SessionCreateRequest` / `SessionCreateResponse`
- `InteractionRequest` / `InteractionResponse`
- `SessionStatusResponse`
- `NextPrompt` for the question payload shown to end users

All payloads keep client responsibilities minimal: the client only sends the raw user message; commands such as `/goto 3` are detected and acted upon server-side via `parse_user_command`.

## Command Handling

- Commands are detected automatically through `is_user_command()`.
- `/steps` output enumerates the step order, so `/goto 2` remains intuitive.
- The service persists the session after each interaction to maintain continuity across stateless API calls.

## Storage Abstraction

`QueryRefinementService` depends on `SessionStorageInterface`, which allows implementers to back sessions with Redis, Postgres, in-memory caches, etc. All storage calls are wrapped in `asyncio.to_thread` to keep the public API awaitable.

## Extensibility

- Additional endpoints (e.g., webhook registration, streaming events) can be layered on top without touching the core manager.
- The service offers a natural hook for tracing providers (`TraceEventEmitter` events already exist within the manager) so request/response cycles can be correlated with LLM calls.
