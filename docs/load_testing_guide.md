# Load Testing Guide

## Overview

This guide covers load testing the Query Refinement API to validate performance under concurrent user load. The goal is to support **100 concurrent users** with acceptable response times and error rates.

## Table of Contents

1. [Prerequisites](#prerequisites)
2. [Test Environment Setup](#test-environment-setup)
3. [Running Load Tests](#running-load-tests)
4. [Test Scenarios](#test-scenarios)
5. [Interpreting Results](#interpreting-results)
6. [Performance Targets](#performance-targets)
7. [Troubleshooting](#troubleshooting)

---

## Prerequisites

### Software

- Locust (installed via `poetry add --group dev locust`)
- Docker and Docker Compose (for production-like environment)
- PostgreSQL and Redis (via Docker or local installation)

### Files

- `tests/load/locustfile.py` - Load test scenarios
- `scripts/generate_test_data.py` - Test data generator
- `scripts/monitor_performance.py` - Performance monitoring
- `.env.loadtest` - Load test configuration

---

## Test Environment Setup

### 1. Generate Test Data

Create test users and API keys:

```bash
# Generate 20 test users with 2 API keys each
poetry run python scripts/generate_test_data.py --users 20 --keys-per-user 2

# Clean existing test data first
poetry run python scripts/generate_test_data.py --clean --users 20

# Export test data to file
poetry run python scripts/generate_test_data.py --users 50 --export test_data.json
```

This creates:
- Test users in the database
- API keys for authentication
- `.env.loadtest` file with the first API key

### 2. Configure Environment

Copy the load test environment file:

```bash
cp .env.loadtest .env
```

**Key settings to verify**:
```bash
# Database pool (for 100 users)
DB_POOL_SIZE=20
DB_POOL_MAX_OVERFLOW=40

# Gunicorn workers
WORKERS=9  # (2 × CPU cores) + 1

# Rate limits (relaxed for testing)
RATE_LIMIT_REQUESTS_PER_MINUTE=1000
RATE_LIMIT_PER_USER_REQUESTS_PER_MINUTE=500

# Logging
LOG_FORMAT=json
LOG_LEVEL=INFO
```

### 3. Start Services

#### Option A: Docker Compose (Recommended)

```bash
# Start all services
docker-compose up -d

# Check status
docker-compose ps

# View logs
docker-compose logs -f api
```

#### Option B: Local Services

```bash
# Start PostgreSQL
docker run -d --name postgres \
  -e POSTGRES_USER=queryrefine \
  -e POSTGRES_PASSWORD=password \
  -e POSTGRES_DB=query_refinement_loadtest \
  -p 5432:5432 postgres:16-alpine

# Start Redis
docker run -d --name redis \
  -p 6379:6379 redis:7-alpine

# Start API
poetry run bash start_production.sh
```

### 4. Verify Setup

```bash
# Health check
curl http://localhost:8000/health

# Readiness check
curl http://localhost:8000/ready

# Test authentication
curl -H "X-API-Key: YOUR_API_KEY" http://localhost:8000/sessions
```

---

## Running Load Tests

### Basic Load Tests

#### 1. Interactive Mode (Web UI)

```bash
# Start Locust web interface
poetry run locust -f tests/load/locustfile.py --host=http://localhost:8000

# Open browser to http://localhost:8089
# Configure:
#   - Number of users: 100
#   - Spawn rate: 10 users/second
#   - Host: http://localhost:8000
# Click "Start swarming"
```

#### 2. Headless Mode (Command Line)

```bash
# 10 users for 2 minutes
poetry run locust -f tests/load/locustfile.py \
  --host=http://localhost:8000 \
  --users 10 \
  --spawn-rate 2 \
  --run-time 2m \
  --headless

# 100 users for 10 minutes
poetry run locust -f tests/load/locustfile.py \
  --host=http://localhost:8000 \
  --users 100 \
  --spawn-rate 10 \
  --run-time 10m \
  --headless

# Generate HTML report
poetry run locust -f tests/load/locustfile.py \
  --host=http://localhost:8000 \
  --users 100 \
  --spawn-rate 10 \
  --run-time 10m \
  --headless \
  --html report.html \
  --csv results
```

### Progressive Load Tests

Test with increasing user counts to find performance limits:

```bash
# Phase 1: 10 users (baseline)
poetry run locust -f tests/load/locustfile.py \
  --host=http://localhost:8000 \
  --users 10 --spawn-rate 2 --run-time 5m --headless \
  --html reports/10_users.html

# Phase 2: 25 users
poetry run locust -f tests/load/locustfile.py \
  --host=http://localhost:8000 \
  --users 25 --spawn-rate 5 --run-time 5m --headless \
  --html reports/25_users.html

# Phase 3: 50 users
poetry run locust -f tests/load/locustfile.py \
  --host=http://localhost:8000 \
  --users 50 --spawn-rate 10 --run-time 5m --headless \
  --html reports/50_users.html

# Phase 4: 100 users (target)
poetry run locust -f tests/load/locustfile.py \
  --host=http://localhost:8000 \
  --users 100 --spawn-rate 10 --run-time 10m --headless \
  --html reports/100_users.html

# Phase 5: 150 users (stress test)
poetry run locust -f tests/load/locustfile.py \
  --host=http://localhost:8000 \
  --users 150 --spawn-rate 15 --run-time 5m --headless \
  --html reports/150_users.html
```

### Advanced Load Patterns

#### Step Load Pattern

Gradually increase load in steps:

```bash
poetry run locust -f tests/load/locustfile.py \
  --host=http://localhost:8000 \
  StepLoadShape --headless

# Pattern:
# 0-60s: 10 users
# 60-120s: 25 users
# 120-180s: 50 users
# 180-300s: 100 users
```

#### Wave Load Pattern

Simulate varying traffic:

```bash
poetry run locust -f tests/load/locustfile.py \
  --host=http://localhost:8000 \
  WaveLoadShape --headless
```

---

## Test Scenarios

### 1. SingleStepUser (Weight: 3)

**Behavior**: Quick single-step refinements
- Create session
- Perform one refinement
- Retrieve session data

**Use case**: Users exploring queries quickly

### 2. MultiStepUser (Weight: 2)

**Behavior**: Multi-step refinement workflows
- Create initial refinement
- Submit 3-5 followup refinements
- Review session history

**Use case**: Users doing deep query refinement

### 3. ParallelUser (Weight: 1)

**Behavior**: Uses parallel processing
- Create refinement with parallel enabled
- Wait for subdimension processing
- Retrieve results with metadata

**Use case**: Users leveraging advanced features

### 4. MonitoringUser (Weight: 1)

**Behavior**: Health check monitoring
- Frequent `/health` checks
- Periodic `/ready` checks

**Use case**: Load balancer health checks

### 5. MixedUser (Weight: 5) - **Most Realistic**

**Behavior**: Combination of all behaviors
- Mix of single and multi-step
- Occasional parallel processing
- Health checks

**Use case**: Real-world user behavior

### Running Specific Scenarios

```bash
# Only single-step users
poetry run locust -f tests/load/locustfile.py \
  --host=http://localhost:8000 \
  --users 50 SingleStepUser

# Only multi-step users
poetry run locust -f tests/load/locustfile.py \
  --host=http://localhost:8000 \
  --users 30 MultiStepUser

# Only parallel processing users
poetry run locust -f tests/load/locustfile.py \
  --host=http://localhost:8000 \
  --users 20 ParallelUser
```

---

## Monitoring During Tests

### Real-Time Performance Dashboard

In a separate terminal, run the monitoring script:

```bash
# Monitor with default settings
poetry run python scripts/monitor_performance.py

# Monitor with custom interval and output
poetry run python scripts/monitor_performance.py \
  --interval 10 \
  --output metrics.json

# Monitor for specific duration
poetry run python scripts/monitor_performance.py \
  --duration 600  # 10 minutes
```

**Dashboard shows**:
- Response times (current, average)
- Error rate
- System resources (CPU, memory)
- Health status
- Dependency checks

### Database Pool Monitoring

Check PostgreSQL connection pool status:

```bash
# View pool size and checked out connections
docker-compose logs api | grep "pool"

# Connect to database
docker-compose exec postgres psql -U queryrefine query_refinement

# Check active connections
SELECT count(*) FROM pg_stat_activity WHERE datname = 'query_refinement';

# View connection details
SELECT pid, usename, application_name, state, query_start
FROM pg_stat_activity
WHERE datname = 'query_refinement';
```

### Redis Monitoring

```bash
# Connect to Redis
docker-compose exec redis redis-cli

# Get info
INFO

# Monitor commands in real-time
MONITOR

# Check memory usage
INFO memory

# Count keys by prefix
KEYS session:*
KEYS ratelimit:*
```

### System Resource Monitoring

```bash
# CPU and memory
docker stats

# Detailed system metrics
htop

# Disk I/O
iostat -x 5

# Network traffic
iftop
```

---

## Interpreting Results

### Locust Web UI Metrics

**Statistics Tab**:
- **Requests**: Total requests per endpoint
- **Fails**: Failed requests
- **Median**: 50th percentile response time
- **95%ile**: 95th percentile response time
- **Average**: Mean response time
- **RPS**: Requests per second

**Charts Tab**:
- **Total Requests per Second**: Throughput over time
- **Response Times**: Latency distribution
- **Number of Users**: User ramp-up

**Failures Tab**:
- Error types and counts
- Error messages

### HTML Report

Generated with `--html report.html`:

- Summary statistics
- Response time charts
- Error breakdown
- Download link for CSV data

### CSV Data

Generated with `--csv results`:

- `results_stats.csv`: Request statistics
- `results_stats_history.csv`: Time-series data
- `results_failures.csv`: Error details

### Analyzing Results

#### 1. Response Times

**Good**:
- Median < 1000ms
- 95th percentile < 2000ms
- 99th percentile < 3000ms

**Warning**:
- Median 1000-2000ms
- 95th percentile 2000-3000ms

**Critical**:
- Median > 2000ms
- 95th percentile > 3000ms
- Increasing over time

#### 2. Error Rate

**Good**: < 0.1%
**Acceptable**: 0.1% - 1%
**Warning**: 1% - 5%
**Critical**: > 5%

#### 3. Throughput

**Target**: 50+ requests/second for 100 users

**Calculation**:
```
Expected RPS = Users / Avg Think Time
Example: 100 users / 2s = 50 RPS
```

#### 4. System Resources

**Good**:
- CPU < 70%
- Memory < 70%
- No connection pool exhaustion

**Warning**:
- CPU 70-85%
- Memory 70-85%
- Connection pool near max

**Critical**:
- CPU > 85%
- Memory > 85%
- Connection pool exhausted

---

## Performance Targets

### Target Metrics (100 Concurrent Users)

| Metric               | Target   | Acceptable | Critical |
| -------------------- | -------- | ---------- | -------- |
| Median Response Time | < 500ms  | < 1000ms   | > 2000ms |
| 95th Percentile      | < 1500ms | < 2000ms   | > 3000ms |
| 99th Percentile      | < 2000ms | < 3000ms   | > 5000ms |
| Error Rate           | < 0.1%   | < 1%       | > 5%     |
| Throughput           | > 50 RPS | > 30 RPS   | < 20 RPS |
| CPU Usage            | < 70%    | < 85%      | > 90%    |
| Memory Usage         | < 70%    | < 85%      | > 90%    |
| DB Connections       | < 30     | < 50       | > 60     |

### Bottleneck Indicators

#### Database

- High response times for `/refine` endpoint
- Pool connection timeouts
- Many checked out connections
- Slow query log entries

**Solution**:
- Increase `DB_POOL_SIZE`
- Add database indexes
- Optimize query complexity

#### LLM API

- Timeouts on LLM calls
- High `LLM_TIMEOUT` occurrences
- Rate limit errors (429)

**Solution**:
- Increase `LLM_TIMEOUT`
- Use faster model (gpt-4o-mini)
- Implement request queuing
- Add caching layer

#### Redis

- Session creation/retrieval slow
- Rate limit checks slow
- Connection errors

**Solution**:
- Increase Redis memory
- Enable AOF persistence
- Use connection pooling
- Consider Redis Cluster

#### Application

- High CPU usage
- High memory usage
- Worker timeouts

**Solution**:
- Increase `WORKERS`
- Optimize code paths
- Add caching
- Scale horizontally

---

## Troubleshooting

### Connection Pool Exhausted

**Error**: `TimeoutError: QueuePool limit of size X overflow Y reached`

**Solutions**:
```bash
# Increase pool size
DB_POOL_SIZE=30
DB_POOL_MAX_OVERFLOW=60

# Reduce pool timeout
DB_POOL_TIMEOUT=10

# Enable pre-ping
DB_POOL_PRE_PING=true
```

### High Response Times

**Check**:
1. Database query performance
2. LLM API latency
3. Network latency
4. System resource saturation

**Debug**:
```bash
# Enable query logging
DB_ECHO=true
LOG_SQL_QUERIES=true

# Check logs
docker-compose logs api | grep "duration_ms"

# Profile specific endpoint
curl -w "@curl-format.txt" -H "X-API-Key: KEY" \
  http://localhost:8000/refine -d '{...}'
```

### Memory Leaks

**Symptom**: Memory usage increases over time

**Debug**:
```bash
# Monitor memory
docker stats

# Check for unclosed connections
# Add to database.py
@event.listens_for(engine.sync_engine, "checkin")
def receive_checkin(dbapi_conn, connection_record):
    logger.info("Connection returned to pool")

# Profile memory
poetry add --group dev memory_profiler
python -m memory_profiler scripts/profile_memory.py
```

### Rate Limit Errors

**Error**: 429 Too Many Requests

**Solutions**:
```bash
# Increase rate limits
RATE_LIMIT_REQUESTS_PER_MINUTE=2000
RATE_LIMIT_PER_USER_REQUESTS_PER_MINUTE=1000

# Or disable for testing
RATE_LIMIT_ENABLED=false
```

### Worker Timeouts

**Error**: Worker timeout (30s)

**Solutions**:
```bash
# Increase timeout
TIMEOUT=180

# Reduce max requests
MAX_REQUESTS=2000

# Add graceful timeout
GRACEFUL_TIMEOUT=60
```

---

## Best Practices

### 1. Baseline First

Always establish baseline performance before optimization:
```bash
# Run with minimal load
poetry run locust -f tests/load/locustfile.py \
  --users 1 --spawn-rate 1 --run-time 5m --headless
```

### 2. Progressive Loading

Increase load gradually to find breaking points:
```bash
10 → 25 → 50 → 100 → 150 → 200 users
```

### 3. Multiple Runs

Run each test at least 3 times for consistency:
```bash
for i in {1..3}; do
  poetry run locust -f tests/load/locustfile.py \
    --users 100 --spawn-rate 10 --run-time 10m --headless \
    --html reports/run_$i.html
done
```

### 4. Monitor Everything

Run monitoring during all tests:
```bash
# Terminal 1: API
docker-compose up

# Terminal 2: Monitoring
poetry run python scripts/monitor_performance.py --output metrics.json

# Terminal 3: Load test
poetry run locust -f tests/load/locustfile.py ...
```

### 5. Document Results

Save all outputs:
```bash
mkdir -p reports/$(date +%Y%m%d_%H%M%S)
cd reports/$(date +%Y%m%d_%H%M%S)

# Run tests with output
poetry run locust -f ../../tests/load/locustfile.py \
  --host=http://localhost:8000 \
  --users 100 --spawn-rate 10 --run-time 10m --headless \
  --html report.html --csv results

# Save configuration
cp ../../.env config.env

# Save system info
uname -a > system_info.txt
docker stats --no-stream > docker_stats.txt
```

### 6. Clean Between Runs

Reset state between test runs:
```bash
# Clear Redis
docker-compose exec redis redis-cli FLUSHALL

# Restart services
docker-compose restart

# Wait for readiness
curl http://localhost:8000/ready
```

---

## Next Steps

After completing load tests:

1. **Analyze Results**: Review metrics and identify bottlenecks
2. **Optimize Configuration**: Tune database pool, workers, caching
3. **Re-test**: Validate improvements with new load tests
4. **Document Findings**: Create comprehensive performance report
5. **Plan Scaling**: Determine infrastructure requirements for production

See [Production Deployment Guide](production_deployment.md) for scaling strategies.

---

**Last Updated**: 2024-12-16
