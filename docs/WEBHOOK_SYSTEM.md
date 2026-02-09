# Webhook System Documentation

## Overview

The webhook system enables real-time event notifications to external systems, allowing seamless integration with other applications like literature search databases, workflow automation tools, and analytics platforms.

## Features

- **Event-driven notifications** - Real-time updates on refinement workflow events
- **HMAC signature security** - Cryptographic verification of webhook payloads
- **Automatic retry logic** - Exponential backoff for failed deliveries
- **Comprehensive tracking** - Full audit trail of all webhook deliveries
- **Performance statistics** - Success/failure rates and delivery analytics
- **Flexible event filtering** - Subscribe to specific event types only

## Event Types

### Refinement Events
- `refinement.started` - Triggered when a new refinement workflow begins
- `refinement.step_completed` - Triggered when a dimension is marked complete
- `refinement.complete` - Triggered when all dimensions are refined

### Synthesis Events
- `synthesis.started` - Triggered at the beginning of query synthesis
- `synthesis.complete` - Triggered after refined query is generated

### Query Events
- `query.created` - Triggered when a new query is created
- `query.updated` - Triggered when a query is updated

### Session Events
- `session.created` - Triggered when a new session is created
- `session.ended` - Triggered when a session ends

## API Endpoints

### Webhook Management

#### Get Available Event Types
```http
GET /api/webhooks/event-types
```

Returns list of all available event types that can be subscribed to.

**Response:**
```json
{
  "event_types": [
    "refinement.started",
    "refinement.step_completed",
    "refinement.complete",
    "synthesis.started",
    "synthesis.complete",
    "query.created",
    "query.updated",
    "session.created",
    "session.ended"
  ]
}
```

#### Create Webhook
```http
POST /api/webhooks
Authorization: Bearer <token>
Content-Type: application/json

{
  "url": "https://your-app.com/webhook-endpoint",
  "events": ["refinement.complete", "synthesis.complete"],
  "name": "Literature Search Integration",
  "description": "Automatically trigger literature search when refinement completes",
  "max_retries": 3,
  "timeout_seconds": 30
}
```

**Response:**
```json
{
  "webhook_id": 1,
  "secret": "aK9sD3fG2hJ5lP8qW1xZ4v7nM0bT6cY",
  "message": "Store this secret securely. It cannot be retrieved later."
}
```

⚠️ **Important:** The secret is only shown once. Store it securely for HMAC signature verification.

#### List Webhooks
```http
GET /api/webhooks?active_only=false
Authorization: Bearer <token>
```

Returns all webhooks for the authenticated user.

**Response:**
```json
[
  {
    "id": 1,
    "user_id": 123,
    "url": "https://your-app.com/webhook-endpoint",
    "events": ["refinement.complete", "synthesis.complete"],
    "name": "Literature Search Integration",
    "description": "Automatically trigger literature search",
    "active": true,
    "max_retries": 3,
    "timeout_seconds": 30,
    "total_deliveries": 45,
    "successful_deliveries": 43,
    "failed_deliveries": 2,
    "last_delivery_at": "2026-02-09T14:30:00Z",
    "last_delivery_status": "success",
    "last_error": null,
    "created_at": "2026-02-01T10:00:00Z",
    "updated_at": "2026-02-09T14:30:00Z"
  }
]
```

#### Get Webhook Details
```http
GET /api/webhooks/{webhook_id}
Authorization: Bearer <token>
```

#### Update Webhook
```http
PUT /api/webhooks/{webhook_id}
Authorization: Bearer <token>
Content-Type: application/json

{
  "active": true,
  "events": ["refinement.complete", "synthesis.complete", "refinement.started"],
  "timeout_seconds": 45
}
```

Only provided fields are updated. Others remain unchanged.

#### Delete Webhook
```http
DELETE /api/webhooks/{webhook_id}
Authorization: Bearer <token>
```

Deletes the webhook and all associated delivery history.

