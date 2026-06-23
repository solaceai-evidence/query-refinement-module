# Deployment Guide

This guide is written for someone who needs to put the application on a server and make it available to users. It starts with the simplest production setup and explains the settings in plain language.

## Before You Start

For a normal production deployment, you will need:

- Docker Engine and the Docker Compose plugin on the server
- A copy of the production environment file (`.env.prod` for Anthropic Claude, or `.env.prod.selfhosted` for self-hosted inference)
- Values for the database, AI provider, and website addresses
- A writable location for logs

## Quick Production Setup

1. Copy the production environment file that matches your LLM backend:

```bash
cp .env.prod .env                  # Anthropic Claude (recommended)
# or
cp .env.prod.selfhosted .env       # Self-hosted or local inference
```

2. Edit `.env` and set these required values:

- `SECRET_KEY` - protects login sessions. Must be at least 32 characters. Generate with: `python -c "import secrets; print(secrets.token_urlsafe(32))"`
- `LLM_API_KEY` - required for cloud providers (Anthropic, OpenAI); leave blank for Ollama or vLLM
- `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB` - database login details
- `ALLOWED_ORIGINS` - the browser addresses allowed to use the app

3. If users should be able to create their own accounts, set `ALLOW_REGISTRATION=true`. Otherwise leave it at `false`.

4. If outside systems will call the API directly, set `INTEGRATION_API_KEY` and, optionally, `INTEGRATION_SERVICE_USERNAME`.

5. Start the production stack:

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build
```

6. Open the site in a browser and check that the homepage, login page, and API docs load correctly.

## Pre-deployment checklist

Before starting, verify the following:

- Docker Engine and Docker Compose plugin are installed on the server
- The correct template has been copied to `.env` (`.env.claude_api`, `.env.cloud`, `.env.local`, `.env.selfhosted`, `.env.prod`, or `.env.prod.selfhosted`)
- `SECRET_KEY` is set, is at least 32 characters long, and is not one of the known placeholder values (the API will refuse to start in production mode if this check fails)
- `LLM_API_KEY` is set **if using a cloud provider** (Anthropic, OpenAI); leave blank for Ollama or vLLM
- `LLM_API_BASE` is set **if needed** for vLLM or for an Ollama server that is not using the default `http://localhost:11434`
- `POSTGRES_USER`, `POSTGRES_PASSWORD`, and `POSTGRES_DB` are set
- `ALLOWED_ORIGINS` includes every browser address that should be allowed to use the app
- `ALLOW_REGISTRATION=false` unless self-signup is needed
- `ENFORCE_WORKFLOW_LIMIT` is set to the intended operating mode
- `INTEGRATION_API_KEY` is set if other systems will call the API
- Host paths exist and are writable: `./logs`, `./logs/nginx`
- If port `5432` or `6379` is already in use, override with `POSTGRES_PORT` / `REDIS_PORT` in `.env`
- Inbound ports `80` and `443` are open; port `8001` is optional for direct API access

## What Runs in Production

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

## LLM Provider Configuration

The API service connects to an LLM provider via LiteLLM. Six pre-filled environment templates are provided:

| Template | Provider | Environment | API key required |
| -------- | -------- | ------------ | ---------------- |
| `.env.claude_api` | Anthropic Claude Sonnet 4.6 | Development (cloud) | yes |
| `.env.cloud` | Other cloud providers (OpenAI, etc.) | Development (cloud) | yes |
| `.env.local` | Ollama — local models | Development (local) | no |
| `.env.selfhosted` | vLLM or self-hosted inference | Development / Production | no |
| `.env.prod` | Anthropic Claude Sonnet 4.6 | Production (cloud) | yes |
| `.env.prod.selfhosted` | Self-hosted or local inference | Production | no |

### Switching to OpenAI or other cloud providers

1. Generate or retrieve an API key from your cloud provider.

2. Copy the template and configure:

```bash
cp .env.cloud .env
```

Key cloud provider settings:

| Variable                | Value           | Notes                                                                          |
| ----------------------- | --------------- | ------------------------------------------------------------------------------ |
| `LLM_API_KEY`           | required        | API key for your cloud provider (Anthropic, OpenAI, etc.)                      |
| `LLM_MODEL`             | provider/model  | Model identifier (e.g. `openai/gpt-4o`, `anthropic/claude-sonnet-4-6`)        |
| `LLM_API_BASE`          | *(leave blank)* | Leave blank for official cloud endpoints; set only if using a custom endpoint  |
| `LLM_MAX_OUTPUT_TOKENS` | `4096`          | Default per-call output ceiling; does not change the model context window      |
| `LLM_CONTEXT_WINDOW`    | unsupported     | Cloud providers manage context window; do not set this                         |

### Switching to Ollama (local models)

1. Install and start Ollama: https://ollama.com

2. Pull the model you want to use:

```bash
# Recommended local setup
ollama pull qwen2.5:72b

# Verify: ollama list
```

3. Copy the template and configure:

```bash
cp .env.local .env
```

Key Ollama-specific settings:

| Variable                    | Value           | Notes                                           |
| --------------------------- | --------------- | ----------------------------------------------- |
| `LLM_API_BASE`              | auto            | Defaults internally to `http://localhost:11434` |
| `LLM_API_KEY`               | *(leave blank)* | Not required for local Ollama                   |
| `LLM_COMPLETION_KWARGS`     | auto            | Defaults internally to `{"num_ctx": 16384}`     |
| `LLM_ENABLE_PROMPT_CACHING` | auto            | Defaults internally to `false` for Ollama       |

### Switching to vLLM or self-hosted inference

1. Start your self-hosted inference server (vLLM, TGI, etc.):

```bash
# Example vLLM launch
./start_vllm.sh meta-llama/Llama-3.1-8B-Instruct
# Verify: curl http://localhost:8000/v1/models
```

