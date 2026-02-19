# Deployment Checklist

Use this as the production checklist for VM-based microservice evaluation and external integrations.
For full detail, see `docs/DEPLOYMENT.md`.

## 1) Pre-Deployment

- [ ] Install Docker Engine + Docker Compose plugin on the VM
- [ ] Copy `.env.prod` to `.env` and replace placeholder values
- [ ] Set required secrets: `SECRET_KEY`, `QUERY_REFINEMENT_LLM_API_KEY`
- [ ] If using external API integrations without user JWTs, set `INTEGRATION_API_KEY`
- [ ] Optional for integration identity naming: set `INTEGRATION_SERVICE_USERNAME`
- [ ] Set database connectivity values: `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB`
- [ ] Set browser connectivity value: `ALLOWED_ORIGINS`
- [ ] Optional tooling compatibility: set `DATABASE_URL` to match compose DB settings
- [ ] Keep `ALLOW_REGISTRATION=false` in production unless self-signup is explicitly required
- [ ] Set workflow mode with `ENFORCE_WORKFLOW_LIMIT`:
	- [ ] `true` for one-workflow-per-user evaluation mode
	- [ ] `false` for unlimited non-superuser workflows
- [ ] Ensure host paths exist and are writable: `./logs`, `./logs/nginx`
- [ ] If host uses `5432`/`6379`, override `POSTGRES_PORT`/`REDIS_PORT` in `.env` (example: `5433`/`6380`)
- [ ] Verify required inbound ports:
	- [ ] `80` (HTTP via nginx)
	- [ ] `443` (HTTPS via nginx, if certificates are configured)
	- [ ] `8000` (direct API access, optional but enabled by default in compose)

## 2) Deploy (Canonical Path)

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build
```

- [ ] Stack is up: `docker compose -f docker-compose.yml -f docker-compose.prod.yml ps`
- [ ] Service health is healthy for `postgres`, `redis`, `api`, `nginx`

## 3) Verify Runtime

- [ ] Nginx liveness: `curl -f http://localhost/health`
- [ ] API readiness (direct API port): `curl -f http://localhost:8000/ready`
- [ ] Auth endpoint is reachable: `curl -i -X POST http://localhost/api/v1/auth/login`
- [ ] Registration policy is enforced (expected `403` when disabled):

```bash
curl -i -X POST http://localhost/api/v1/auth/register \
	-H 'Content-Type: application/json' \
	-d '{"username":"testuser","password":"ValidPass123!"}'
```

- [ ] Frontend login flow works end-to-end through nginx (`http://<vm-host>`)

## 4) Integration Smoke Checks

- [ ] Start → answer → synthesize succeeds via `/api/v1/refinement/*`
- [ ] External integration path validated with `X-API-Key` and `source="api_integration"`
- [ ] Partial answer carry-forward works with `/done` (run `python scripts/replay_e2e_check.py` and confirm `PASS`)
- [ ] Forward-to-QA succeeds using `/api/v1/refinement/queries/{query_id}/forward-to-qa`
- [ ] Optional webhooks trigger for expected events (`/api/v1/webhooks`)

## 5) Post-Deployment Operations

- [ ] Tail API logs: `docker compose -f docker-compose.yml -f docker-compose.prod.yml logs -f api`
- [ ] Tail nginx logs: `docker compose -f docker-compose.yml -f docker-compose.prod.yml logs -f nginx`
- [ ] Confirm DB migrations were applied during API startup (`alembic upgrade head` in container logs)
- [ ] Snapshot/backup policy is in place for Postgres and Redis volumes

## 6) Rollback (Fast Path)

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml down
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d
```

## 7) Alternative Topology (Reference Only)

`docker-compose.fullstack.yml` uses different service names and routing assumptions (`backend` instead of `api`).
Use it only when you intentionally deploy that topology; do not mix its commands with the canonical base+prod path above.