#### Regenerate Secret
```http
POST /api/webhooks/{webhook_id}/regenerate-secret
Authorization: Bearer <token>
```

Generates a new secret. The old secret is immediately invalidated.

**Response:**
```json
{
  "webhook_id": 1,
  "secret": "nM5xL9pK2wQ8fD3hJ7vC1zY4bT6aS0gR",
  "message": "Secret regenerated. Update your webhook endpoint with the new secret."
}
```

### Delivery History

#### Get Webhook Deliveries
```http
GET /api/webhooks/{webhook_id}/deliveries?limit=100&status_filter=failed
Authorization: Bearer <token>
```

**Query Parameters:**
- `limit` - Maximum number of deliveries to return (default: 100)
- `status_filter` - Filter by status: "success", "failed", "timeout", "pending"

**Response:**
```json
[
  {
    "id": 1234,
    "webhook_id": 1,
    "event_type": "refinement.complete",
    "attempt_number": 1,
    "status": "success",
    "status_code": 200,
    "response_body": "{\"received\": true}",
    "error_message": null,
    "duration_ms": 145,
    "created_at": "2026-02-09T14:30:00Z",
    "completed_at": "2026-02-09T14:30:00Z"
  }
]
```

#### Get Recent Deliveries (All Webhooks)
```http
GET /api/webhooks/deliveries/recent?limit=50
Authorization: Bearer <token>
```

Returns recent deliveries across all user's webhooks.

### Testing

#### Test Webhook
```http
POST /api/webhooks/{webhook_id}/test
Authorization: Bearer <token>
Content-Type: application/json

{
  "test_data": {
    "custom": "payload"
  }
}
```

Sends a test event to verify webhook configuration.

**Response:**
```json
{
  "success": true,
  "status_code": 200,
  "response_body": "{\"received\": true}",
  "error_message": null,
  "duration_ms": 145
}
```

## Webhook Payload Format

All webhook events are delivered as HTTP POST requests with the following format:

### Headers
```
Content-Type: application/json
X-Webhook-Signature: sha256=<hmac_signature>
X-Webhook-Event: <event_type>
X-Webhook-ID: <webhook_id>
X-Webhook-Attempt: <attempt_number>
User-Agent: QueryRefinement-Webhook/1.0
```

### Body
```json
{
  "event": "refinement.complete",
  "data": {
    "query_id": 123,
    "total_steps": 5,
    "timestamp": "2026-02-09T14:30:00Z"
  },
  "webhook_id": 1,
  "timestamp": "2026-02-09T14:30:00Z",
  "attempt": 1
}
```

## Security - HMAC Signature Verification

All webhook payloads include an HMAC-SHA256 signature for security. **Always verify the signature** before processing webhook events.

### Verification Steps

1. Extract the signature from the `X-Webhook-Signature` header
2. Get your webhook secret (received when webhook was created)
3. Compute HMAC-SHA256 of the raw request body using the secret
4. Compare computed signature with the provided signature

### Example (Python)
```python
import hmac
import hashlib

def verify_webhook_signature(payload_body: bytes, signature_header: str, secret: str) -> bool:
    """
    Verify webhook signature.
    
    Args:
        payload_body: Raw request body as bytes
        signature_header: Value from X-Webhook-Signature header
        secret: Your webhook secret
        
    Returns:
        True if signature is valid, False otherwise
    """
    # Extract signature (format: "sha256=<hex_signature>")
    expected_signature = signature_header.replace('sha256=', '')
    
    # Compute signature
    computed_signature = hmac.new(
        key=secret.encode('utf-8'),
        msg=payload_body,
        digestmod=hashlib.sha256
    ).hexdigest()
    
    # Constant-time comparison
    return hmac.compare_digest(computed_signature, expected_signature)


# Usage in Flask/FastAPI
@app.post('/webhook')
async def handle_webhook(request: Request):
    payload_body = await request.body()
    signature = request.headers.get('X-Webhook-Signature')
    
    if not verify_webhook_signature(payload_body, signature, WEBHOOK_SECRET):
        raise HTTPException(status_code=401, detail="Invalid signature")
    
    # Process webhook event
    event_data = await request.json()
    # ... handle event ...
```

