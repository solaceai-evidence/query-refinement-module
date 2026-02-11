# Operations Guide

This guide covers routine tasks and checks.

## Migrations

```bash
poetry run alembic upgrade head
poetry run alembic current
poetry run alembic history
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
