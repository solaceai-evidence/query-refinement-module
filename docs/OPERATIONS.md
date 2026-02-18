# Operations Guide

This guide covers routine tasks and checks.

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
curl http://localhost/ready
```

Integration auth quick check:

```bash
curl -i -H 'X-API-Key: <integration-api-key>' http://localhost:8000/api/v1/refinement/frameworks
curl -i -H 'X-API-Key: wrong-key' http://localhost:8000/api/v1/refinement/frameworks
```

Expected:

- valid key => `200`
- wrong key => `401`

End-to-end integration smoke (minimal):

```bash
curl -X POST http://localhost:8000/api/v1/refinement/start \
  -H 'Content-Type: application/json' \
  -H 'X-API-Key: <integration-api-key>' \
  -d '{"original_query":"effects of aspirin in older adults","framework_name":"pico_advanced","source":"api_integration"}'
```

## Backups

Use your database provider backups or run:

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml exec postgres \
  pg_dump -U postgres query_refinement > backup.sql
```

## Rollback

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml down
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d
```
