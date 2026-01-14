# Logging and Tracing Implementation Guide

## Overview

This document describes the comprehensive logging and tracing system implemented for the Query Refinement Module. The system provides production-ready logging with structured output, PII sanitization, distributed tracing, and audit capabilities across both backend (Python/FastAPI) and frontend (JavaScript/React).

## Architecture

### Backend Architecture

```
query_refinement_module/
├── logging/
│   ├── __init__.py           # Public API
│   ├── config.py             # Centralized configuration
│   ├── formatters.py         # JSON and text formatters
│   ├── filters.py            # PII sanitization, context enrichment
│   └── middleware.py         # Request/response logging
├── tracing.py                # Distributed tracing utilities
└── api/
    └── main.py               # FastAPI app with logging middleware
```

### Frontend Architecture

```
frontend/src/utils/
├── logger/
│   └── index.js              # Logger utility (existing)
└── auth.js
```

## Backend Implementation

### 1. Logging Configuration

**Location:** `query_refinement_module/logging/config.py`

#### Usage:

```python
from query_refinement_module.logging import configure_logging

# Configure at application startup
configure_logging(
    level="INFO",              # DEBUG, INFO, WARNING, ERROR, CRITICAL
    log_format="json",         # "json" or "text"
    log_file="/var/log/app.log",  # Optional file path
    sanitize_pii=True,         # Enable PII sanitization
    redact_ip=False            # Whether to redact IP addresses
)
```

#### Environment Variables:

- `LOG_LEVEL`: Log level (default: INFO)
- `LOG_FORMAT`: Output format (default: text in dev, json in prod)
- `LOG_FILE`: Optional file path for log output

### 2. Log Formatters

**Two formatters available:**

#### A. JSON Formatter (Production)

```json
{
  "timestamp": "2026-01-14T10:30:45.123Z",
  "level": "INFO",
  "request_id": "a3f8c2d1",
  "trace_id": "550e8400-e29b-41d4-a716-446655440000",
  "span_id": "7f3b9c10",
  "user_id": "user_12345",
  "session_id": 789,
  "query_id": 456,
  "logger": "api.routes.refinement",
  "function": "submit_answer",
  "message": "Command executed successfully",
  "context": {
    "command_type": "skip",
    "execution_time_ms": 234
  }
}
```

#### B. Structured Text Formatter (Development)

```
2026-01-14 10:30:45.123 | INFO     | req:a3f8c2d1 | user:user_12345 | api.routes.refinement:submit_answer | Command executed successfully | {"command_type": "skip"}
```

### 3. PII Sanitization

**Automatically redacts:**
- Email addresses → `[EMAIL_REDACTED]`
- Phone numbers → `[PHONE_REDACTED]`
- SSN → `[SSN_REDACTED]`
- Credit cards → `[CREDIT_CARD_REDACTED]`
- API keys/tokens → `[API_KEY_REDACTED]`
- IP addresses (optional) → `[IP_ADDRESS_REDACTED]`

**Usage:**

```python
logger.info("User registered", extra={"context": {"email": "user@example.com"}})
# Output: ... "email": "[EMAIL_REDACTED]" ...
```

### 4. Request Logging Middleware

**Features:**
- Generates or extracts `request_id` from `X-Request-ID` header
- Generates `trace_id` for distributed tracing
- Logs request start (method, path, query params)
- Times request execution
- Logs response (status code, duration, size)
- Adds `X-Request-ID` and `X-Trace-ID` headers to response
- Warns on slow requests (>5s)

**Automatic Integration:**

Added to FastAPI app in `main.py`:

```python
from query_refinement_module.logging.middleware import RequestLoggingMiddleware

app.add_middleware(RequestLoggingMiddleware)
```

**Example Logs:**

```
INFO | req:a3f8c2d1 | Request started: POST /api/refinement/queries/456/answer
INFO | req:a3f8c2d1 | Request completed: POST /api/refinement/queries/456/answer | status:200 | duration:234ms
```

### 5. Distributed Tracing

**Enhanced tracing module with:**

#### A. Context Management

