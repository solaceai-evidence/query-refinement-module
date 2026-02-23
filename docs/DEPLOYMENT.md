# Deployment Guide

This guide covers local development and production deployment for the Query Refinement Module, with a focus on VM-based microservice evaluation.

## Canonical Production Topology

Use this deployment path for production and external integrations:

- `docker-compose.yml` (base services): `postgres`, `redis`, `api`
- `docker-compose.prod.yml` (production overrides): adds `frontend`, `nginx`

Routing model:

- Client traffic enters via `nginx` on ports `80/443`
- API traffic is proxied to `api:8000` under `/api/*`
- Frontend traffic is proxied from `/` to the frontend container
- Direct API port `8000` is also published by default for diagnostics

`docker-compose.fullstack.yml` is an alternative topology (`backend` naming, different proxy assumptions). Use it only intentionally and do not mix with commands in this guide.

## Prerequisites

- Docker Engine + Docker Compose plugin
- VM with persistent disk for database/cache volumes
- Network access to your LLM provider
- Optional for local dev: Python 3.12+, Poetry, Node.js 20+

## Environment Configuration

1. Copy production template:

```bash
cp .env.prod .env
```

2. Set required values in `.env`:

- `SECRET_KEY`
- `POSTGRES_USER`
- `POSTGRES_PASSWORD`
- `POSTGRES_DB`
- `ALLOWED_ORIGINS`
- `QUERY_REFINEMENT_LLM_API_KEY`

Notes:

- Canonical compose derives API database connectivity from `POSTGRES_*`.
- Do not set a separate `DATABASE_URL` in canonical compose unless you intentionally override derived settings.

If external systems call refinement APIs without user JWT login, also set:

- `INTEGRATION_API_KEY`
- `INTEGRATION_SERVICE_USERNAME` (optional; default is `api_integration_service`)

Important: if you add/change these values, restart the API process/container. If not restarted, integration requests may return `401 Not authenticated` even though `.env` was updated.

3. Strongly recommended production settings:

- `ALLOW_REGISTRATION=false`
- `LOG_FORMAT=json`
- `ENVIRONMENT=production`

4. Workflow limit mode:

- `ENFORCE_WORKFLOW_LIMIT=true` limits non-superusers to one completed workflow
- `ENFORCE_WORKFLOW_LIMIT=false` allows non-superusers to run unlimited workflows

Recommended values by operating mode:

- Controlled evaluation mode: `ENFORCE_WORKFLOW_LIMIT=true`
- Open usage mode: `ENFORCE_WORKFLOW_LIMIT=false`

5. Optional throughput tuning:

- `LLM_RATE_LIMIT_RPM`
- `LLM_RATE_LIMIT_PER_USER_RPM`
- `LLM_MAX_CONCURRENT`
- `LLM_MAX_CONCURRENT_PER_USER`
- `WORKERS`

## VM Microservice Deployment Runbook

### Step 1: Host preflight

- Ensure ports `80` and `443` are allowed inbound
- Decide whether port `8000` should be externally reachable; restrict at firewall if not needed
- Create writable directories: `./logs`, `./logs/nginx`
- If host services already use `5432`/`6379`, set `POSTGRES_PORT`/`REDIS_PORT` in `.env` (for example `5433`/`6380`)

Optional preflight validator:

```bash
bash scripts/validate_deployment.sh
```

### Step 2: Start stack

Choose one deployment mode:

#### Mode A: HTTP (API-only, no nginx)

```bash
docker compose -f docker-compose.yml up -d --build
```

Use this for internal testing or local-only access on port `8000`.

#### Mode B: HTTPS (nginx + TLS, no public domain required)

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build
```

Use this when you want TLS termination at nginx but are not exposing a public domain yet (for example, direct IP testing with a self-signed certificate).

#### Mode C: HTTPS + Domain (recommended for evaluators/integrations)

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build
```

Use this with DNS + valid certificates (for example, `query-refinement-assistant.cloud`).

### Step 3: Verify services and health

Run checks for the mode you started:

#### Mode A: HTTP (API-only)

```bash
docker compose -f docker-compose.yml ps
curl -f http://localhost:8000/ready
curl -f http://localhost:8000/health
```

#### Mode B: HTTPS (no public domain)

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml ps
curl -I http://localhost/health
curl -f http://localhost/nginx-health
curl -k -f https://localhost/health
curl -f http://localhost:8000/ready
```

#### Mode C: HTTPS + Domain

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml ps
curl -I http://query-refinement-assistant.cloud/health
curl -f https://query-refinement-assistant.cloud/health
curl -f http://localhost/nginx-health
curl -f http://localhost:8000/ready
```

Interpretation:

- HTTP mode uses API endpoints directly on `:8000`
- In HTTPS modes, `http://.../health` should return `301` redirect to HTTPS
- `/nginx-health` confirms local nginx container liveness (used by container healthcheck in prod compose)
- `/ready` confirms API dependency readiness (DB/Redis/etc.)

### Step 4: Functional smoke checks

Use the appropriate base URL:

- Mode A (HTTP): `http://localhost:8000`
- Mode B (HTTPS, local test): `https://localhost`
- Mode C (HTTPS + domain): `https://query-refinement-assistant.cloud`

Examples:

```bash
curl -i -X POST <base-url>/api/v1/auth/login
curl -i -X POST <base-url>/api/v1/refinement/start \
	-H 'Content-Type: application/json' \
	-H 'Authorization: Bearer <token>' \
	-d '{"original_query":"effects of aspirin","framework_name":"pico_advanced"}'

# Service-to-service integration (no end-user JWT)
curl -i -X POST <base-url>/api/v1/refinement/start \
	-H 'Content-Type: application/json' \
	-H 'X-API-Key: <integration-api-key>' \
	-d '{"original_query":"effects of aspirin","framework_name":"pico_advanced","source":"api_integration"}'
```

Notes:

- For Mode B, add `-k` to curl commands if using self-signed certs.
- For Mode C, replace `<base-url>` with `https://query-refinement-assistant.cloud`.

### Step 5: Observe runtime

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml logs -f api
docker compose -f docker-compose.yml -f docker-compose.prod.yml logs -f nginx
```

## External Integration Readiness Checklist

- `/api/v1` routes are reachable from integrating systems
- CORS origins in `ALLOWED_ORIGINS` include all browser-based callers
- Forwarding target for `/forward-to-qa` is reachable from the API container
- Timeout expectations are aligned (`timeout_seconds` allowed range: `5..120`)
- Webhook endpoints are reachable from API container egress (if enabled)

## Local Development

### API

```bash
poetry install
poetry run alembic upgrade head
poetry run uvicorn query_refinement_module.api.main:app --reload
```

API default: `http://localhost:8000`

### Frontend

```bash
cd frontend
npm install
npm run dev
```

Frontend default: `http://localhost:5173`

## Migrations

Migrations run automatically in the API container startup command (`python3 -m alembic upgrade head`).
For manual execution:

```bash
poetry run alembic upgrade head
```

## Rollback and Recovery

Fast rollback to last built images:

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml down
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d
```

Recommended operational safeguards:

- Keep regular Postgres backups of `postgres_data`
- Keep Redis persistence enabled (already configured with AOF)
- Store `.env` securely and version only templates, not secrets
