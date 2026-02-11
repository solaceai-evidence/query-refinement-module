# Middleware Integration Guide for External Q&A Systems

## Overview
This guide explains how to use the Query Refinement Module as a middleware between users and external question-answering systems.

The Query Refinement Module preserves **full user control** through multi-turn clarification dialogues. It never guesses or auto-completes refinements—users provide explicit answers to clarification questions for each dimension before the refined query is forwarded to your QA system.

## Architecture

```
┌──────────┐      ┌────────────────────┐      ┌──────────────┐
│  User    │─────►│  Refinement Module │─────►│  Your Q&A    │
│  App     │◄─────│  (Middleware)      │◄─────│  System      │
└──────────┘      └────────────────────┘      └──────────────┘
     ▲                      │                         │
     │                      │                         │
     └──── Clarifications ──┘                         │
           (Multi-turn)                               │
                                                      │
                          Refined Query ─────────────►│
                          (After user approval)
```

## Key Principle: User Always in Control

- ✅ **Multi-turn clarifications**: System asks questions, user provides answers
- ✅ **No automated guessing**: Only extracts what's explicitly in the query
- ✅ **Dimension-driven**: Framework specifications define what to extract
- ✅ **User approval**: Forwarding happens only after complete refinement
- ❌ **No auto-completion**: System never fills in missing information without user input

## Integration Pattern 1: Direct Forwarding (Recommended for Middleware)

### Overview
The **`POST /refinement/queries/{query_id}/forward-to-qa`** endpoint forwards the completed refined query directly to your external QA system after the entire refinement process completes (with user clarifications for all dimensions).

### When to Use
- ✅ You want seamless middleware integration
- ✅ You want both refined query + QA response in one call
- ✅ You're building a transparent query enhancement layer
- ✅ Your QA system has a standard REST API

### How It Works

```
1. User: "effects of aspirin"
   ↓
2. System: "What population?" (extracted: unclear)
   ↓
3. User: "adults over 65" ← USER CLARIFIES
   ↓
4. System: "What outcome?" (extracted: unclear)
   ↓
5. User: "stroke prevention" ← USER CLARIFIES
   ↓
6. System: "Any comparison?" (extracted: unclear)
   ↓
7. User: "placebo" ← USER CLARIFIES
   ↓
8. System: Synthesizes → "aspirin vs placebo for stroke prevention in adults over 65"
   ↓
9. POST /queries/{query_id}/forward-to-qa ← FORWARD TO YOUR QA SYSTEM
   ↓
10. Your QA System: Returns answer
   ↓
11. User: Receives refined query + QA answer
```

### API Endpoint

**POST `/refinement/queries/{query_id}/forward-to-qa`**

**Prerequisites:**
- Query refinement must be complete (synthesis done)
- User must be authenticated
- Query must belong to the user

**Request:**
```json
{
  "qa_system_url": "https://your-qa-system.com/api/query",
  "qa_system_auth": {
    "Authorization": "Bearer your-qa-token",
    "X-API-Key": "your-api-key"
  },
  "timeout_seconds": 30,
  "include_refinement_metadata": true,
  "forward_original_query": false
}
```

**Response:**
```json
{
  "query_id": 123,
  "refined_query": "aspirin vs placebo for stroke prevention in adults over 65",
  "original_query": "effects of aspirin",
  "qa_system_url": "https://your-qa-system.com/api/query",
  "qa_system_response": {
    "answer": "Studies show aspirin reduces stroke risk by 20-30% in adults over 65...",
    "sources": [
      {"title": "NEJM Study 2022", "url": "..."},
      {"title": "Lancet Meta-analysis", "url": "..."}
    ],
    "confidence": 0.95
  },
  "qa_system_status_code": 200,
  "response_time_ms": 1250,
  "refinement_metadata": {
    "framework": "pico_advanced",
    "total_steps": 4,
    "dimensions_refined": ["population", "intervention", "comparison", "outcome"],
    "query_id": 123
  }
}
```

### Error Responses

**400 Bad Request** - Refinement not complete:
```json
{
  "detail": "Query refinement is not complete. Please complete the synthesis step first."
}
```

**502 Bad Gateway** - QA system connection failed:
```json
{
  "detail": "Failed to connect to QA system: Connection refused"
}
```

**504 Gateway Timeout** - QA system timed out:
```json
{
  "detail": "QA system did not respond within 30 seconds"
}
```

### Complete Integration Example