### Example (Node.js)
```javascript
const crypto = require('crypto');

function verifyWebhookSignature(payloadBody, signatureHeader, secret) {
    // Extract signature
    const expectedSignature = signatureHeader.replace('sha256=', '');
    
    // Compute signature
    const computedSignature = crypto
        .createHmac('sha256', secret)
        .update(payloadBody)
        .digest('hex');
    
    // Constant-time comparison
    return crypto.timingSafeEqual(
        Buffer.from(expectedSignature),
        Buffer.from(computedSignature)
    );
}

// Usage in Express
app.post('/webhook', express.raw({type: 'application/json'}), (req, res) => {
    const signature = req.headers['x-webhook-signature'];
    
    if (!verifyWebhookSignature(req.body, signature, WEBHOOK_SECRET)) {
        return res.status(401).json({error: 'Invalid signature'});
    }
    
    // Process webhook event
    const event = JSON.parse(req.body.toString());
    // ... handle event ...
});
```

## Retry Logic

The webhook system automatically retries failed deliveries using exponential backoff:

- **Attempt 1:** Immediate delivery
- **Attempt 2:** Wait 2 seconds, retry
- **Attempt 3:** Wait 4 seconds, retry
- **Attempt 4:** Wait 8 seconds, retry

### Retry Triggers
Deliveries are retried when:
- HTTP status code is not 2xx
- Request times out
- Network error occurs

### Success Criteria
A delivery is considered successful when:
- Server responds with HTTP status 200-299
- Response is received within timeout period

## Event Payload Examples

### refinement.started
```json
{
  "event": "refinement.started",
  "data": {
    "query_id": 123,
    "user_id": 456,
    "framework": "pico_advanced",
    "timestamp": "2026-02-09T14:00:00Z"
  },
  "webhook_id": 1,
  "timestamp": "2026-02-09T14:00:00Z",
  "attempt": 1
}
```

### refinement.step_completed
```json
{
  "event": "refinement.step_completed",
  "data": {
    "query_id": 123,
    "dimension": "population",
    "aspect": "population",
    "answer": "adults aged 18-65 with Type 2 diabetes",
    "timestamp": "2026-02-09T14:05:00Z"
  },
  "webhook_id": 1,
  "timestamp": "2026-02-09T14:05:00Z",
  "attempt": 1
}
```

### refinement.complete
```json
{
  "event": "refinement.complete",
  "data": {
    "query_id": 123,
    "total_steps": 5,
    "timestamp": "2026-02-09T14:15:00Z"
  },
  "webhook_id": 1,
  "timestamp": "2026-02-09T14:15:00Z",
  "attempt": 1
}
```

### synthesis.started
```json
{
  "event": "synthesis.started",
  "data": {
    "query_id": 123,
    "initial_query": "diabetes treatment",
    "timestamp": "2026-02-09T14:16:00Z"
  },
  "webhook_id": 1,
  "timestamp": "2026-02-09T14:16:00Z",
  "attempt": 1
}
```

### synthesis.complete
```json
{
  "event": "synthesis.complete",
  "data": {
    "query_id": 123,
    "initial_query": "diabetes treatment",
    "refined_query": "What are the efficacy and safety outcomes of SGLT-2 inhibitors versus DPP-4 inhibitors for glycemic control in adults aged 18-65 with Type 2 diabetes who have inadequate control on metformin monotherapy?",
    "timestamp": "2026-02-09T14:20:00Z"
  },
  "webhook_id": 1,
  "timestamp": "2026-02-09T14:20:00Z",
  "attempt": 1
}
```

## Use Cases

### 1. Automated Literature Search
Trigger a literature search in PubMed/Scopus when synthesis completes:

