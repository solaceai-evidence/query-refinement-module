# Production Deployment Checklist

**System:** Query Refinement Module API v0.3.0  
**Status:** ✅ READY FOR PRODUCTION  
**Date:** February 9, 2026

---

## Pre-Deployment Checklist

### Environment Configuration
- [ ] Set `ENVIRONMENT=production` in .env
- [ ] Generate and set secure `SECRET_KEY` (never use default)
- [ ] Configure `DATABASE_URL` with PostgreSQL connection string
- [ ] Set `ALLOWED_ORIGINS` to production frontend domains
- [ ] Configure `QUERY_REFINEMENT_LLM_API_KEY` with valid API key
- [ ] Set `LOG_FORMAT=json` for structured logging
- [ ] Set `LOG_LEVEL=INFO` (or WARNING for production)
- [ ] Configure `REDIS_URL` for session storage
- [ ] Review rate limiting settings (`LLM_RATE_LIMIT_RPM`)

### Database Setup
- [ ] Run database migrations: `poetry run alembic upgrade head`
- [ ] Create superuser account: `poetry run python scripts/make_superuser.py admin`
- [ ] Configure database backups (automated, daily minimum)
- [ ] Test database connection and query performance
- [ ] Verify connection pooling is working (monitor pool utilization)

### Security Hardening
- [ ] Verify .env file is NOT in git repository (check: `git ls-files .env`)
- [ ] Enable HTTPS with valid SSL certificate
- [ ] Configure firewall rules (allow only 80/443, block database ports)
- [ ] Set up WAF (Web Application Firewall) if available
- [ ] Review CORS policy for production domains
- [ ] Enable security headers (HSTS, CSP, X-Frame-Options)
- [ ] Rotate all secrets and API keys from development

### Application Server
- [ ] Use Gunicorn with UvicornWorker (not dev server)
- [ ] Configure worker count (4-8 workers typical)
- [ ] Set worker timeout (120s default)
- [ ] Enable worker auto-restart (`--max-requests 1000`)
- [ ] Configure graceful shutdown handling
- [ ] Test health check endpoint: `curl http://localhost:8000/health`

### Reverse Proxy (Nginx/Caddy)
- [ ] Configure HTTPS termination
- [ ] Set up proxy headers (X-Forwarded-For, X-Real-IP)
- [ ] Enable gzip compression for responses
- [ ] Configure rate limiting at proxy level
- [ ] Set up static file serving for frontend
- [ ] Configure timeouts (client body, headers)
- [ ] Enable access logs and error logs

### Monitoring & Alerting
- [ ] Set up application metrics (Prometheus/CloudWatch)
- [ ] Configure log aggregation (ELK/Splunk/Datadog)
- [ ] Enable error tracking (Sentry/Rollbar)
- [ ] Set up uptime monitoring (Pingdom/UptimeRobot)
- [ ] Configure alerts for:
  - [ ] API error rate > 5%
  - [ ] Response time p95 > 2s
  - [ ] Database connection pool exhaustion
  - [ ] Disk space < 10%
  - [ ] Memory usage > 90%
  - [ ] LLM API errors

### Testing
- [ ] Run full test suite: `poetry run pytest tests/`
- [ ] Load test with expected production traffic
- [ ] Test error scenarios (network failures, database issues)
- [ ] Verify graceful degradation when Redis unavailable
- [ ] Test authentication flows
- [ ] Verify rate limiting works
- [ ] Test database connection pool under load

### Documentation
- [ ] Update API documentation at /docs
- [ ] Create runbook for common operations
- [ ] Document incident response procedures
- [ ] Create database backup/restore procedures
- [ ] Document rollback procedures
- [ ] Update architecture diagrams

### Backup & Recovery
- [ ] Database backups enabled (automated)
- [ ] Test database restore procedure
- [ ] Document recovery time objective (RTO)
- [ ] Document recovery point objective (RPO)
- [ ] Create disaster recovery plan

---

## Deployment Commands

### Option 1: Docker Compose (Recommended)
```bash
# Build and start all services
docker-compose -f docker-compose.prod.yml up -d

# Check logs
docker-compose logs -f api

# Run migrations
docker-compose exec api poetry run alembic upgrade head

# Create superuser
docker-compose exec api poetry run python scripts/make_superuser.py admin
```

### Option 2: Direct Deployment
```bash
# Install dependencies
poetry install --no-dev

# Run migrations
poetry run alembic upgrade head

# Create superuser (optional)
poetry run python scripts/make_superuser.py admin

# Start with Gunicorn
poetry run gunicorn query_refinement_module.api.main:app \
  --workers 4 \
  --worker-class uvicorn.workers.UvicornWorker \
  --bind 0.0.0.0:8000 \
  --timeout 120 \
  --max-requests 1000 \
  --max-requests-jitter 100 \
  --access-logfile - \
  --error-logfile - \
  --log-level info
```

### Option 3: Systemd Service
```bash
# Create service file: /etc/systemd/system/query-refinement.service
sudo systemctl daemon-reload
sudo systemctl enable query-refinement
sudo systemctl start query-refinement
sudo systemctl status query-refinement
```