```python
import requests

# Configuration
REFINEMENT_API = "http://localhost:8000"
QA_SYSTEM_URL = "https://your-qa-system.com/api/query"
AUTH_TOKEN = "your-auth-token"

def refine_and_query(user_query: str, framework: str = "pico_advanced"):
    """
    Complete refinement workflow with QA system integration.
    """
    headers = {"Authorization": f"Bearer {AUTH_TOKEN}"}
    
    # 1. Start refinement
    response = requests.post(
        f"{REFINEMENT_API}/refinement/start",
        json={"original_query": user_query, "framework_name": framework},
        headers=headers
    )
    session_id = response.json()["session_id"]
    query_id = response.json()["query_id"]
    
    # 2. User goes through multi-turn refinement
    # (Your frontend handles this - asking questions, getting user answers)
    while not is_refinement_complete(query_id):
        # Get next question
        status = requests.get(
            f"{REFINEMENT_API}/refinement/status/{query_id}",
            headers=headers
        ).json()
        
        # Show question to user, get answer
        user_answer = get_user_answer(status["current_question"])
        
        # Submit answer
        requests.post(
            f"{REFINEMENT_API}/refinement/submit-answer",
            json={"query_id": query_id, "answer": user_answer},
            headers=headers
        )
    
    # 3. Synthesis (final refinement)
    requests.post(
        f"{REFINEMENT_API}/refinement/synthesize",
        json={"query_id": query_id},
        headers=headers
    )
    
    # 4. Forward to QA system (NEW ENDPOINT)
    response = requests.post(
        f"{REFINEMENT_API}/refinement/queries/{query_id}/forward-to-qa",
        json={
            "qa_system_url": QA_SYSTEM_URL,
            "qa_system_auth": {"Authorization": "Bearer qa-token"},
            "include_refinement_metadata": True
        },
        headers=headers
    )
    
    result = response.json()
    return {
        "refined_query": result["refined_query"],
        "qa_answer": result["qa_system_response"],
        "metadata": result["refinement_metadata"]
    }

# Usage
result = refine_and_query("effects of aspirin")
print(f"Refined: {result['refined_query']}")
print(f"Answer: {result['qa_answer']['answer']}")
```

### Webhook Event

When forwarding completes, the system triggers a **`query.forwarded`** webhook event:

```json
{
  "event": "query.forwarded",
  "data": {
    "query_id": 123,
    "refined_query": "aspirin vs placebo for stroke prevention...",
    "qa_system_url": "https://your-qa-system.com/api/query",
    "qa_status_code": 200,
    "response_time_ms": 1250
  },
  "webhook_id": 456,
  "timestamp": "2026-02-11T10:30:00Z"
}
```

### QA System Requirements

Your QA system should accept:

```json
POST /api/query
{
  "query": "refined query string",
  "original_query": "original query string (optional)",
  "refinement_metadata": {
    "framework": "pico_advanced",
    "dimensions_refined": ["population", "intervention", ...]
  }
}
```

And return:
```json
{
  "answer": "Your answer text",
  "sources": [...],
  "confidence": 0.95
}
```

---

## Integration Pattern 2: Webhook-Based

### How It Works
1. User submits query to your app
2. Your app calls refinement API to start refinement
3. User goes through refinement dialogue
4. When synthesis completes, webhook notifies your Q&A system
5. Your Q&A system receives refined query and processes it

### Setup

**1. Register Webhook in Your System:**
```bash
curl -X POST http://your-refinement-api/api/webhooks \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "url": "https://your-qa-system.com/api/refined-query-webhook",
    "events": ["synthesis.complete"],
    "name": "Q&A System Integration",
    "max_retries": 3,
    "timeout_seconds": 30
  }'
```

**2. Implement Webhook Receiver in Your Q&A System:**
```python
from flask import Flask, request
import hmac
import hashlib

app = Flask(__name__)

@app.route('/api/refined-query-webhook', methods=['POST'])
def handle_refined_query():
    # Verify webhook signature
    signature = request.headers.get('X-Webhook-Signature', '')
    payload = request.get_data()
    
    expected = 'sha256=' + hmac.new(
        WEBHOOK_SECRET.encode(), 
        payload, 
        hashlib.sha256
    ).hexdigest()
    
    if not hmac.compare_digest(signature, expected):
        return {'error': 'Invalid signature'}, 401
    
    # Process webhook
    data = request.json
    event_type = data['event']
    
    if event_type == 'synthesis.complete':
        refined_query = data['data']['refined_query']
        query_id = data['data']['query_id']
        
        # Send refined query to your Q&A system
        result = your_qa_system.answer_query(refined_query)
        
        return {'status': 'processed', 'result': result}
    
    return {'status': 'ignored'}
```