```python
@app.post('/webhook')
async def handle_webhook(request: Request):
    event = await request.json()
    
    if event['event'] == 'synthesis.complete':
        refined_query = event['data']['refined_query']
        
        # Trigger literature search
        search_results = await pubmed_search(refined_query)
        
        # Store results
        await store_search_results(event['data']['query_id'], search_results)
```

### 2. Workflow Automation
Chain multiple systems together:

```javascript
async function handleWebhook(event) {
    switch(event.event) {
        case 'refinement.complete':
            // Notify project team
            await slack.sendMessage(`Refinement complete for query ${event.data.query_id}`);
            break;
            
        case 'synthesis.complete':
            // Trigger next step in workflow
            await projectManagement.createTask({
                title: 'Review refined query',
                queryId: event.data.query_id,
                refinedQuery: event.data.refined_query
            });
            break;
    }
}
```

### 3. Analytics & Monitoring
Track refinement workflows in analytics platform:

```python
@app.post('/webhook')
async def handle_webhook(request: Request):
    event = await request.json()
    
    # Send to analytics
    analytics.track(
        user_id=event['data']['user_id'],
        event_type=event['event'],
        properties=event['data']
    )
```

## Best Practices

### 1. Security
- ✅ Always verify HMAC signatures
- ✅ Use HTTPS endpoints only
- ✅ Store webhook secrets securely (environment variables, secrets manager)
- ✅ Regenerate secrets periodically
- ❌ Never log or expose webhook secrets

### 2. Reliability
- ✅ Respond with 2xx status code quickly (< 5 seconds)
- ✅ Process webhook payloads asynchronously
- ✅ Implement idempotency (handle duplicate deliveries)
- ✅ Monitor delivery failure rates
- ❌ Don't perform long-running tasks synchronously

### 3. Error Handling
- ✅ Return 2xx for successfully received webhooks (even if processing fails later)
- ✅ Return 5xx for temporary failures that should be retried
- ✅ Return 4xx for permanent failures (invalid webhook config)
- ✅ Log webhook processing errors for debugging

### 4. Testing
- ✅ Use the test endpoint to verify configuration
- ✅ Test with ngrok/localtunnel during development
- ✅ Monitor delivery history regularly
- ✅ Set up alerts for high failure rates

## Troubleshooting

### Webhook Not Receiving Events

1. **Check webhook is active**
   ```http
   GET /api/webhooks/{webhook_id}
   ```
   Verify `"active": true`

2. **Check event subscription**
   Verify your webhook is subscribed to the event type

3. **Test connectivity**
   ```http
   POST /api/webhooks/{webhook_id}/test
   ```

4. **Check delivery history**
   ```http
   GET /api/webhooks/{webhook_id}/deliveries?limit=10
   ```
   Look for error messages in failed deliveries

### Signature Verification Failing

1. **Check secret usage**
   - Ensure you're using the correct secret
   - Secret is case-sensitive
   - Don't include "sha256=" prefix in secret

2. **Check payload handling**
   - Use raw request body (not parsed JSON)
   - Don't modify payload before verification
   - Check character encoding (UTF-8)

3. **Test signature generation**
   ```python
   import hmac, hashlib
   secret = "your_webhook_secret"
   payload = b'{"event":"test"}'
   signature = hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()
   print(f"Expected signature: sha256={signature}")
   ```

### High Failure Rate

1. **Check timeout settings**
   - Increase `timeout_seconds` if endpoint is slow
   - Optimize webhook endpoint response time

2. **Check endpoint availability**
   - Verify firewall rules allow incoming webhooks
   - Check SSL certificate is valid
   - Test endpoint with curl

3. **Monitor logs**
   ```http
   GET /api/webhooks/{webhook_id}/deliveries?status_filter=failed&limit=50
   ```

## Database Schema

