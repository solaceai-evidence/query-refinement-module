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
