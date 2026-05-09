# Operations Guide

This guide covers routine tasks and checks.

## Switching LLM backends

Seven env templates cover the supported backends:

| Template                           | Provider                                 | API key required | Constrained decoding |
| ---------------------------------- | ---------------------------------------- | ---------------- | -------------------- |
| `.env.anthropic-claude-sonnet-4-6` | Anthropic Claude Sonnet 4.6 (dev)        | yes              | off                  |
| `.env.openai-gpt-4o`               | OpenAI GPT-4o (dev)                      | yes              | off                  |
| `.env.prod`                        | Anthropic Claude Sonnet 4.6 (production) | yes              | off                  |
| `.env.prod.openai-gpt-4o`          | OpenAI GPT-4o (production)               | yes              | off                  |
| `.env.prod.ollama-qwen2.5-72b`     | Ollama — Qwen 2.5 72B (production)       | no               | off                  |
| `.env.ollama-qwen2.5-72b`          | Ollama — Qwen 2.5 72B (local)            | no               | off                  |
| `.env.vllm`                        | vLLM — Llama 3.1 8B                      | no               | **on**               |

The rate-limit values inside these templates are prefilled starting points. In normal deployments, leave them alone unless your provider tier or host capacity requires tuning.

Config ownership is split on purpose:
- `query_refinement_module/api/config.py` owns API/web settings and HTTP ingress throttling.
- `query_refinement_module/settings.py` owns outbound LLM runtime settings and provider-side throttling.

`LLM_RATE_LIMIT_RPM` is shared between those layers. `LLM_MAX_CONCURRENT` is outbound-only. `LLM_RATE_LIMIT_PER_USER_RPM` and `LLM_MAX_CONCURRENT_PER_USER` are API fairness controls only.

To switch, copy the relevant template to `.env` and restart the API:

```bash
# Anthropic Claude Sonnet 4.6 (local development)
cp .env.anthropic-claude-sonnet-4-6 .env
./start_api.sh

# OpenAI GPT-4o (local development)
cp .env.openai-gpt-4o .env
./start_api.sh

# Ollama — Qwen 2.5 72B (local)
cp .env.ollama-qwen2.5-72b .env
./start_api.sh

# vLLM — self-hosted (Llama 3.1 8B)
cp .env.vllm .env
./start_vllm.sh
./start_api.sh

# Anthropic cloud (production)
cp .env.prod .env
./start_production.sh

# OpenAI GPT-4o (production)
cp .env.prod.openai-gpt-4o .env
./start_production.sh

# Ollama — Qwen 2.5 72B (production)
cp .env.prod.ollama-qwen2.5-72b .env
./start_production.sh
```

For a running Docker stack, rebuild only the API container:

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build api
```

### Verifying constrained decoding is active

When `QUERY_REFINEMENT_LLM_CONSTRAINED_DECODING=true` the API logs will show
`guided_json` schema injection for every structured call.  Confirm at runtime:

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml logs api | grep guided_json
```

If constrained decoding is active but the vLLM server is unreachable, the
`/ready` endpoint will report unhealthy:

```bash
curl -f http://localhost:8001/ready
```

### Ollama diagnostics

```bash
# Confirm Ollama is running and the model is available
ollama list
curl http://localhost:11434/v1/models

# Test a basic completion (replace model name to match your .env)
curl -X POST http://localhost:11434/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -d '{"model": "qwen2.5:32b", "messages": [{"role": "user", "content": "ping"}]}'
```

> **Note:** The app now defaults Ollama to `QUERY_REFINEMENT_LLM_COMPLETION_KWARGS={"num_ctx": 16384}` to override Ollama's
> default 2 048-token context window, which is too small for this application.
> Synthesis runs 5 sequential and parallel LLM calls per request; each call shares
> the same context budget. Increase to `32768` if you observe truncated responses;
> decrease to `8192` only when memory is severely constrained.

OpenAI and Anthropic do not expose an equivalent client-side context-window knob in this app. For those providers, use `QUERY_REFINEMENT_LLM_MAX_TOKENS` to control output length only.

### vLLM server diagnostics