**Available Webhook Events:**
- `synthesis.started` - Synthesis begins
- `synthesis.complete` - Refined query ready
- `refinement.started` - User starts refinement
- `refinement.step_completed` - Each aspect completed
- `refinement.complete` - All aspects refined (before synthesis)

## Integration Pattern 2: Polling-Based

### How It Works
Your system polls the refinement API to check if synthesis is complete.

```python
import time
import requests

def wait_for_refinement(query_id, api_base_url, token):
    """Poll until refinement is complete."""
    headers = {'Authorization': f'Bearer {token}'}
    
    while True:
        response = requests.get(
            f'{api_base_url}/api/queries/{query_id}',
            headers=headers
        )
        query = response.json()
        
        if query['refined_query']:
            return query['refined_query']
        
        time.sleep(5)  # Poll every 5 seconds
```

## Integration Pattern 3: Direct API Call (Synchronous)

### New API Endpoint Needed
⚠️ **Currently Missing** - You would need to add this endpoint:

```python
@router.post("/refine-and-forward")
async def refine_and_forward(
    request: RefineAndForwardRequest,
    current_user = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Complete refinement workflow and forward to external system.
    
    This is a blocking operation that:
    1. Starts refinement
    2. Waits for user to complete dialogue
    3. Triggers synthesis
    4. Forwards refined query to external_callback_url
    5. Returns final result
    """
    # Implementation needed
    pass
```

## Docker Container Setup for Middleware Use

### docker-compose.yml for Middleware Deployment

```yaml
version: '3.8'

services:
  refinement-middleware:
    image: query-refinement-api:latest
    container_name: refinement-middleware
    environment:
      # Database
      DATABASE_URL: postgresql://user:pass@postgres:5432/refinement
      
      # Redis for sessions
      REDIS_URL: redis://redis:6379/0
      
      # LLM Configuration
      QUERY_REFINEMENT_LLM_MODEL: anthropic/claude-sonnet-4
      QUERY_REFINEMENT_LLM_API_KEY: ${LLM_API_KEY}
      
      # Concurrency settings for middleware use
      WORKERS: 8  # Increase for higher throughput
      LLM_MAX_CONCURRENT: 100  # Allow more concurrent LLM calls
      DB_POOL_SIZE: 20  # Larger connection pool
      DB_MAX_OVERFLOW: 40
      
      # Rate limiting
      LLM_RATE_LIMIT_RPM: 200
      
    ports:
      - "8000:8000"
    networks:
      - qa-network
    depends_on:
      - postgres
      - redis

  # Your Q&A system
  qa-system:
    image: your-qa-system:latest
    environment:
      REFINEMENT_API_URL: http://refinement-middleware:8000
    networks:
      - qa-network

networks:
  qa-network:
    driver: bridge
```

## API Endpoints for Middleware Integration

### Essential Endpoints You Have:

**1. Start Refinement**
```http
POST /api/refinement/start
Content-Type: application/json
Authorization: Bearer {token}

{
  "original_query": "effects of aspirin on stroke",
  "framework_name": "pico"
}
```

**2. Submit User Answers**
```http
POST /api/refinement/{query_id}/submit
Content-Type: application/json

{
  "answer": "hemorrhagic stroke prevention"
}
```

**3. Synthesize Refined Query**
```http
POST /api/refinement/synthesize
Content-Type: application/json

{
  "query_id": 123
}
```

**4. Get Refined Query**
```http
GET /api/queries/{query_id}
```

### Missing Endpoints for Better Middleware Integration

**❌ 1. Batch Refinement API** (for processing multiple queries)
```http
POST /api/refinement/batch
Content-Type: application/json

{
  "queries": [
    {"query": "...", "framework": "pico"},
    {"query": "...", "framework": "pico"}
  ]
}
```

**❌ 2. Forward API** (refine and forward to external system)
```http
POST /api/refinement/refine-and-forward
Content-Type: application/json

{
  "query": "effects of aspirin",
  "framework": "pico",
  "forward_to": "https://your-qa-system/api/answer",
  "forward_method": "POST",
  "forward_headers": {"X-API-Key": "..."}
}
```

**❌ 3. Streaming API** (SSE for real-time updates)
```http
GET /api/refinement/{query_id}/stream
Accept: text/event-stream
```

**❌ 4. Status Check API** (non-blocking status)
```http
GET /api/refinement/{query_id}/status

Response:
{
  "status": "in_progress",  // or "complete", "waiting_user", "error"
  "progress": 0.6,
  "current_step": "Outcome",
  "refined_query": null  // or refined query if complete
}
```

