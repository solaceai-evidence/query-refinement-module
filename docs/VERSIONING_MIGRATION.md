# Migration Guide: Unversioned to Versioned APIs

## Overview

All API endpoints have been updated to include versioning. You must update all API calls to include `/v1/` in the path.

## What Changed

### Before (Unversioned)
```python
POST /api/refinement/start
GET  /api/queries/123
POST /api/webhooks
```

### After (Versioned - v1)
```python
POST /api/v1/refinement/start
GET  /api/v1/queries/123
POST /api/v1/webhooks
```

## Migration Checklist

### 1. Update Frontend/Client Code

**Before:**
```javascript
const API_BASE = 'http://localhost:8000/api';

fetch(`${API_BASE}/refinement/start`, {
  method: 'POST',
  body: JSON.stringify({...})
});
```

**After:**
```javascript
const API_BASE = 'http://localhost:8000/api/v1';  // ← Add /v1

fetch(`${API_BASE}/refinement/start`, {
  method: 'POST',
  body: JSON.stringify({...})
});
```

### 2. Update Python Clients

**Before:**
```python
REFINEMENT_API = "http://localhost:8000/api"

response = requests.post(
    f"{REFINEMENT_API}/refinement/start",
    json={"original_query": "...", "framework_name": "pico"}
)
```

**After:**
```python
REFINEMENT_API = "http://localhost:8000/api/v1"  # ← Add /v1

response = requests.post(
    f"{REFINEMENT_API}/refinement/start",
    json={"original_query": "...", "framework_name": "pico"}
)
```

### 3. Update Environment Variables

**Before:**
```bash
API_BASE_URL=http://localhost:8000/api
```

**After:**
```bash
API_BASE_URL=http://localhost:8000/api/v1
```

### 4. Update Integration Tests

**Before:**
```python
def test_start_refinement():
    response = client.post("/api/refinement/start", json={...})
```

**After:**
```python
def test_start_refinement():
    response = client.post("/api/v1/refinement/start", json={...})
```

### 5. Update Webhooks (No Change Needed)

Webhook configurations remain the same—only update the URLs you use to manage webhooks:

**Before:**
```bash
curl -X POST http://localhost:8000/api/webhooks
```

**After:**
```bash
curl -X POST http://localhost:8000/api/v1/webhooks
```

## Affected Endpoints

All endpoints under `/api/` now require version prefix:

| Category | Old Path | New Path |
|----------|----------|----------|
| **Auth** | `/api/auth/register` | `/api/v1/auth/register` |
| | `/api/auth/login` | `/api/v1/auth/login` |
| **Refinement** | `/api/refinement/start` | `/api/v1/refinement/start` |
| | `/api/refinement/submit-answer` | `/api/v1/refinement/submit-answer` |
| | `/api/refinement/synthesize` | `/api/v1/refinement/synthesize` |
| | `/api/refinement/queries/{id}/forward-to-qa` | `/api/v1/refinement/queries/{id}/forward-to-qa` |
| **Queries** | `/api/queries/sessions` | `/api/v1/queries/sessions` |
| | `/api/queries/{id}` | `/api/v1/queries/{id}` |
| **Webhooks** | `/api/webhooks` | `/api/v1/webhooks` |
| | `/api/webhooks/{id}` | `/api/v1/webhooks/{id}` |
| **Feedback** | `/api/feedback` | `/api/v1/feedback` |
| **Audit** | `/api/audit/logs` | `/api/v1/audit/logs` |
| **Admin** | `/api/admin/*` | `/api/v1/admin/*` |

## Unaffected Endpoints

These endpoints remain unversioned:

| Endpoint | Purpose | No Change |
|----------|---------|-----------|
| `/health` | Health check | ✅ Still `/health` |
| `/ready` | Readiness check | ✅ Still `/ready` |
| `/` | Root/info | ✅ Still `/` |
| `/docs` | API documentation | ✅ Still `/docs` |
| `/api/version` | Version info | ✅ Still `/api/version` |

## Automated Migration Script

Use this script to update your code:

```bash
#!/bin/bash
# migrate-to-versioned-api.sh

# Update Python files
find . -type f -name "*.py" -exec sed -i '' 's|/api/refinement|/api/v1/refinement|g' {} +
find . -type f -name "*.py" -exec sed -i '' 's|/api/queries|/api/v1/queries|g' {} +
find . -type f -name "*.py" -exec sed -i '' 's|/api/webhooks|/api/v1/webhooks|g' {} +
find . -type f -name "*.py" -exec sed -i '' 's|/api/auth|/api/v1/auth|g' {} +
find . -type f -name "*.py" -exec sed -i '' 's|/api/feedback|/api/v1/feedback|g' {} +
find . -type f -name "*.py" -exec sed -i '' 's|/api/audit|/api/v1/audit|g' {} +
find . -type f -name "*.py" -exec sed -i '' 's|/api/admin|/api/v1/admin|g' {} +

# Update JavaScript/TypeScript files
find . -type f \( -name "*.js" -o -name "*.ts" -o -name "*.jsx" -o -name "*.tsx" \) \
  -exec sed -i '' 's|/api/refinement|/api/v1/refinement|g' {} +
find . -type f \( -name "*.js" -o -name "*.ts" -o -name "*.jsx" -o -name "*.tsx" \) \
  -exec sed -i '' 's|/api/queries|/api/v1/queries|g' {} +
find . -type f \( -name "*.js" -o -name "*.ts" -o -name "*.jsx" -o -name "*.tsx" \) \
  -exec sed -i '' 's|/api/webhooks|/api/v1/webhooks|g' {} +

# Preserve unversioned endpoints
find . -type f -exec sed -i '' 's|/api/v1/version|/api/version|g' {} +

echo "✅ Migration complete!"
echo "⚠️  Please review changes and test thoroughly before deploying."
```

## Testing After Migration

### 1. Run Test Suite
```bash
poetry run pytest
```

### 2. Test Key Endpoints
```bash
# Check version endpoint
curl http://localhost:8000/api/version

# Test refinement start
curl -X POST http://localhost:8000/api/v1/refinement/start \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"original_query": "test", "framework_name": "pico"}'
```

### 3. Check Frontend
- Open browser console
- Check for 404 errors
- Verify API calls use `/api/v1/...`

## Rollback Plan

If you need to rollback temporarily, you can create route aliases:

```python
# In main.py (temporary compatibility layer)
from fastapi import APIRouter

# Create compatibility router (forwards to v1)
compat_router = APIRouter(prefix="/api")

@compat_router.post("/refinement/start")
async def compat_start(request: Request):
    """Compatibility shim - forwards to v1."""
    # Forward to v1 endpoint
    return await app.url_path_for("start_refinement")(request)

app.include_router(compat_router)
```

**Note:** This is temporary only. Plan to remove after migration.

## Timeline

- **T+0 (Today):** Versioning deployed
- **T+1 week:** Update all internal code
- **T+2 weeks:** Notify external API consumers
- **T+1 month:** Remove compatibility shims (if any)

## Need Help?

- Check API docs: `http://localhost:8000/docs`
- Version info: `GET /api/version`
- Full versioning docs: `docs/API_VERSIONING.md`

## Common Issues

### Issue: 404 Not Found

**Before:**
```
POST /api/refinement/start → 404
```

**Fix:**
```
POST /api/v1/refinement/start → 200
```

### Issue: CORS Errors

Update your CORS origins to include the versioned paths (no change needed—version is in path, not origin).

### Issue: Frontend Build Errors

If using environment variables:
```javascript
// .env
VITE_API_BASE_URL=http://localhost:8000/api/v1
```

Update your config and rebuild.