---

## Post-Deployment Verification

### Health Checks
```bash
# API health
curl https://your-domain.com/health

# Expected: {"status": "healthy", "version": "0.3.0"}
```

### Smoke Tests
```bash
# Test authentication
curl -X POST https://your-domain.com/api/auth/register \
  -H "Content-Type: application/json" \
  -d '{"username":"test","email":"test@example.com","password":"TestPass123!","name":"Test"}'

# Test API documentation
curl https://your-domain.com/docs

# Test CORS headers
curl -I -H "Origin: https://your-frontend.com" https://your-domain.com/api/auth/login
```

### Performance Tests
```bash
# Response time check
time curl https://your-domain.com/health

# Load test (requires Apache Bench)
ab -n 1000 -c 10 https://your-domain.com/health
```

### Monitoring Dashboard
- [ ] API requests per minute
- [ ] Average response time
- [ ] Error rate (4xx, 5xx)
- [ ] Active users/sessions
- [ ] Database connection pool usage
- [ ] Memory usage per worker
- [ ] CPU usage

---

## Rollback Procedures

### If Deployment Fails
```bash
# Docker
docker-compose -f docker-compose.prod.yml down
docker-compose -f docker-compose.prod.yml up -d

# Systemd
sudo systemctl stop query-refinement
# Restore previous version
sudo systemctl start query-refinement

# Database rollback (if needed)
poetry run alembic downgrade -1
```

### Database Rollback
```bash
# Show migration history
poetry run alembic history

# Rollback one migration
poetry run alembic downgrade -1

# Rollback to specific version
poetry run alembic downgrade <revision_id>
```

---

## Maintenance Tasks

### Daily
- [ ] Check error logs for anomalies
- [ ] Monitor API response times
- [ ] Verify database backups completed
- [ ] Check disk space usage

### Weekly
- [ ] Review security alerts
- [ ] Analyze slow query logs
- [ ] Check memory leaks (worker restarts)
- [ ] Review rate limit violations

### Monthly
- [ ] Update dependencies (`poetry update`)
- [ ] Review and archive old logs
- [ ] Rotate API keys if needed
- [ ] Performance optimization review
- [ ] Security patch updates

### Quarterly
- [ ] Security audit
- [ ] Load testing
- [ ] Disaster recovery drill
- [ ] Documentation review

---

## Common Issues & Solutions

### Issue: API returns 500 errors
**Check:**
- Application logs: `docker-compose logs api`
- Database connection: verify DATABASE_URL
- LLM API key: verify QUERY_REFINEMENT_LLM_API_KEY
- Redis connection: verify REDIS_URL

### Issue: Slow response times
**Check:**
- Database query performance
- Connection pool exhaustion
- Worker count (increase if CPU allows)
- LLM provider rate limits

### Issue: Authentication failures
**Check:**
- SECRET_KEY is set and consistent across restarts
- Token expiration settings
- User exists in database
- Clock synchronization (JWT uses timestamps)

### Issue: Database connection errors
**Check:**
- DATABASE_URL is correct
- Database server is reachable
- Connection pool settings
- Database user permissions

### Issue: Rate limiting too aggressive
**Adjust:**
- Increase LLM_RATE_LIMIT_RPM
- Increase LLM_RATE_LIMIT_PER_USER_RPM
- Review concurrent request limits

---

## Emergency Contacts

### On-Call Procedures
1. Check health endpoint
2. Review error logs
3. Check monitoring dashboard
4. Verify external dependencies (database, Redis, LLM API)
5. Escalate if needed

### Support Channels
- **Documentation:** /docs endpoints
- **Logs:** Application and access logs
- **Metrics:** Monitoring dashboard
- **Database:** Direct database access (emergency only)

---

## Success Criteria

### Deployment is successful when:
- [ ] Health endpoint returns 200
- [ ] API documentation is accessible
- [ ] Authentication works
- [ ] Test queries complete successfully
- [ ] No critical errors in logs
- [ ] Response times < 2s (p95)
- [ ] Error rate < 1%
- [ ] Monitoring dashboards show healthy metrics

### System is production-ready when:
- [ ] All checklist items completed
- [ ] Smoke tests pass
- [ ] Performance tests meet requirements
- [ ] Security hardening complete
- [ ] Monitoring and alerts configured
- [ ] Backup and recovery tested
- [ ] Documentation updated
- [ ] Team trained on operations

---

## Sign-off

**Deployment Manager:** ___________________  
**Date:** ___________________  
**Version:** 0.3.0  
**Status:** ✅ APPROVED FOR PRODUCTION

---

## Additional Resources

- **API Documentation:** https://your-domain.com/docs
- **Production Audit:** [PRODUCTION_READINESS_AUDIT.md](./PRODUCTION_READINESS_AUDIT.md)
- **Deployment Guide:** [production_deployment.md](./production_deployment.md)
- **Quick Start:** [QUICK_START_VM_DEPLOYMENT.md](./QUICK_START_VM_DEPLOYMENT.md)
- **Architecture:** [api_service.md](./api_service.md)