2. Copy the template and configure:

```bash
cp .env.selfhosted .env
# Set LLM_API_BASE to match your server address
# Set LLM_MODEL to match the loaded model
```

Key self-hosted settings:

| Variable                    | Value                   | Notes                                |
| --------------------------- | ----------------------- | ------------------------------------ |
| `LLM_API_BASE`              | `http://<host>:8000/v1` | Point this at your inference server  |
| `LLM_MODEL`                 | The loaded model name   | Must match the model on your server  |
| `LLM_API_KEY`               | `EMPTY`                 | Placeholder for local servers        |
| `LLM_CONSTRAINED_DECODING`  | `true` (vLLM only)      | Enforces JSON schema at token level  |

> **Warning:** `LLM_CONSTRAINED_DECODING=true` only works with vLLM.
> Set it to `false` for other self-hosted backends.

---

## Environment Configuration

1. Copy the production template if you have not already done so:

```bash
cp .env.prod .env              # Anthropic Claude (recommended)
# or
cp .env.prod.selfhosted .env   # Self-hosted or local inference
```

2. Set required values in `.env`:

- `SECRET_KEY`
- `POSTGRES_USER`
- `POSTGRES_PASSWORD`
- `POSTGRES_DB`
- `ALLOWED_ORIGINS`
- `LLM_API_KEY` — required for cloud providers (Anthropic, OpenAI); leave blank for Ollama or vLLM
- `LLM_API_BASE` — required for vLLM and optional for Ollama when not using the default `http://localhost:11434`; omit for cloud

Context-window note:

- `LLM_CONTEXT_WINDOW` only applies to backends that expose a client-side context-size parameter. Today that means Ollama. It does not change the provider-managed context window for Anthropic or OpenAI.

Notes:

- Canonical compose derives API database connectivity from `POSTGRES_*`.
- Do not set a separate `DATABASE_URL` in canonical compose unless you intentionally override derived settings.
- `API_RATE_LIMIT_RPM` and `API_RATE_LIMIT_PER_USER_RPM` apply to HTTP ingress throttling only.
- `LLM_PROVIDER_RATE_LIMIT_RPM`, `LLM_PROVIDER_RATE_LIMIT_TPM`, and `LLM_PROVIDER_MAX_CONCURRENT` apply to outbound provider throttling only.
- Legacy shared names are still accepted for compatibility, but new deployments should use the explicit API/provider names.

If external systems call refinement APIs without user JWT login, also set:

- `INTEGRATION_API_KEY`
- `INTEGRATION_SERVICE_USERNAME` (optional; default is `api_integration_service`)

Important: if you change these values, restart the API process or container. If not restarted, integration requests may return `401 Not authenticated` even though `.env` was updated.

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

- Leave the template rate-limit values alone unless your provider tier or expected load differs.
- `API_RATE_LIMIT_RPM`
- `API_RATE_LIMIT_PER_USER_RPM`
- `LLM_PROVIDER_RATE_LIMIT_RPM`
- `LLM_PROVIDER_MAX_CONCURRENT`
- `WORKERS`

Ownership model:

- `query_refinement_module/api/config.py` owns the HTTP/API layer.
- `query_refinement_module/settings.py` owns outbound LLM runtime configuration.

## Deployment Runbook

### Step 1: Check the server

- Ensure ports `80` and `443` are allowed inbound
- Decide whether port `8001` should be externally reachable; restrict it at the firewall if not needed
- Create writable directories: `./logs`, `./logs/nginx`
- If host services already use `5432`/`6379`, set `POSTGRES_PORT`/`REDIS_PORT` in `.env` (for example `5433`/`6380`)

Optional preflight validator:

```bash
bash scripts/validate_deployment.sh
```

### Step 2: Start the stack

Choose one deployment mode:

#### Mode A: HTTP (API only, no nginx)

```bash
docker compose -f docker-compose.yml up -d --build
```

Use this for internal testing or local-only access on port `8001`.

#### Mode B: HTTPS (nginx + TLS, no public domain required)

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build
```

Use this when you want TLS termination at nginx but are not exposing a public domain yet. This is useful for direct IP testing with a self-signed certificate.

#### Mode C: HTTPS + domain (recommended for evaluators and integrations)

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build
```

Use this with DNS and valid certificates (for example, `query-refinement-assistant.cloud`).

### Step 3: Verify the services

Run checks for the mode you started:

#### Mode A: HTTP (API only)

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

#### Mode C: HTTPS + domain

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml ps
curl -I http://query-refinement-assistant.cloud/health
curl -f https://query-refinement-assistant.cloud/health
curl -f http://localhost/nginx-health
curl -f http://localhost:8001/ready
```

What the checks mean:

- HTTP mode uses API endpoints directly on `:8001`
- In HTTPS modes, `http://.../health` should return a redirect to HTTPS
- `/nginx-health` confirms the nginx container is alive
- `/ready` confirms API dependency readiness such as the database and Redis

### Step 4: Run a quick smoke test

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

### Step 5: Watch the logs

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml logs -f api
docker compose -f docker-compose.yml -f docker-compose.prod.yml logs -f nginx
```

## External Integration Readiness Checklist

- `/api/v1` routes are reachable from integrating systems
- CORS origins in `ALLOWED_ORIGINS` include all browser-based callers
- Forwarding target for `/forward-to-qa` is reachable from the API container
- Timeout expectations are aligned (`timeout_seconds` allowed range: `5..120`)

## Local Development

### API

```bash
poetry install
poetry run alembic upgrade head
poetry run uvicorn query_refinement_module.api.main:app --reload
```

Or use the startup script (checks env, runs migrations, starts Gunicorn):

```bash
./start_api.sh
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