### webhooks table
```sql
CREATE TABLE webhooks (
    id INTEGER PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id),
    url VARCHAR(2048) NOT NULL,
    events JSON NOT NULL,
    secret VARCHAR(256) NOT NULL,
    name VARCHAR(256),
    description TEXT,
    active BOOLEAN NOT NULL DEFAULT TRUE,
    max_retries INTEGER NOT NULL DEFAULT 3,
    timeout_seconds INTEGER NOT NULL DEFAULT 30,
    total_deliveries INTEGER NOT NULL DEFAULT 0,
    successful_deliveries INTEGER NOT NULL DEFAULT 0,
    failed_deliveries INTEGER NOT NULL DEFAULT 0,
    last_delivery_at TIMESTAMP WITH TIME ZONE,
    last_delivery_status VARCHAR(50),
    last_error TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);
```

### webhook_deliveries table
```sql
CREATE TABLE webhook_deliveries (
    id INTEGER PRIMARY KEY,
    webhook_id INTEGER NOT NULL REFERENCES webhooks(id) ON DELETE CASCADE,
    event_type VARCHAR(100) NOT NULL,
    event_data JSON NOT NULL,
    attempt_number INTEGER NOT NULL,
    status_code INTEGER,
    response_body TEXT,
    status VARCHAR(50) NOT NULL,
    error_message TEXT,
    duration_ms INTEGER,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    completed_at TIMESTAMP WITH TIME ZONE
);
```

## Architecture

### Components

1. **Database Models** (`query_refinement_module/db/models/webhook.py`)
   - Webhook configuration storage
   - Delivery history tracking

2. **CRUD Operations** (`query_refinement_module/db/crud_webhooks.py`)
   - Webhook management functions
   - Delivery record management

3. **Webhook Service** (`query_refinement_module/services/webhook_service.py`)
   - HMAC signature generation
   - HTTP delivery with retry logic
   - Event triggering and routing

4. **API Endpoints** (`query_refinement_module/api/routes/webhooks.py`)
   - RESTful webhook management
   - Delivery history viewing
   - Testing functionality

5. **Event Triggers** (`query_refinement_module/api/routes/refinement.py`)
   - Integration points in refinement workflow
   - Automatic event emission at key stages

### Flow Diagram

```
Refinement Workflow
       ↓
  Event Trigger Point
       ↓
  Build Event Payload
       ↓
  Query Active Webhooks (filtered by event type & user)
       ↓
  For Each Webhook:
       ↓
  Generate HMAC Signature
       ↓
  HTTP POST with Headers
       ↓
  ┌──────────────┐
  │  Success?    │
  └──────┬───────┘
         │
    ┌────┴────┐
   Yes       No
    │         │
    │    Retry Logic
    │    (exponential backoff)
    │         │
    │    ┌────┴────┐
    │   Yes       No (max retries)
    │    │         │
    └────┼─────────┘
         │
  Update Statistics
  Save Delivery Record
```

## Migration

The webhook system was added via Alembic migration `b5637a6b9fdb_add_webhook_system_tables.py`.

To apply:
```bash
poetry run alembic upgrade head
```

To rollback:
```bash
poetry run alembic downgrade -1
```

## Future Enhancements

Potential improvements for future versions:

1. **Webhook Templates** - Pre-configured webhooks for popular services
2. **Batch Delivery** - Group multiple events into single delivery
3. **Event Filtering** - Advanced filter syntax (e.g., only certain frameworks)
4. **Rate Limiting** - Configurable rate limits for delivery
5. **Custom Headers** - Allow users to specify additional headers
6. **Transformation Rules** - Transform event payloads before delivery
7. **Webhook Groups** - Deliver to multiple endpoints for same event
8. **Delivery Scheduling** - Queue events for delivery at specific times

## Support

For issues or questions about the webhook system:

1. Check delivery history for error messages
2. Use the test endpoint to verify configuration
3. Review this documentation for examples and best practices
4. Check application logs for webhook-related errors

## Changelog

### v1.0.0 (2026-02-09)
- Initial release
- 9 event types
- HMAC signature verification
- Automatic retry with exponential backoff
- Comprehensive delivery tracking
- Full REST API for management
