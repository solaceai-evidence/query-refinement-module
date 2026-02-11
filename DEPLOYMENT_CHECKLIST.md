# Deployment Checklist

Use this as a quick deployment checklist. For details, see docs/DEPLOYMENT.md.

## Pre-Deployment

- [ ] Fill `.env` from `.env.prod` with real values
- [ ] Set `SECRET_KEY` and `QUERY_REFINEMENT_LLM_API_KEY`
- [ ] Set `DATABASE_URL` and `ALLOWED_ORIGINS`
- [ ] Confirm Docker and Docker Compose are installed

## Deploy

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d
```

## Verify

- [ ] `curl http://localhost/health`
- [ ] `curl http://localhost/api/v1/auth/login` returns 401/422
- [ ] Frontend loads and can log in

## Post-Deployment

- [ ] Check logs: `docker compose -f docker-compose.yml -f docker-compose.prod.yml logs -f api`
- [ ] Run migrations if needed: `poetry run alembic upgrade head`
