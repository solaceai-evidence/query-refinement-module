# Deployment Guide

This guide covers local development and production deployment for the Query Refinement Module.

## Pre-deployment checklist

Before starting, verify the following:

- Docker Engine and Docker Compose plugin are installed on the VM
- Copy `.env.prod` to `.env` and fill in all placeholder values
- Required secrets are set: `SECRET_KEY`, `QUERY_REFINEMENT_LLM_API_KEY`
- Database values are set: `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB`
- `ALLOWED_ORIGINS` includes all browser-facing hostnames
- `ALLOW_REGISTRATION=false` unless self-signup is explicitly required
- `ENFORCE_WORKFLOW_LIMIT` is set: `true` for one-workflow-per-user evaluation; `false` for unlimited
- For server-to-server integrations: `INTEGRATION_API_KEY` is set
- Host paths exist and are writable: `./logs`, `./logs/nginx`
- If port `5432` or `6379` is already in use on the host, override with `POSTGRES_PORT` / `REDIS_PORT` in `.env`
- Inbound ports `80` and `443` are open; port `8001` is optional (direct API access)

## Production topology

- `docker-compose.yml` (base services): `postgres`, `redis`, `api`
- `docker-compose.prod.yml` (production overrides): adds `frontend`, `nginx`

Routing model:

- Client traffic enters via `nginx` on ports `80/443`
- API traffic is proxied to `api:8001` under `/api/*`
- Frontend traffic is proxied from `/` to the frontend container
- Direct API port `8001` is also published by default for diagnostics

## Prerequisites

- Docker Engine + Docker Compose plugin
- VM with persistent disk for database/cache volumes
- Network access to your LLM provider
- Optional for local development: Python 3.12+, Poetry, Node.js 20+

## LLM provider configuration

The API service connects to an LLM provider via LiteLLM.  Three pre-filled
environment templates are provided:

| Template      | Provider                                  | `CONSTRAINED_DECODING` |
| ------------- | ----------------------------------------- | ---------------------- |
| `.env.prod`   | Anthropic Claude (cloud, default)         | `false`                |
| `.env.ollama` | Ollama (local CPU/GPU)                    | `false`                |
| `.env.vllm`   | vLLM self-hosted OpenAI-compatible server | `true`                 |

### Switching to vLLM

1. Start a vLLM server (requires GPU and the `vllm` package):

```bash
vllm serve meta-llama/Llama-3.3-70B-Instruct \
  --port 8000 --dtype bfloat16 --max-model-len 16384
# Verify: curl http://localhost:8000/v1/models
```

2. Copy the template and configure:

```bash
cp .env.vllm .env
# Set QUERY_REFINEMENT_LLM_API_BASE to match your vLLM server address
# Set QUERY_REFINEMENT_LLM_MODEL to match the loaded model
```

Key vLLM-specific settings:

| Variable                                    | Required value          | Notes                                               |
| ------------------------------------------- | ----------------------- | --------------------------------------------------- |
| `QUERY_REFINEMENT_LLM_API_BASE`             | `http://<host>:8000/v1` | Must point at the vLLM server                       |
| `QUERY_REFINEMENT_LLM_API_KEY`              | `EMPTY`                 | Conventional placeholder for local servers          |
| `QUERY_REFINEMENT_LLM_CONSTRAINED_DECODING` | `true`                  | Sends `guided_json` schema in every structured call |
| `QUERY_REFINEMENT_ENABLE_PROMPT_CACHING`    | `false`                 | Anthropic-specific feature; disable for vLLM        |

> **Warning:** `QUERY_REFINEMENT_LLM_CONSTRAINED_DECODING=true` must only be
> set when the API base points at a vLLM server.  Setting it for
> Anthropic / OpenAI / Ollama will break structured output for those providers.

### Constrained decoding behaviour

When `CONSTRAINED_DECODING=true`, the provider injects the full Pydantic JSON
Schema as `extra_body={"guided_json": <schema>}` in every structured LLM
call.  vLLM enforces the schema at the token level, guaranteeing
structurally valid output from both the dimension evaluation and synthesis
stages without any post-hoc JSON repair.

---

## Environment configuration

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
- Decide whether port `8001` should be externally reachable; restrict at firewall if not needed
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

Use this for internal testing or local-only access on port `8001`.

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
curl -f http://localhost:8001/ready
curl -f http://localhost:8001/health
```

#### Mode B: HTTPS (no public domain)

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml ps
curl -I http://localhost/health
curl -f http://localhost/nginx-health
curl -k -f https://localhost/health
curl -f http://localhost:8001/ready
```

#### Mode C: HTTPS + Domain

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml ps
curl -I http://query-refinement-assistant.cloud/health
curl -f https://query-refinement-assistant.cloud/health
curl -f http://localhost/nginx-health
curl -f http://localhost:8001/ready
```

Interpretation:

- HTTP mode uses API endpoints directly on `:8001`
- In HTTPS modes, `http://.../health` should return `301` redirect to HTTPS
- `/nginx-health` confirms local nginx container liveness (used by container healthcheck in prod compose)
- `/ready` confirms API dependency readiness (DB/Redis/etc.)

### Step 4: Functional smoke checks

Use the appropriate base URL:

- Mode A (HTTP): `http://localhost:8001`
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

API default: `http://localhost:8001`

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
