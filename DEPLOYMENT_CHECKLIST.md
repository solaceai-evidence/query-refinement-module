# Deployment Checklist - API Versioning Migration

## ✅ Pre-Deployment (Complete)

- [x] API versioning implemented (`query_refinement_module/api/versioning.py`)
- [x] Version middleware added (`query_refinement_module/api/version_middleware.py`)
- [x] All routes updated to use `/api/v1/` prefix
- [x] Frontend .env updated with versioned base URL
- [x] Frontend API calls updated to remove `/api/` prefix (handled by baseURL)
- [x] Test files updated to use versioned endpoints
- [x] Documentation updated (API_VERSIONING.md, VERSIONING_MIGRATION.md)
- [x] Migration script created (`scripts/migrate_to_versioned_api.py`)

## 📋 Deployment Steps

### 1. Backend Deployment

```bash
# 1. Pull latest code
git pull origin main

# 2. Install dependencies (if needed)
poetry install

# 3. Run database migrations (if any)
poetry run alembic upgrade head

# 4. Run tests
poetry run pytest tests/api/test_versioning.py -v
poetry run pytest tests/integration/test_versioned_migration.py -v

# 5. Start backend
poetry run uvicorn query_refinement_module.api.main:app --reload
```

### 2. Frontend Deployment

```bash
cd frontend

# 1. Update .env or .env.production
# Ensure: VITE_API_BASE_URL=https://your-domain.com/api/v1

# 2. Install dependencies (if needed)
npm install

# 3. Build for production
npm run build

# 4. Deploy build/ directory to your hosting
```

### 3. Verification

#### Backend Tests
```bash
# Test version endpoint
curl https://your-api.com/api/version

# Expected response:
# {
#   "current_version": "v1",
#   "latest_version": "v1",
#   "supported_versions": ["v1"],
#   "deprecated_versions": [],
#   "min_supported_version": "v1"
# }

# Test health (unversioned)
curl https://your-api.com/health

# Test versioned endpoint
curl -X POST https://your-api.com/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username":"test","password":"test"}'

# Should return 401 or 422, NOT 404
```

#### Frontend Tests
```bash
# 1. Open browser console
# 2. Check Network tab - all requests should go to /api/v1/*
# 3. Verify no 404 errors
# 4. Test login/register flow
# 5. Test refinement workflow
```

### 4. Monitoring

Monitor these metrics for 24-48 hours:

- [ ] API response times (should be unchanged)
- [ ] Error rates (should not increase)
- [ ] 404 rates (should be zero for /api/v1/* paths)
- [ ] Frontend console errors
- [ ] User reports

### 5. Rollback Plan (If Needed)

If issues arise:

```bash
# Backend: Revert to previous commit
git revert HEAD
poetry run uvicorn query_refinement_module.api.main:app --reload

# Frontend: Deploy previous build
# Or temporarily update .env:
# VITE_API_BASE_URL=https://your-domain.com/api  # Old path
```

## 🔍 Post-Deployment Validation

### API Endpoints to Test

- [ ] `/health` - Health check (unversioned)
- [ ] `/ready` - Readiness check (unversioned)
- [ ] `/api/version` - Version info (unversioned)
- [ ] `/api/v1/auth/login` - Authentication
- [ ] `/api/v1/refinement/start` - Start refinement
- [ ] `/api/v1/queries/{id}` - Get query
- [ ] `/api/v1/webhooks` - Webhook management
- [ ] `/api/v1/feedback` - Submit feedback

### User Workflows to Test

- [ ] User registration
- [ ] User login
- [ ] Start refinement
- [ ] Answer questions (multi-turn)
- [ ] Synthesize query
- [ ] View history
- [ ] Manage webhooks (if used)

## 📊 Success Criteria

- ✅ No 404 errors on `/api/v1/*` endpoints
- ✅ All frontend API calls succeed
- ✅ Response times within normal range
- ✅ Error rates unchanged or decreased
- ✅ Users can complete full workflows
- ✅ Webhook deliveries succeed (if configured)

## 🚨 Known Issues & Mitigations

### Issue: Frontend build with old .env
**Mitigation:** Verify `.env.production` has correct VITE_API_BASE_URL

### Issue: Browser cache with old API calls
**Mitigation:** Force cache clear with version bump in index.html

### Issue: External integrations using old API paths
**Mitigation:** Notify integrators, provide migration guide

## 📝 Communication Plan

### Before Deployment
- [ ] Notify users of maintenance window (if needed)
- [ ] Send migration guide to API consumers
- [ ] Update API documentation at `/docs`

### During Deployment
- [ ] Monitor error logs
- [ ] Watch user reports
- [ ] Be ready to rollback if critical issues

### After Deployment
- [ ] Announce successful deployment
- [ ] Share new API documentation
- [ ] Provide example updated code

## 🔗 Resources

- API Versioning Strategy: `docs/API_VERSIONING.md`
- Migration Guide: `docs/VERSIONING_MIGRATION.md`
- Implementation Summary: `docs/VERSIONING_IMPLEMENTATION_SUMMARY.md`
- Middleware Integration: `MIDDLEWARE_INTEGRATION_GUIDE.md`

## ✅ Final Checklist

Before marking deployment as complete:

- [ ] All tests passing
- [ ] Frontend deployed with updated .env
- [ ] Backend deployed and healthy
- [ ] Version endpoint accessible
- [ ] Sample API calls succeed
- [ ] Frontend workflows work end-to-end
- [ ] Monitoring dashboards show healthy metrics
- [ ] Documentation updated and accessible
- [ ] Team notified of completion
- [ ] Migration guide sent to API consumers

---

**Deployment Date:** _______________  
**Deployed By:** _______________  
**Deployment Status:** ⬜ Success  ⬜ Partial  ⬜ Rollback  
**Notes:**
