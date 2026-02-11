# Circuit Breaker Implementation

## Overview

The query refinement system now includes a **circuit breaker pattern** for LLM API calls to protect against cascading failures and reduce costs during provider outages.

### Why Circuit Breaker?

Without circuit breaker:
```
LLM provider down → 100 concurrent users × 3 retries × 30s timeout
= 9000 seconds of wasted API calls + blocked workers + $$$
```

With circuit breaker:
```
LLM provider down → Circuit opens after 5 failures
→ All subsequent calls fail fast (< 1ms)
→ Automatic recovery testing after 60s
```

---

## Features

### 1. **Per-Provider Tracking**
- Separate circuit breakers for each LLM provider (OpenAI, Anthropic, Google, etc.)
- One provider down ≠ all providers down
- Automatic provider detection from model name

### 2. **Smart Failure Detection**
- **Counts:** Timeouts, connection errors, 5xx errors
- **Ignores:** Rate limit errors (temporary throttling, not outages)
- **Windowed:** Only failures in last 5 minutes count

### 3. **Three States**
- **CLOSED** (Normal): All requests allowed
- **OPEN** (Failing): Requests blocked, fail fast
- **HALF_OPEN** (Testing): Trying recovery, limited requests

### 4. **Automatic Recovery**
- After 60s (configurable), circuit enters HALF_OPEN
- Makes test request to check if provider recovered
- Closes after 2 successful requests
- Reopens immediately on any failure

---

## Configuration

### Environment Variables

```bash
# Enable/disable circuit breaker (default: true)
QUERY_REFINEMENT_ENABLE_CIRCUIT_BREAKER=true

# Number of failures before opening circuit (default: 5)
QUERY_REFINEMENT_CIRCUIT_BREAKER_FAILURE_THRESHOLD=5

# Seconds to wait before testing recovery (default: 60)
QUERY_REFINEMENT_CIRCUIT_BREAKER_RECOVERY_TIMEOUT=60
```

### Programmatic Configuration

```python
from query_refinement_module.providers import LiteLLMProvider, CircuitBreakerConfig

# Custom circuit breaker settings
config = CircuitBreakerConfig(
    failure_threshold=10,        # Open after 10 failures
    recovery_timeout=120.0,      # Wait 2 minutes before testing
    success_threshold=3,         # Need 3 successes to close
    failure_window=600.0,        # Count failures in last 10 minutes
)

provider = LiteLLMProvider(
    default_model="gpt-4",
    enable_circuit_breaker=True,
    circuit_breaker_config=config
)
```

---

## Monitoring

### API Endpoints

#### GET /api/v1/monitoring/circuit-breakers

Get circuit breaker status for all providers.

**Response:**
```json
{
  "circuit_breaker_enabled": true,
  "providers": {
    "openai": {
      "state": "closed",
      "failure_count": 0,
      "success_count": 45,
      "last_success_time": "2026-02-11T10:15:30Z",
      "last_failure_time": null,
      "total_calls": 45,
      "rejected_calls": 0
    },
    "anthropic": {
      "state": "open",
      "failure_count": 5,
      "success_count": 0,
      "last_failure_time": "2026-02-11T10:14:00Z",
      "opened_at": "2026-02-11T10:14:00Z",
      "total_calls": 25,
      "rejected_calls": 20
    }
  }
}
```

#### GET /api/v1/monitoring/llm-health

Get overall LLM health summary.

**Response:**
```json
{
  "status": "degraded",
  "message": "Circuit breaker OPEN for: anthropic",
  "circuit_breakers": { /* full status */ },
  "timestamp": null
}
```

**Status values:**
- `healthy` - All providers operational
- `recovering` - Testing recovery (HALF_OPEN)
- `degraded` - One or more circuits OPEN
- `unknown` - Health check failed

---

## Usage Examples

### Check Circuit Breaker Status

```python
from query_refinement_module.api.dependencies import get_llm_provider

provider = get_llm_provider()
metrics = provider.get_circuit_breaker_metrics()

if metrics.get("circuit_breaker_enabled"):
    for provider_name, status in metrics["providers"].items():
        print(f"{provider_name}: {status['state']}")
```

### Monitoring with Alerts

```python
import requests

response = requests.get("http://localhost:8000/api/v1/monitoring/llm-health")
health = response.json()

if health["status"] == "degraded":
    # Send alert to Slack/PagerDuty
    send_alert(f"LLM provider degraded: {health['message']}")
```

### Circuit Breaker Behavior

