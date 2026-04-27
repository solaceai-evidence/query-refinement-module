# Operations Guide

This guide covers routine tasks and checks.

## Switching LLM backends

Four env templates cover the supported backends:

| Template      | Provider                 | API key required | Constrained decoding |
| ------------- | ------------------------ | ---------------- | -------------------- |
| `.env`        | Anthropic Claude (dev)   | yes              | off                  |
| `.env.prod`   | Anthropic Claude (cloud) | yes              | off                  |
| `.env.ollama` | Ollama (local)           | no               | off                  |
| `.env.vllm`   | vLLM (self-hosted)       | no               | **on**               |

To switch, copy the relevant template to `.env` and restart the API:

```bash
# Ollama
cp .env.ollama .env
./start_api.sh

# vLLM
cp .env.vllm .env
./start_api.sh

# Anthropic cloud (production)
cp .env.prod .env
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

# Test a basic completion
curl -X POST http://localhost:11434/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -d '{"model": "llama3.3:70b", "messages": [{"role": "user", "content": "ping"}]}'
```

> **Note:** `QUERY_REFINEMENT_LLM_COMPLETION_KWARGS={"num_ctx": 16384}` overrides Ollama's
> default 2 048-token context window, which is too small for this application.
> Increase to `32768` if you observe truncated responses; decrease to `8192` to reduce memory use.

### vLLM server diagnostics

```bash
# Confirm the vLLM server is up and serving the expected model
curl http://localhost:8000/v1/models

# Test a raw structured call with guided_json
curl -X POST http://localhost:8000/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -d '{
    "model": "meta-llama/Llama-3.3-70B-Instruct",
    "messages": [{"role": "user", "content": "Reply with valid JSON only: {\"complete\": true, \"current\": \"test\", \"question\": \"\"}"}],
    "guided_json": {"type": "object", "properties": {"complete": {"type": "boolean"}, "current": {"type": "string"}, "question": {"type": "string"}}, "required": ["complete", "current", "question"]}
  }'
```

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
