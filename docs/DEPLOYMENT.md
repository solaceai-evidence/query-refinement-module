# Deployment Guide

This guide covers development and production deployment for the Query Refinement Module.

## Prerequisites

- Docker and Docker Compose (recommended for production)
- Python 3.12+ and Poetry (for local development)
- Node.js 20+ (frontend development)
- PostgreSQL 12+ and Redis 6+ (production services)

## Environment Setup

1. Copy the production template:

```bash
cp .env.prod .env
```

2. Set required values in `.env`:

- `SECRET_KEY`
- `DATABASE_URL`
- `ALLOWED_ORIGINS`
- `QUERY_REFINEMENT_LLM_API_KEY`

3. Optional tuning:

- `LLM_RATE_LIMIT_RPM`
- `LLM_RATE_LIMIT_PER_USER_RPM`
- `LLM_MAX_CONCURRENT`
- `LLM_MAX_CONCURRENT_PER_USER`

## Local Development (API)

```bash
poetry install
poetry run alembic upgrade head
poetry run uvicorn query_refinement_module.api.main:app --reload
```

API: http://localhost:8000

## Local Development (Frontend)

```bash
cd frontend
npm install
npm run dev
```

Frontend: http://localhost:5173

## Production Deployment (Docker Compose)

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d
```

Check status and logs:

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml ps
docker compose -f docker-compose.yml -f docker-compose.prod.yml logs -f api
```

## VM Quick Start

1. Install Docker and the Compose plugin.
2. Clone the repo to the VM.
3. Copy `.env.prod` to `.env` and fill required values.
4. Start the stack with the compose command above.
5. Verify:

```bash
curl http://localhost/health
curl http://localhost/api/v1/auth/login
```

## Migrations

```bash
poetry run alembic upgrade head
```

## Health Checks

- `/health` for liveness
- `/ready` for dependency checks

## Rollback

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml down
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d
```