```python
from query_refinement_module.providers import LiteLLMProvider
from query_refinement_module.providers.circuit_breaker import CircuitBreakerOpen

provider = LiteLLMProvider(
    default_model="gpt-4",
    enable_circuit_breaker=True
)

try:
    result = await provider.complete_async(
        user_prompt="Explain quantum computing",
        system_prompt="You are a helpful assistant."
    )
    print(f"Success: {result.context}")
except CircuitBreakerOpen as e:
    print(f"Circuit breaker open: {e}")
    # Handle gracefully - maybe use cached response or show user message
except Exception as e:
    print(f"Other error: {e}")
```

---

## Architecture

### State Machine

```
CLOSED ──(5 failures)──> OPEN ──(60s wait)──> HALF_OPEN
  ↑                                                │
  └────────(2 successes)──────────────────────────┘
  
HALF_OPEN ──(1 failure)──> OPEN
```

### Per-Provider Isolation

```python
# OpenAI circuit breaker
openai_cb = circuit_breaker_registry.get_breaker("openai")

# Anthropic circuit breaker (independent)
anthropic_cb = circuit_breaker_registry.get_breaker("anthropic")

# If OpenAI down, Anthropic still works
```

### Provider Detection

Model names are automatically mapped to providers:

| Model Pattern | Provider |
|--------------|----------|
| `gpt-*`, `o1-*` | openai |
| `claude-*` | anthropic |
| `gemini-*`, `palm-*` | google |
| `llama-*` | meta |
| `mistral-*`, `mixtral-*` | mistral |
| `command-*` | cohere |
| `bedrock/*` | aws-bedrock |
| `azure/*` | azure |

---

## Cost Savings

### Without Circuit Breaker (Outage Scenario)

```
Provider outage duration: 5 minutes
Concurrent users: 50
Retry attempts per user: 3
Timeout per attempt: 30s

Wasted time: 50 users × 3 retries × 30s = 4500 seconds
Worker threads blocked: 50 (can't serve other requests)
API calls made: 50 × 3 = 150 failed calls (still charged)
```

### With Circuit Breaker

```
Provider outage duration: 5 minutes
Failures before circuit opens: 5
Time to detect and open: ~5 seconds
Subsequent requests: Fail fast (< 1ms)

Wasted time: 5 calls × 30s = 150 seconds
Worker threads blocked: Never (fail fast)
API calls made: 5 (circuit opens, rest rejected)
Cost savings: 97% fewer failed API calls
```

---

## Production Deployment

### Docker Environment Variables

```yaml
# docker-compose.yml
services:
  api:
    environment:
      # LLM settings
      QUERY_REFINEMENT_LLM_MODEL: "gpt-4"
      QUERY_REFINEMENT_LLM_API_KEY: "${OPENAI_API_KEY}"
      
      # Circuit breaker (enabled by default)
      QUERY_REFINEMENT_ENABLE_CIRCUIT_BREAKER: "true"
      QUERY_REFINEMENT_CIRCUIT_BREAKER_FAILURE_THRESHOLD: "5"
      QUERY_REFINEMENT_CIRCUIT_BREAKER_RECOVERY_TIMEOUT: "60"
```

### Kubernetes Health Checks

```yaml
livenessProbe:
  httpGet:
    path: /health
    port: 8000
  initialDelaySeconds: 10
  periodSeconds: 30

readinessProbe:
  httpGet:
    path: /api/v1/monitoring/llm-health
    port: 8000
  initialDelaySeconds: 5
  periodSeconds: 10
  # Pod marked not ready if circuit breaker open
```

### Monitoring Setup

#### Prometheus Metrics (Future Enhancement)

```python
# Query circuit breaker metrics
circuit_breaker_state{provider="openai"} 0  # 0=closed, 1=half_open, 2=open
circuit_breaker_failures_total{provider="openai"} 45
circuit_breaker_rejected_calls_total{provider="openai"} 120
```

#### Current Monitoring

Use the monitoring endpoints with your observability stack:

```bash
# Check status every 30 seconds
*/30 * * * * curl -s http://localhost:8000/api/v1/monitoring/llm-health | \
  jq '.status' | \
  grep -v "healthy" && \
  send-alert "LLM health degraded"
```

---

## Troubleshooting

### Circuit Keeps Opening

**Symptoms:** Circuit breaker frequently opens for a provider

**Possible causes:**
1. Provider genuinely having issues
2. Timeout too aggressive (increase timeout)
3. Failure threshold too low (increase threshold)
4. Network issues between your server and provider

**Solution:**
```bash
# Increase failure threshold
QUERY_REFINEMENT_CIRCUIT_BREAKER_FAILURE_THRESHOLD=10

# Increase recovery timeout (wait longer before testing)
QUERY_REFINEMENT_CIRCUIT_BREAKER_RECOVERY_TIMEOUT=120
```