```bash
# Confirm the vLLM server is up and serving the expected model
curl http://localhost:8000/v1/models

# Test a raw structured call with guided_json
curl -X POST http://localhost:8000/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -d '{
    "model": "meta-llama/Llama-3.1-8B-Instruct",
    "messages": [{"role": "user", "content": "Reply with valid JSON only: {\"complete\": true, \"current\": \"test\", \"question\": \"\"}"}],
    "guided_json": {"type": "object", "properties": {"complete": {"type": "boolean"}, "current": {"type": "string"}, "question": {"type": "string"}}, "required": ["complete", "current", "question"]}
  }'
```

On macOS, keep local vLLM testing on the 8B model; vLLM runs CPU-only there.

---

## Runtime Modes

The service now supports two practical runtime channels:

- GUI evaluation mode (JWT user auth, feedback workflow)
- External integration mode (service-to-service auth via `X-API-Key`)

For external integrations, set:

- `INTEGRATION_API_KEY` (required)
- `INTEGRATION_SERVICE_USERNAME` (optional, defaults to `api_integration_service`)

In integration requests to `/api/v1/refinement/start`, send:

- `source: "api_integration"`

## Migrations

```bash
poetry run alembic upgrade head
poetry run alembic current
poetry run alembic history
```

## Environment and Restart

When changing integration auth settings, restart API processes so new env values are loaded.

Docker:

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build api
```

Local:

```bash
INTEGRATION_API_KEY=<shared-key> ./start_api.sh
```

## Logs

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml logs -f api
```

## Health Checks

```bash
curl http://localhost/health
curl http://localhost:8001/ready
```

Integration auth quick check:

```bash
curl -i -H 'X-API-Key: <integration-api-key>' http://localhost:8001/api/v1/refinement/frameworks
curl -i -H 'X-API-Key: wrong-key' http://localhost:8001/api/v1/refinement/frameworks
```

Expected:

- valid key => `200`
- wrong key => `401`

End-to-end integration smoke (minimal):

```bash
curl -X POST http://localhost:8001/api/v1/refinement/start \
  -H 'Content-Type: application/json' \
  -H 'X-API-Key: <integration-api-key>' \
  -d '{"original_query":"effects of aspirin in older adults","framework_name":"pico_advanced","source":"api_integration"}'
```

## Backups

Create timestamped PostgreSQL backups (custom format, suitable for `pg_restore`):

```bash
mkdir -p backups
ts="$(date +%Y%m%d_%H%M%S)"
docker compose -f docker-compose.yml -f docker-compose.prod.yml exec -T postgres \
  sh -lc 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc' \
  > "backups/postgres_${ts}.dump"
ls -lh "backups/postgres_${ts}.dump"
```

Optional Redis snapshot backup:

```bash
mkdir -p backups
ts="$(date +%Y%m%d_%H%M%S)"
cp data/redis/appendonly.aof "backups/redis_${ts}.aof"
```

## Restore

Restore Postgres from a backup file:

```bash
backup_file="backups/postgres_YYYYMMDD_HHMMSS.dump"
docker compose -f docker-compose.yml -f docker-compose.prod.yml exec -T postgres \
  sh -lc 'dropdb -U "$POSTGRES_USER" --if-exists "$POSTGRES_DB" && createdb -U "$POSTGRES_USER" "$POSTGRES_DB"'
cat "$backup_file" | docker compose -f docker-compose.yml -f docker-compose.prod.yml exec -T postgres \
  sh -lc 'pg_restore -U "$POSTGRES_USER" -d "$POSTGRES_DB" --clean --if-exists --no-owner --no-privileges'
```

After restore:

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml restart api
docker compose -f docker-compose.yml -f docker-compose.prod.yml exec api python -m alembic current
curl -f http://localhost:8001/ready
```

## Rollback

Fast rollback to last local images and volumes:

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml down
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d
```

Rollback code + containers to a known Git commit:

```bash
git checkout <known-good-commit-or-tag>
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build api frontend nginx
docker compose -f docker-compose.yml -f docker-compose.prod.yml ps
```