```python
from query_refinement_module.tracing import (
    generate_request_id, set_request_id, get_request_id,
    generate_trace_id, set_trace_id, get_trace_id,
    generate_span_id, set_span_id, get_span_id,
)

# In middleware or API endpoint
request_id = generate_request_id()
set_request_id(request_id)

trace_id = generate_trace_id()
set_trace_id(trace_id)

# All downstream code automatically has access
logger.info("Processing request")  # Includes request_id and trace_id
```

#### B. Trace Context Propagation

**Frontend → Backend:**
1. Frontend generates `request_id`
2. Sends in `X-Request-ID` header
3. Backend extracts and sets in context
4. Backend returns `request_id` and `trace_id` in response headers
5. Frontend uses for subsequent logging

**Backend → Database:**
1. Request context includes `request_id`
2. All database queries logged with `request_id`
3. Enables correlation of DB operations to API requests

### 6. Using Loggers in Code

#### A. Get Logger

```python
import logging

logger = logging.getLogger(__name__)

# Context automatically added by filters
logger.info("User logged in", extra={"user_id": user.id})
```

#### B. Structured Logging

```python
logger.info(
    "Query refinement started",
    extra={
        "user_id": user.id,
        "context": {
            "framework": "PICO",
            "query_length": len(query),
            "session_id": session.id
        }
    }
)
```

#### C. Error Logging

```python
try:
    result = process_query()
except Exception as exc:
    logger.error(
        "Query processing failed",
        exc_info=exc,
        extra={
            "user_id": user.id,
            "context": {
                "query_id": query_id,
                "framework": framework
            }
        }
    )
    raise
```

## Frontend Implementation

### 1. Logger Utility

**Location:** `frontend/src/utils/logger/index.js`

#### Usage:

```javascript
import { logger } from '../utils/logger';

// Debug (development only)
logger.debug('State updated', { oldValue, newValue });

// Info (always logged)
logger.info('User logged in', { username });

// Warning (always logged)
logger.warn('Slow API response', { duration_ms: 5000 });

// Error (always logged with stack trace)
logger.error('API call failed', error, { endpoint: '/api/queries' });
```

### 2. Request ID Integration

**In API client (`services/api.js`):**

```javascript
// Request interceptor
apiClient.interceptors.request.use(config => {
  const requestId = generateRequestId();
  config.headers['X-Request-ID'] = requestId;
  
  logger.info('API request', {
    request_id: requestId,
    method: config.method,
    url: config.url
  });
  
  return config;
});

// Response interceptor
apiClient.interceptors.response.use(response => {
  const requestId = response.headers['x-request-id'];
  const traceId = response.headers['x-trace-id'];
  
  logger.info('API response', {
    request_id: requestId,
    trace_id: traceId,
    status: response.status
  });
  
  return response;
});
```

## Log Levels & Usage Guidelines

| Level        | Use Case           | Examples                               | Production |
| ------------ | ------------------ | -------------------------------------- | ---------- |
| **DEBUG**    | Development traces | Variable dumps, state transitions      | Hidden     |
| **INFO**     | Business events    | User actions, API calls, system events | Visible    |
| **WARNING**  | Recoverable errors | Retries, slow queries, rate limits     | Visible    |
| **ERROR**    | Failures           | API errors, exceptions, data issues    | Visible    |
| **CRITICAL** | System failures    | Service down, data corruption          | Visible    |

## Best Practices

### 1. What to Log

**✅ DO LOG:**
- User actions (login, logout, query creation)
- API requests and responses
- Command executions
- State transitions
- Performance metrics (duration, size)
- Errors and exceptions
- Security events (failed auth, suspicious activity)

**❌ DON'T LOG:**
- Passwords or tokens (automatically sanitized)
- Full user email addresses in production (sanitized)
- Large payloads or responses
- Sensitive personal information

### 2. Structured Logging

**Use context objects:**

```python
# Good
logger.info(
    "Query created",
    extra={"context": {
        "query_id": 123,
        "framework": "PICO",
        "user_id": "user_456"
    }}
)

# Bad
logger.info(f"Query created: {query_id} with framework {framework}")
```

### 3. Log Correlation

**Always use request_id for correlation:**

```python
# Backend - automatically added
logger.info("Step 1 complete")
logger.info("Step 2 started")
# Both logs have same request_id

# Frontend
logger.info('User action', { request_id: getCurrentRequestId() });
```