## Recommended Implementation Plan

### Phase 1: Use Existing Webhook System
- ✅ Already implemented
- Register webhook for `synthesis.complete` event
- Your Q&A system receives refined queries automatically

### Phase 2: Add Status Check API (High Priority)
- Enables polling without loading full query object
- Better for middleware integration
- Non-blocking status checks

### Phase 3: Add Forward API (Medium Priority)
- Direct integration pattern
- Refinement module forwards to your Q&A system
- Reduces integration complexity

### Phase 4: Add Streaming API (Low Priority)
- Real-time updates during refinement
- Better UX for long refinements
- Optional enhancement

## Code Changes Needed for Full Middleware Support

### 1. Add Status Check Endpoint

```python
# In query_refinement_module/api/routes/refinement.py

@router.get("/{query_id}/status", response_model=RefinementStatusResponse)
async def get_refinement_status(
    query_id: int,
    current_user = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get lightweight status of refinement without loading full data."""
    query = get_query(db, query_id)
    if not query:
        raise HTTPException(404, "Query not found")
    
    # Check ownership
    session = get_query_session(db, query.session_id)
    if session.user_id != current_user.id:
        raise HTTPException(403, "Access denied")
    
    steps = get_query_refinement_steps(db, query_id)
    total_steps = len(steps)
    completed_steps = len([s for s in steps if s.is_complete])
    
    return {
        "status": "complete" if query.refined_query else "in_progress",
        "progress": completed_steps / total_steps if total_steps > 0 else 0,
        "total_steps": total_steps,
        "completed_steps": completed_steps,
        "refined_query": query.refined_query  # Only if complete
    }
```

### 2. Add Forward API Endpoint

```python
@router.post("/refine-and-forward", response_model=ForwardResponse)
async def refine_and_forward(
    request: RefineAndForwardRequest,
    background_tasks: BackgroundTasks,
    current_user = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Start refinement and register a forward action on completion.
    
    This creates a special webhook that forwards to your system
    and optionally returns the external system's response.
    """
    # Start refinement (existing logic)
    # ...
    
    # Register one-time webhook for forwarding
    webhook = create_webhook(
        db,
        user_id=current_user.id,
        url=request.forward_to,
        events=["synthesis.complete"],
        name=f"Forward for query {query_id}",
        is_one_time=True  # New field: auto-delete after first delivery
    )
    
    return {
        "query_id": query_id,
        "status": "refinement_started",
        "message": "Will forward to your system when refinement completes"
    }
```

## Production Deployment Checklist

- [ ] Set `WORKERS` to appropriate value (8-16 for middleware use)
- [ ] Increase `LLM_MAX_CONCURRENT` (50-100)
- [ ] Configure larger DB connection pool
- [ ] Set up webhook endpoints in your Q&A system
- [ ] Implement webhook signature verification
- [ ] Configure CORS for your Q&A system domain
- [ ] Set up monitoring for webhook delivery failures
- [ ] Implement retry logic in your Q&A system
- [ ] Load test with concurrent requests
- [ ] Set up logging aggregation

## Testing Your Middleware Integration

```bash
# 1. Start refinement
QUERY_ID=$(curl -X POST http://localhost:8000/api/refinement/start \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"original_query":"test query","framework_name":"pico"}' \
  | jq -r '.query_id')

# 2. Check status (if you implement status endpoint)
curl http://localhost:8000/api/refinement/$QUERY_ID/status \
  -H "Authorization: Bearer $TOKEN"

# 3. Complete refinement (simulate user)
# ... submit answers ...

# 4. Trigger synthesis
curl -X POST http://localhost:8000/api/refinement/synthesize \
  -H "Authorization: Bearer $TOKEN" \
  -d "{\"query_id\":$QUERY_ID}"

# 5. Your webhook should be called automatically
```

## Conclusion

**Current State:**
- ✅ Webhook system is complete and production-ready
- ✅ Docker containerization works for middleware deployment
- ✅ Basic API for refinement workflow exists

**Recommended Additions:**
1. **Status Check API** (high priority for polling integrations)
2. **Forward API** (medium priority for simpler integration)
3. **Batch API** (if you need to process multiple queries)
4. **Streaming API** (optional, for real-time UX)

**Bottom Line:** Your system is **80% ready** for middleware use. The webhook system alone is sufficient for most integrations. The additional APIs would make integration easier but aren't strictly necessary.
