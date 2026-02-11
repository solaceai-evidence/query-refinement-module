# API Versioning Strategy

## Overview

The Query Refinement API uses **URL path-based versioning** to maintain backward compatibility and enable smooth migration between API versions.

## Versioning Format

```
https://api.example.com/api/{version}/{resource}
                              ↑
                           Version identifier
```

**Examples:**
- `https://api.example.com/api/v1/refinement/start`
- `https://api.example.com/api/v1/queries/123`
- `https://api.example.com/api/v1/webhooks`

## Current Version

**v1** - Initial stable release (current)

## Supported Versions

| Version | Status | Release Date | End of Support |
|---------|--------|--------------|----------------|
| v1      | ✅ Stable | 2026-02-11 | - |

## Version Information Endpoint

Get comprehensive version information:

```bash
GET /api/version
```

**Response:**
```json
{
  "current_version": "v1",
  "latest_version": "v1",
  "supported_versions": ["v1"],
  "deprecated_versions": [],
  "min_supported_version": "v1"
}
```

## Breaking vs Non-Breaking Changes

### Non-Breaking Changes (Patch/Minor)
- ✅ Adding new endpoints
- ✅ Adding optional request parameters
- ✅ Adding fields to responses
- ✅ Adding new webhook events
- ✅ Performance improvements
- ✅ Bug fixes

**No version change required** - deployed within the same version.

### Breaking Changes (Major)
- ❌ Removing endpoints
- ❌ Removing request/response fields
- ❌ Changing required parameters
- ❌ Changing response structure
- ❌ Changing authentication method
- ❌ Changing status codes

**Requires new version** (e.g., v2) - old version maintained for 12 months.

## Deprecation Policy

### Timeline

1. **Announcement** (T+0)
   - New version released
   - Old version marked deprecated
   - Deprecation notice in docs and headers

2. **Warning Period** (T+6 months)
   - Deprecation warnings in responses
   - `Warning` header added to all responses
   - Email notifications to API users

3. **Sunset Period** (T+12 months)
   - Old version removed
   - Requests to old version return 410 Gone
   - Migration guide published

### Deprecation Headers

When using a deprecated version:

```http
HTTP/1.1 200 OK
X-API-Version: v1
Warning: 299 - "API version v1 is deprecated and will be removed on 2027-02-11. Please upgrade to v2."
```

## Version Selection

### Explicit Version (Recommended)

Always specify the version in your URL:

```python
import requests

# ✅ Explicit version
response = requests.post(
    "https://api.example.com/api/v1/refinement/start",
    json={"original_query": "...", "framework_name": "pico"}
)
```

### Default Behavior

If no version specified (not recommended), defaults to `v1`:

```python
# ⚠️ Implicit version (will break when v1 is removed)
response = requests.post(
    "https://api.example.com/api/refinement/start",  # No version
    json={...}
)
```

## Migration Guide

### Migrating from v1 to v2 (Future)

When v2 is released:

1. **Review breaking changes**
   - Read v2 migration guide
   - Check changelog for breaking changes

2. **Test in staging**
   - Update URLs to `/api/v2/...`
   - Run test suite
   - Verify responses

3. **Deploy gradually**
   - Use feature flags
   - Gradual rollout (10% → 50% → 100%)
   - Monitor error rates

4. **Complete migration**
   - Update all endpoints to v2
   - Remove v1 references
   - Update documentation

## Error Handling

### Invalid Version

```bash
GET /api/v99/refinement/start
```

**Response:**
```json
{
  "error": "invalid_api_version",
  "message": "API version 'v99' is not supported",
  "supported_versions": ["v1"],
  "help": "Use /api/v1/... for the current stable API"
}
```

### Removed Version

```bash
GET /api/v0/refinement/start  # After v0 sunset
```

**Response:**
```json
{
  "error": "api_version_removed",
  "message": "API version 'v0' has been removed",
  "removed_date": "2026-02-11",
  "current_version": "v1",
  "migration_guide": "https://docs.example.com/migration/v0-to-v1"
}
```

## Version Headers

All responses include version headers:

```http
HTTP/1.1 200 OK
X-API-Version: v1
Content-Type: application/json
```

## Best Practices

### For API Consumers

1. ✅ **Always specify version explicitly**
   ```python
   BASE_URL = "https://api.example.com/api/v1"
   ```

2. ✅ **Monitor deprecation warnings**
   ```python
   if 'Warning' in response.headers:
       logger.warning(f"API deprecation: {response.headers['Warning']}")
   ```

3. ✅ **Stay updated**
   - Subscribe to API changelog
   - Monitor `/api/version` endpoint
   - Set up alerts for deprecation warnings

4. ✅ **Test new versions early**
   - Test v2 in staging before it becomes default
   - Provide feedback during beta period

### For API Maintainers

1. ✅ **Batch breaking changes**
   - Don't release v2, v3, v4 rapidly
   - Collect breaking changes and release together

2. ✅ **Maintain old versions**
   - Support for 12 months minimum
   - Security patches to all supported versions

3. ✅ **Communicate clearly**
   - Announce changes 6 months in advance
   - Provide migration guides
   - Offer migration support

4. ✅ **Version everything**
   - API endpoints
   - Webhook payloads
   - Error formats
   - Authentication methods

## Backward Compatibility

### Additive Changes (Safe)

```json
// v1 Response
{
  "query_id": 123,
  "refined_query": "..."
}

// v1 Response (with new field added - still v1)
{
  "query_id": 123,
  "refined_query": "...",
  "confidence_score": 0.95  // ← New field (safe to add)
}
```

### Breaking Changes (Requires v2)

```json
// v1 Response
{
  "query_id": 123,
  "refined_query": "..."
}

// v2 Response (field renamed - breaking!)
{
  "id": 123,              // ← Renamed from query_id
  "query": "..."          // ← Renamed from refined_query
}
```

## Monitoring Version Usage

Track version usage in your analytics:

```python
# Log version usage
logger.info(
    "API request",
    extra={
        "version": "v1",
        "endpoint": "/refinement/start",
        "user_id": user.id
    }
)
```

## Changelog

### v1 (2026-02-11) - Initial Release
- ✨ Query refinement workflow
- ✨ Synthesis mode
- ✨ Webhook system
- ✨ QA forwarding endpoint
- ✨ Admin analytics

### Future Versions

**v2 (Planned)**
- TBD based on user feedback and breaking changes needed

## Contact

For questions about API versioning:
- Documentation: `/docs`
- Support: support@example.com
- Changelog: `/api/version`