## Monitoring & Alerting

### 1. Log Queries

**Find all logs for a request:**

```bash
# JSON format
jq 'select(.request_id == "a3f8c2d1")' logs.json

# Text format
grep "req:a3f8c2d1" logs.txt
```

**Find errors for a user:**

```bash
jq 'select(.user_id == "user_123" and .level == "ERROR")' logs.json
```

### 2. Performance Monitoring

**Slow requests:**

```bash
jq 'select(.context.duration_ms > 5000)' logs.json
```

**Database query times:**

```bash
jq 'select(.message contains "SQL query" and .context.duration_ms > 1000)' logs.json
```

### 3. Error Tracking

**Error counts by type:**

```bash
jq -r 'select(.level == "ERROR") | .exception.type' logs.json | sort | uniq -c
```

## Production Deployment

### 1. Configuration

**Environment variables:**

```env
LOG_LEVEL=INFO
LOG_FORMAT=json
LOG_FILE=/var/log/query-refinement/app.log
```

### 2. Log Storage

**Options:**

#### A. File System
- Location: `/var/log/query-refinement/`
- Rotation: logrotate (daily, keep 30 days)

#### B. Log Aggregation (Recommended)
- Grafana Loki
- ELK Stack
- CloudWatch Logs
- DataDog

### 3. Log Retention

| Log Type | Hot Storage | Cold Storage  | Total   |
| -------- | ----------- | ------------- | ------- |
| DEBUG    | 7 days      | -             | 7 days  |
| INFO     | 30 days     | 60 days (S3)  | 90 days |
| WARNING  | 60 days     | 30 days (S3)  | 90 days |
| ERROR    | 90 days     | 9 months (S3) | 1 year  |
| CRITICAL | 1 year      | 2 years (S3)  | 3 years |

## Troubleshooting

### 1. No Request ID in Logs

**Problem:** Logs don't include request_id

**Solution:**
- Ensure `RequestLoggingMiddleware` is added to FastAPI app
- Check that `RequestContextFilter` is applied to loggers
- Verify `configure_logging()` is called at startup

### 2. PII Not Sanitized

**Problem:** Email addresses appearing in logs

**Solution:**
- Check `sanitize_pii=True` in `configure_logging()`
- Verify `PIISanitizationFilter` is applied
- Test with: `logger.info("test@example.com")`

### 3. Frontend Logs Not Correlated

**Problem:** Can't trace frontend to backend logs

**Solution:**
- Ensure `X-Request-ID` header is sent in requests
- Check response headers include `X-Request-ID`
- Verify frontend stores and uses request_id

## Future Enhancements

### Phase 2 (Planned)

1. **Frontend Log Forwarding**
   - Send browser logs to backend API
   - Batch and buffer for performance
   - `/api/logs/frontend` endpoint

2. **Audit Logging**
   - Separate audit_logs table
   - Track all user actions
   - GDPR compliance exports

3. **External Integrations**
   - Sentry for error tracking
   - Prometheus for metrics
   - OpenTelemetry for distributed tracing

### Phase 3 (Planned)

1. **Advanced Analytics**
   - User behavior tracking
   - Performance dashboards
   - Anomaly detection

2. **Alerting**
   - Error rate thresholds
   - Slow request alerts
   - Security event notifications

## Support & Maintenance

### Log Files

**Development:**
- stdout (terminal)
- Optional: `./logs/development.log`

**Production:**
- `/var/log/query-refinement/app.log`
- Rotated daily, compressed after 7 days
- Shipped to log aggregation service

### Health Checks

**Endpoints:**
- `GET /health` - Basic health check
- `GET /ready` - Readiness with dependency checks

Both include logging status and version information.

## References

- [Python Logging HOWTO](https://docs.python.org/3/howto/logging.html)
- [Structured Logging Best Practices](https://engineering.linkedin.com/blog/2020/improving-operational-excellence-through-structured-logging)
- [FastAPI Middleware](https://fastapi.tiangolo.com/tutorial/middleware/)
- [ContextVars in Python](https://docs.python.org/3/library/contextvars.html)

---

**Version:** 1.0.0
**Last Updated:** January 14, 2026
**Authors:** Query Refinement Team