### Circuit Never Opens

**Symptoms:** Provider is down but circuit stays closed

**Possible causes:**
1. Circuit breaker disabled
2. Failures not being counted (rate limit errors don't count)
3. Failure window too narrow (old failures aging out)

**Solution:**
```bash
# Ensure enabled
QUERY_REFINEMENT_ENABLE_CIRCUIT_BREAKER=true

# Check if failures are being counted
curl http://localhost:8000/api/v1/monitoring/circuit-breakers | jq '.providers'
```

### False Positives

**Symptoms:** Circuit opens but provider is actually fine

**Possible causes:**
1. Transient network issues
2. Your server under heavy load
3. Failure threshold too low

**Solution:**
```bash
# Increase failure threshold
QUERY_REFINEMENT_CIRCUIT_BREAKER_FAILURE_THRESHOLD=8

# Widen failure window (require more consistent failures)
# (requires code change to CircuitBreakerConfig)
```

---

## Testing

### Manual Testing

```bash
# 1. Start the API
poetry run uvicorn query_refinement_module.api.main:app --reload

# 2. Check initial status (should be healthy)
curl http://localhost:8000/api/v1/monitoring/circuit-breakers

# 3. Make some successful requests
curl -X POST http://localhost:8000/api/v1/refinement/start \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"query": "test query", "framework_name": "pico_advanced"}'

# 4. Simulate provider failure (set invalid API key)
export QUERY_REFINEMENT_LLM_API_KEY="invalid-key"

# 5. Make 5 requests (circuit should open)
for i in {1..5}; do
  curl -X POST http://localhost:8000/api/v1/refinement/start \
    -H "Authorization: Bearer $TOKEN" \
    -H "Content-Type: application/json" \
    -d '{"query": "test query", "framework_name": "pico_advanced"}'
done

# 6. Check status (should show circuit OPEN)
curl http://localhost:8000/api/v1/monitoring/circuit-breakers
```

### Automated Tests

```bash
# Run circuit breaker tests
poetry run pytest tests/test_circuit_breaker.py -v

# Run integration tests
poetry run pytest tests/integration/ -k circuit -v
```

---

## Best Practices

### 1. **Monitor Circuit Breaker State**
- Set up alerts for when circuits open
- Track how often circuits open/close
- Investigate patterns in circuit breaker activity

### 2. **Tune Thresholds for Your Workload**
- High-traffic: Higher thresholds (10-15 failures)
- Low-traffic: Lower thresholds (3-5 failures)
- Critical systems: Longer recovery timeouts (2-5 minutes)

### 3. **Handle Circuit Breaker Errors Gracefully**
```python
try:
    result = await provider.complete_async(...)
except CircuitBreakerOpen:
    # Option 1: Use cached response
    result = get_cached_response(query)
    
    # Option 2: Show user-friendly message
    return {
        "error": "LLM service temporarily unavailable. Please try again in 1 minute.",
        "retry_after": 60
    }
    
    # Option 3: Fallback to simpler model
    result = await fallback_provider.complete_async(...)
```

### 4. **Log Circuit Breaker Events**
All circuit breaker state changes are automatically logged:
```
INFO: Circuit breaker OPENED for openai
INFO: Circuit breaker HALF-OPEN for openai (testing recovery)
INFO: Circuit breaker CLOSED for openai (service recovered)
```

### 5. **Test in Staging First**
- Simulate provider outages in staging
- Verify circuit breaker opens and closes correctly
- Measure impact on user experience
- Adjust thresholds before production deployment

---

## Future Enhancements

### Planned Features
- [ ] Prometheus metrics export
- [ ] Grafana dashboard template
- [ ] Adaptive thresholds (ML-based)
- [ ] Circuit breaker events webhook
- [ ] Per-endpoint circuit breakers
- [ ] Fallback provider chains

### Contribute
Have ideas for improving the circuit breaker? Open an issue or PR!

---

## References

- [Circuit Breaker Pattern](https://martinfowler.com/bliki/CircuitBreaker.html) - Martin Fowler
- [Release It!](https://pragprog.com/titles/mnee2/release-it-second-edition/) - Michael Nygard
- [Resilience Engineering](https://www.oreilly.com/library/view/site-reliability-engineering/9781491929117/)

---

## Support

Having issues with circuit breaker? Check:
1. This documentation
2. [Troubleshooting section](#troubleshooting)
3. Monitoring endpoints for real-time status
4. Application logs for circuit breaker events

Still stuck? Open an issue with:
- Circuit breaker metrics (from monitoring endpoint)
- Relevant log entries
- Your configuration (environment variables)
