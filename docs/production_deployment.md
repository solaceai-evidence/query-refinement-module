# Production Deployment Guide

## Table of Contents

1. [Overview](#overview)
2. [Prerequisites](#prerequisites)
3. [Architecture](#architecture)
4. [Local Development Setup](#local-development-setup)
5. [Docker Development Environment](#docker-development-environment)
6. [Production Deployment](#production-deployment)
7. [Database Management](#database-management)
8. [Monitoring and Health Checks](#monitoring-and-health-checks)
9. [Performance Tuning](#performance-tuning)
10. [Security Hardening](#security-hardening)
11. [Troubleshooting](#troubleshooting)
12. [Scaling Guidelines](#scaling-guidelines)

---

## Overview

This guide covers deploying the Query Refinement Module API for production use, supporting up to 100+ concurrent users. The production infrastructure includes:

- **PostgreSQL** for persistent data storage with connection pooling
- **Redis** for session management and rate limiting
- **Gunicorn** with Uvicorn workers for async request handling
- **Docker** for containerization and orchestration
- **Structured logging** with JSON format for monitoring
- **Health checks** for load balancer integration
- **CORS configuration** for web application integration

### Key Features

- ✅ Horizontal scaling with multiple Gunicorn workers
- ✅ Connection pooling for database efficiency
- ✅ Redis-backed sessions with persistence
- ✅ Request tracing and metadata logging
- ✅ Health and readiness endpoints
- ✅ Graceful shutdown and zero-downtime deployments
- ✅ Multi-stage Docker builds for optimized images
- ✅ Comprehensive pre-flight validation

---

## Prerequisites

### Required Software

- **Python 3.12+**
- **Poetry** (dependency management)
- **Docker** and **Docker Compose** (for containerized deployment)
- **PostgreSQL 12+** (production database)
- **Redis 6+** (session and caching)

### Development Tools

- Git
- curl or httpie (for testing)
- PostgreSQL client tools (psql)
- Redis CLI (redis-cli)

### Cloud/Hosting Requirements (Production)

- **Compute**: 2+ CPU cores, 4GB+ RAM
- **Storage**: 20GB+ SSD for database
- **Network**: HTTPS/TLS termination (load balancer or reverse proxy)
- **Monitoring**: Log aggregation service (optional but recommended)

---

## Architecture

### System Components

```
┌─────────────────┐
│  Load Balancer  │  ← HTTPS/TLS termination
│   (NGINX/ALB)   │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│   Gunicorn      │  ← Multiple workers (2×CPU + 1)
│   + Uvicorn     │     Async request handling
└────────┬────────┘
         │
    ┌────┴────┐
    ▼         ▼
┌────────┐ ┌──────┐
│Postgres│ │Redis │  ← State management
│  (DB)  │ │(Cache)│
└────────┘ └──────┘
```

### Request Flow

1. **Client** → Load balancer (HTTPS)
2. **Load balancer** → Gunicorn workers (round-robin)
3. **Worker** → PostgreSQL (via connection pool)
4. **Worker** → Redis (sessions, rate limits)
5. **Worker** → LLM Provider API (OpenAI, Anthropic, etc.)
6. **Worker** → Client (JSON response)

### Data Persistence

- **PostgreSQL**: User data, API keys, refinement metadata
- **Redis**: Sessions (TTL-based), rate limit counters
- **File system**: Custom schema YAML files, logs

---

## Local Development Setup

### 1. Clone Repository

```bash
git clone <repository-url>
cd query-refinement-module
```

### 2. Install Dependencies

```bash
# Install Poetry (if not already installed)
curl -sSL https://install.python-poetry.org | python3 -

# Install project dependencies
poetry install
```

### 3. Configure Environment

```bash
# Copy example environment file
cp .env.example .env

# Edit .env with your settings
# At minimum, set:
# - SECRET_KEY (generate with: openssl rand -hex 32)
# - LLM_PROVIDER and corresponding API key
# - DATABASE_URL (default SQLite is fine for development)
```

### 4. Initialize Database

```bash
# Run migrations
poetry run alembic upgrade head
```

### 5. Start Development Server

```bash
# Using FastAPI's built-in server (development only)
poetry run uvicorn query_refinement_module.api.main:app --reload --host 0.0.0.0 --port 8000
```

### 6. Verify Setup

```bash
# Check health endpoint
curl http://localhost:8000/health

# Check API documentation
open http://localhost:8000/docs
```

---

## Docker Development Environment

### 1. Prerequisites

Ensure Docker and Docker Compose are installed:

```bash
docker --version  # Should be 20.10+
docker-compose --version  # Should be 2.0+
```

### 2. Configure Environment

```bash
# Copy example file
cp .env.production.example .env

# Edit for development (keep ENVIRONMENT=development)
# Update:
# - SECRET_KEY
# - LLM API keys
# - POSTGRES_PASSWORD
```

### 3. Build and Start Services

```bash
# Build images
docker-compose build

# Start all services (postgres, redis, api)
docker-compose up -d

# View logs
docker-compose logs -f api
```

### 4. Run Migrations

```bash
# Migrations run automatically on container start
# To run manually:
docker-compose exec api alembic upgrade head
```

### 5. Verify Services

```bash
# Check all containers are running
docker-compose ps

# Test API
curl http://localhost:8000/health
curl http://localhost:8000/ready

# Check database
docker-compose exec postgres psql -U queryrefine -d query_refinement -c "\dt"

# Check Redis
docker-compose exec redis redis-cli ping
```

### 6. Stop Services

```bash
# Stop but keep data
docker-compose stop

# Stop and remove containers (keeps volumes)
docker-compose down

# Remove everything including volumes (⚠️ deletes data)
docker-compose down -v
```

---

## Production Deployment

### Option 1: Docker Compose (Single Host)

**Best for**: Small to medium deployments (< 100 users)

#### 1. Prepare Server

```bash
# Update system
sudo apt update && sudo apt upgrade -y

# Install Docker
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker $USER

# Install Docker Compose
sudo curl -L "https://github.com/docker/compose/releases/latest/download/docker-compose-$(uname -s)-$(uname -m)" -o /usr/local/bin/docker-compose
sudo chmod +x /usr/local/bin/docker-compose
```

#### 2. Clone and Configure

```bash
# Clone repository
git clone <repository-url> /opt/query-refinement
cd /opt/query-refinement

# Create production environment file
cp .env.production.example .env

# Edit .env - CRITICAL SETTINGS:
# - ENVIRONMENT=production
# - DEBUG=false
# - SECRET_KEY (generate new: openssl rand -hex 32)
# - DATABASE_URL with strong password
# - ALLOWED_ORIGINS with production domains
# - LOG_FORMAT=json
# - All LLM API keys
```

#### 3. Deploy

```bash
# Build production images
docker-compose build --no-cache

# Start services
docker-compose up -d

# Check status
docker-compose ps
docker-compose logs -f api
```

#### 4. Configure Reverse Proxy (NGINX)

```nginx
# /etc/nginx/sites-available/query-refinement
upstream query_refinement {
    server localhost:8000;
    keepalive 32;
}

server {
    listen 80;
    server_name api.yourdomain.com;
    
    # Redirect HTTP to HTTPS
    return 301 https://$server_name$request_uri;
}

server {
    listen 443 ssl http2;
    server_name api.yourdomain.com;
    
    # SSL certificates (Let's Encrypt)
    ssl_certificate /etc/letsencrypt/live/api.yourdomain.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/api.yourdomain.com/privkey.pem;
    
    # SSL configuration
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers HIGH:!aNULL:!MD5;
    ssl_prefer_server_ciphers on;
    
    # Proxy settings
    location / {
        proxy_pass http://query_refinement;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        
        # Timeouts
        proxy_connect_timeout 60s;
        proxy_send_timeout 120s;
        proxy_read_timeout 120s;
        
        # WebSocket support (if needed)
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
    }
    
    # Health check endpoint (for load balancer)
    location /health {
        proxy_pass http://query_refinement/health;
        access_log off;
    }
}
```

Enable and restart NGINX:

```bash
sudo ln -s /etc/nginx/sites-available/query-refinement /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl reload nginx
```

#### 5. Set Up SSL with Let's Encrypt

```bash
# Install Certbot
sudo apt install certbot python3-certbot-nginx

# Obtain certificate
sudo certbot --nginx -d api.yourdomain.com

# Test auto-renewal
sudo certbot renew --dry-run
```

### Option 2: Manual Deployment (Without Docker)

**Best for**: Custom environments, specific requirements

#### 1. Install System Dependencies

```bash
# PostgreSQL
sudo apt install postgresql postgresql-contrib

# Redis
sudo apt install redis-server

# Python build tools
sudo apt install python3.12 python3.12-dev python3-pip libpq-dev
```

#### 2. Create Application User

```bash
sudo useradd -m -s /bin/bash queryrefine
sudo su - queryrefine
```

#### 3. Install Application

```bash
# Clone repository
git clone <repository-url> ~/query-refinement
cd ~/query-refinement

# Install Poetry
curl -sSL https://install.python-poetry.org | python3 -

# Install dependencies
~/.local/bin/poetry install --only main
```

#### 4. Configure Services

**PostgreSQL:**

```bash
sudo -u postgres psql
```

```sql
CREATE DATABASE query_refinement;
CREATE USER queryrefine WITH PASSWORD 'secure_password';
GRANT ALL PRIVILEGES ON DATABASE query_refinement TO queryrefine;
\q
```

**Redis:**

```bash
# Edit /etc/redis/redis.conf
sudo nano /etc/redis/redis.conf

# Set:
# maxmemory 512mb
# maxmemory-policy allkeys-lru
# appendonly yes

# Restart Redis
sudo systemctl restart redis
```

#### 5. Configure Environment

```bash
# Create .env file
cp .env.production.example .env
nano .env

# Set DATABASE_URL:
# DATABASE_URL=postgresql://queryrefine:secure_password@localhost/query_refinement
```

#### 6. Run Migrations

```bash
~/.local/bin/poetry run alembic upgrade head
```

#### 7. Create Systemd Service

```bash
sudo nano /etc/systemd/system/query-refinement.service
```

```ini
[Unit]
Description=Query Refinement API
After=network.target postgresql.service redis.service
Requires=postgresql.service redis.service

[Service]
Type=notify
User=queryrefine
Group=queryrefine
WorkingDirectory=/home/queryrefine/query-refinement
Environment="PATH=/home/queryrefine/.local/bin:/usr/bin"
ExecStart=/home/queryrefine/query-refinement/start_production.sh
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

```bash
# Reload systemd and start service
sudo systemctl daemon-reload
sudo systemctl enable query-refinement
sudo systemctl start query-refinement

# Check status
sudo systemctl status query-refinement
```

---

## Database Management

### Migrations

#### Creating New Migrations

```bash
# Auto-generate migration from model changes
poetry run alembic revision --autogenerate -m "Description of changes"

# Review generated migration in db/migrations/versions/
# Edit if necessary

# Apply migration
poetry run alembic upgrade head
```

#### Viewing Migration Status

```bash
# Current version
poetry run alembic current

# Migration history
poetry run alembic history

# Show pending migrations
poetry run alembic heads
```

#### Rolling Back Migrations

```bash
# Downgrade one version
poetry run alembic downgrade -1

# Downgrade to specific version
poetry run alembic downgrade <revision_id>

# Downgrade to base
poetry run alembic downgrade base
```

### Backup and Restore

#### PostgreSQL Backup

```bash
# Full database backup
pg_dump -U queryrefine -h localhost query_refinement > backup_$(date +%Y%m%d_%H%M%S).sql

# Docker container backup
docker-compose exec -T postgres pg_dump -U queryrefine query_refinement > backup.sql

# Automated daily backups
cat > /etc/cron.daily/postgres-backup << 'EOF'
#!/bin/bash
BACKUP_DIR=/var/backups/query-refinement
DATE=$(date +%Y%m%d_%H%M%S)
mkdir -p $BACKUP_DIR
docker-compose -f /opt/query-refinement/docker-compose.yml exec -T postgres \
    pg_dump -U queryrefine query_refinement | gzip > $BACKUP_DIR/backup_$DATE.sql.gz
find $BACKUP_DIR -name "backup_*.sql.gz" -mtime +30 -delete
EOF

chmod +x /etc/cron.daily/postgres-backup
```

#### PostgreSQL Restore

```bash
# Restore from backup
psql -U queryrefine -h localhost query_refinement < backup.sql

# Docker container restore
cat backup.sql | docker-compose exec -T postgres psql -U queryrefine query_refinement
```

#### Redis Backup

Redis automatically saves data to disk when using AOF (enabled in docker-compose.yml).

```bash
# Manual save
docker-compose exec redis redis-cli SAVE

# Copy AOF file
docker cp query-refinement-redis-1:/data/appendonly.aof ./redis_backup.aof
```

### Connection Pooling Monitoring

```python
# Add to query_refinement_module/db/database.py for monitoring
from sqlalchemy import event

@event.listens_for(engine.sync_engine, "connect")
def receive_connect(dbapi_conn, connection_record):
    logger.info("Database connection established", extra={
        "pool_size": engine.sync_engine.pool.size(),
        "checked_out": engine.sync_engine.pool.checkedout()
    })
```

---

## Monitoring and Health Checks

### Health Endpoints

#### Liveness Check (`/health`)

Returns 200 if the application is running:

```bash
curl http://localhost:8000/health
```

Response:
```json
{
  "status": "healthy",
  "service": "Query Refinement API",
  "version": "1.0.0",
  "environment": "production"
}
```

#### Readiness Check (`/ready`)

Returns 200 only if database and Redis are accessible:

```bash
curl http://localhost:8000/ready
```

Response (healthy):
```json
{
  "status": "ready",
  "checks": {
    "database": "ok",
    "redis": "ok"
  }
}
```

Response (unhealthy):
```json
{
  "status": "not ready",
  "checks": {
    "database": "ok",
    "redis": "connection failed"
  }
}
```

### Load Balancer Configuration

Configure your load balancer to use health checks:

**AWS Application Load Balancer:**
- Health check path: `/ready`
- Healthy threshold: 2
- Unhealthy threshold: 3
- Timeout: 5 seconds
- Interval: 30 seconds

**NGINX:**
```nginx
upstream query_refinement {
    server localhost:8000 max_fails=3 fail_timeout=30s;
    keepalive 32;
}
```

### Log Aggregation

#### Viewing Logs

```bash
# Docker logs
docker-compose logs -f api

# Systemd logs
sudo journalctl -u query-refinement -f

# Application logs (if LOG_FILE is set)
tail -f logs/app.log
```

#### Structured JSON Logging

When `LOG_FORMAT=json`, logs are structured for parsing:

```json
{
  "timestamp": "2024-01-15T10:30:45.123Z",
  "level": "INFO",
  "logger": "query_refinement_module.api.session_manager",
  "message": "Refinement session created",
  "request_id": "abc123xyz",
  "user_id": "user_456",
  "session_id": "session_789",
  "duration_ms": 125
}
```

#### Log Shipping (Optional)

**Using Fluentd/Fluent Bit:**

```yaml
# docker-compose.yml addition
  fluentd:
    image: fluent/fluentd:latest
    volumes:
      - ./fluentd.conf:/fluentd/etc/fluent.conf
      - ./logs:/logs
    ports:
      - "24224:24224"
```

**Using Vector:**

```toml
# vector.toml
[sources.docker_logs]
type = "docker_logs"

[sinks.elasticsearch]
type = "elasticsearch"
inputs = ["docker_logs"]
endpoint = "http://elasticsearch:9200"
```

### Application Metrics

#### Custom Metrics (Future Enhancement)

Add Prometheus metrics:

```python
# query_refinement_module/api/metrics.py
from prometheus_client import Counter, Histogram, generate_latest

request_count = Counter('http_requests_total', 'Total HTTP requests', ['method', 'endpoint', 'status'])
request_duration = Histogram('http_request_duration_seconds', 'HTTP request duration')

# Expose metrics endpoint
@app.get("/metrics")
async def metrics():
    return Response(content=generate_latest(), media_type="text/plain")
```

---

## Performance Tuning

### Gunicorn Workers

**Formula**: `(2 × CPU cores) + 1`

```bash
# Check CPU cores
nproc

# Example: 4 cores = 9 workers
WORKERS=9
```

Update `.env`:
```bash
WORKERS=9
WORKER_CLASS=uvicorn.workers.UvicornWorker
TIMEOUT=120
```

### Database Connection Pool

**Recommended Settings** (100 concurrent users):

```bash
# Conservative (lower memory)
DB_POOL_SIZE=10
DB_POOL_MAX_OVERFLOW=20

# Aggressive (higher throughput)
DB_POOL_SIZE=20
DB_POOL_MAX_OVERFLOW=40
```

**Calculation**:
- Pool size = `WORKERS × 2`
- Max overflow = `POOL_SIZE × 2`
- Total max connections = `POOL_SIZE + MAX_OVERFLOW`

**PostgreSQL max_connections** must be higher:
```sql
-- Check current setting
SHOW max_connections;

-- Increase if needed (requires restart)
ALTER SYSTEM SET max_connections = 100;
```

### Redis Memory Optimization

```bash
# Set max memory
REDIS_MAXMEMORY=512mb
REDIS_MAXMEMORY_POLICY=allkeys-lru

# Tune session TTL
SESSION_TIMEOUT_MINUTES=60  # Shorter = less memory
```

### Operating System Limits

```bash
# Increase file descriptors
sudo nano /etc/security/limits.conf
```

Add:
```
queryrefine soft nofile 65536
queryrefine hard nofile 65536
```

```bash
# Increase network backlog
sudo sysctl -w net.core.somaxconn=1024
sudo sysctl -w net.ipv4.tcp_max_syn_backlog=2048
```

### Database Query Optimization

```sql
-- Add indexes for frequently queried columns
CREATE INDEX idx_api_keys_user_id ON api_keys(user_id);
CREATE INDEX idx_sessions_session_id ON refinement_sessions(session_id);
CREATE INDEX idx_metadata_session_id ON refinement_step_metadata(session_id);
CREATE INDEX idx_metadata_request_id ON refinement_step_metadata(request_id);

-- Analyze query performance
EXPLAIN ANALYZE SELECT * FROM refinement_sessions WHERE session_id = 'abc123';
```

---

## Security Hardening

### SSL/TLS Configuration

Always use HTTPS in production. Configure your reverse proxy (NGINX, Caddy, or cloud load balancer) for TLS termination.

**Strong SSL settings:**
```nginx
ssl_protocols TLSv1.2 TLSv1.3;
ssl_ciphers 'ECDHE-ECDSA-AES128-GCM-SHA256:ECDHE-RSA-AES128-GCM-SHA256:ECDHE-ECDSA-AES256-GCM-SHA384:ECDHE-RSA-AES256-GCM-SHA384';
ssl_prefer_server_ciphers on;
ssl_session_cache shared:SSL:10m;
ssl_session_timeout 10m;
```

### Secrets Management

**Never commit secrets to version control.**

**Option 1: Environment Variables (Basic)**
```bash
# Set in .env (never commit this file)
SECRET_KEY=$(openssl rand -hex 32)
```

**Option 2: AWS Secrets Manager**
```python
import boto3

def get_secret(secret_name):
    client = boto3.client('secretsmanager')
    response = client.get_secret_value(SecretId=secret_name)
    return response['SecretString']
```

**Option 3: HashiCorp Vault**
```python
import hvac

client = hvac.Client(url='https://vault.example.com')
secret = client.secrets.kv.v2.read_secret_version(path='query-refinement/api')
```

### API Key Security

```python
# Rotate API keys regularly
# Use strong random generation
import secrets
api_key = secrets.token_urlsafe(32)

# Hash keys before storage
from passlib.hash import pbkdf2_sha256
hashed_key = pbkdf2_sha256.hash(api_key)
```

### Rate Limiting

Prevent abuse with rate limits:

```bash
# Per-user limits
RATE_LIMIT_PER_USER_REQUESTS_PER_MINUTE=30
RATE_LIMIT_PER_USER_REQUESTS_PER_HOUR=500

# Global limits
RATE_LIMIT_REQUESTS_PER_MINUTE=100
RATE_LIMIT_REQUESTS_PER_HOUR=5000
```

### Database Security

```sql
-- Revoke unnecessary privileges
REVOKE ALL ON DATABASE query_refinement FROM PUBLIC;
GRANT CONNECT ON DATABASE query_refinement TO queryrefine;

-- Enable SSL connections
ALTER SYSTEM SET ssl = 'on';

-- Restrict network access
# Edit pg_hba.conf:
# hostssl  query_refinement  queryrefine  10.0.0.0/8  md5
```

### Docker Security

```dockerfile
# Run as non-root user
USER appuser

# Read-only root filesystem
docker run --read-only --tmpfs /tmp query-refinement-api

# Drop capabilities
docker run --cap-drop=ALL query-refinement-api
```

### Firewall Configuration

```bash
# Allow only necessary ports
sudo ufw allow 22/tcp    # SSH
sudo ufw allow 80/tcp    # HTTP (redirect to HTTPS)
sudo ufw allow 443/tcp   # HTTPS
sudo ufw enable

# Block direct access to backend services
sudo ufw deny 5432/tcp   # PostgreSQL
sudo ufw deny 6379/tcp   # Redis
```

---

## Troubleshooting

### Common Issues

#### 1. Database Connection Errors

**Symptom**: `OperationalError: (psycopg2.OperationalError) could not connect to server`

**Solutions**:
```bash
# Check PostgreSQL is running
docker-compose ps postgres
sudo systemctl status postgresql

# Verify connection string
echo $DATABASE_URL

# Test connection manually
psql $DATABASE_URL

# Check network connectivity
telnet localhost 5432

# Check PostgreSQL logs
docker-compose logs postgres
sudo journalctl -u postgresql -f
```

#### 2. Redis Connection Errors

**Symptom**: `ConnectionRefusedError: [Errno 111] Connection refused`

**Solutions**:
```bash
# Check Redis is running
docker-compose ps redis
sudo systemctl status redis

# Test Redis connection
redis-cli ping
docker-compose exec redis redis-cli ping

# Check Redis logs
docker-compose logs redis
sudo journalctl -u redis -f
```

#### 3. Pool Connection Timeout

**Symptom**: `TimeoutError: QueuePool limit of size X overflow Y reached`

**Solutions**:
```bash
# Increase pool size in .env
DB_POOL_SIZE=20
DB_POOL_MAX_OVERFLOW=40

# Reduce connection lifetime
DB_POOL_RECYCLE=1800

# Check for connection leaks
# Add to database.py:
@event.listens_for(engine.sync_engine, "checkin")
def receive_checkin(dbapi_conn, connection_record):
    logger.info(f"Connection returned to pool. Pool size: {engine.sync_engine.pool.size()}")
```

#### 4. Memory Issues

**Symptom**: Container killed (exit code 137) or high memory usage

**Solutions**:
```bash
# Check memory usage
docker stats

# Reduce workers
WORKERS=5  # Decrease if using too much memory

# Reduce pool size
DB_POOL_SIZE=10

# Set memory limits in docker-compose.yml
services:
  api:
    deploy:
      resources:
        limits:
          memory: 2G
```

#### 5. Slow API Responses

**Solutions**:
```bash
# Enable query logging to find slow queries
DB_ECHO=true
LOG_SQL_QUERIES=true

# Check database indexes
psql -d query_refinement -c "\d+ refinement_sessions"

# Analyze query plans
EXPLAIN ANALYZE SELECT ...

# Check connection pool stats
# Add monitoring endpoint
@app.get("/pool-status")
async def pool_status():
    return {
        "size": engine.sync_engine.pool.size(),
        "checked_out": engine.sync_engine.pool.checkedout(),
        "overflow": engine.sync_engine.pool.overflow()
    }
```

#### 6. Migration Failures

**Symptom**: `alembic.util.exc.CommandError: Target database is not up to date`

**Solutions**:
```bash
# Check current version
poetry run alembic current

# View migration history
poetry run alembic history

# Force stamp to specific version (⚠️ use cautiously)
poetry run alembic stamp head

# Rebuild from scratch (⚠️ deletes all data)
poetry run alembic downgrade base
poetry run alembic upgrade head
```

### Debugging Tools

#### Enable Debug Logging

```bash
# Temporary debug mode
LOG_LEVEL=DEBUG
DB_ECHO=true

# Restart service
docker-compose restart api
```

#### Request Tracing

All requests are assigned a `request_id`. Find it in logs:

```bash
# Search for specific request
docker-compose logs api | grep "request_id=abc123xyz"

# Follow a session
docker-compose logs api | grep "session_id=session_789"
```

#### Database Queries

```bash
# Connect to database
docker-compose exec postgres psql -U queryrefine query_refinement

# Common queries
SELECT * FROM refinement_sessions WHERE user_id = 'user_456';
SELECT * FROM refinement_step_metadata WHERE session_id = 'session_789' ORDER BY step_number;
SELECT COUNT(*) FROM api_keys WHERE is_active = true;

# Check for stuck connections
SELECT * FROM pg_stat_activity WHERE datname = 'query_refinement';
```

#### Redis Debugging

```bash
# Connect to Redis
docker-compose exec redis redis-cli

# Check session keys
KEYS session:*

# Get session data
GET session:abc123xyz

# Check rate limit counters
KEYS ratelimit:*

# Monitor commands in real-time
MONITOR
```

---

## Scaling Guidelines

### Vertical Scaling (Single Server)

**Small Deployment (< 50 users)**
- 2 CPU cores, 4GB RAM
- DB_POOL_SIZE=10, WORKERS=5
- PostgreSQL shared_buffers=1GB
- Redis maxmemory=256MB

**Medium Deployment (50-100 users)**
- 4 CPU cores, 8GB RAM
- DB_POOL_SIZE=20, WORKERS=9
- PostgreSQL shared_buffers=2GB
- Redis maxmemory=512MB

**Large Deployment (100-500 users)**
- 8 CPU cores, 16GB RAM
- DB_POOL_SIZE=40, WORKERS=17
- PostgreSQL shared_buffers=4GB
- Redis maxmemory=1GB

### Horizontal Scaling (Multiple Servers)

For deployments exceeding 500 users, scale horizontally:

#### 1. Stateless API Servers

Deploy multiple API containers behind a load balancer:

```yaml
# docker-compose-api1.yml
services:
  api:
    image: query-refinement-api:latest
    environment:
      - HOST=0.0.0.0
      - PORT=8000
      - DATABASE_URL=postgresql://user:pass@db.example.com/query_refinement
      - REDIS_URL=redis://redis.example.com:6379/0
```

```yaml
# docker-compose-api2.yml
services:
  api:
    image: query-refinement-api:latest
    environment:
      - HOST=0.0.0.0
      - PORT=8001  # Different port
      - DATABASE_URL=postgresql://user:pass@db.example.com/query_refinement
      - REDIS_URL=redis://redis.example.com:6379/0
```

#### 2. Managed Database Services

Use cloud database services for better scaling:

- **AWS RDS**: Automated backups, read replicas, automatic failover
- **Google Cloud SQL**: High availability, automated scaling
- **Azure Database for PostgreSQL**: Built-in replication

Update `DATABASE_URL`:
```bash
DATABASE_URL=postgresql://user:pass@your-db-instance.region.rds.amazonaws.com:5432/query_refinement
```

#### 3. Redis Cluster

For high availability:

```bash
# Use managed Redis
# AWS ElastiCache, Google Memorystore, Azure Cache for Redis
REDIS_URL=rediss://username:password@your-redis-cluster:6379/0
```

#### 4. Load Balancer Configuration

**AWS Application Load Balancer:**
- Target groups: Multiple API servers
- Health checks: `/ready` endpoint
- Connection draining: 300 seconds
- Sticky sessions: Disabled (stateless API)

**NGINX:**
```nginx
upstream api_servers {
    least_conn;  # Load balancing algorithm
    server api1.internal:8000 max_fails=3 fail_timeout=30s;
    server api2.internal:8000 max_fails=3 fail_timeout=30s;
    server api3.internal:8000 max_fails=3 fail_timeout=30s;
}
```

#### 5. Auto-Scaling (Kubernetes Example)

```yaml
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: query-refinement-hpa
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: query-refinement-api
  minReplicas: 3
  maxReplicas: 10
  metrics:
  - type: Resource
    resource:
      name: cpu
      target:
        type: Utilization
        averageUtilization: 70
  - type: Resource
    resource:
      name: memory
      target:
        type: Utilization
        averageUtilization: 80
```

### Database Optimization for Scale

```sql
-- Read replicas for reporting queries
-- Configure in DATABASE_URL:
# Read queries: postgresql://user:pass@read-replica.example.com/query_refinement
# Write queries: postgresql://user:pass@primary.example.com/query_refinement

-- Connection pooling with PgBouncer
# Install PgBouncer between API and PostgreSQL
# Reduces connection overhead, increases scalability

-- Partitioning large tables
CREATE TABLE refinement_step_metadata_2024_01 PARTITION OF refinement_step_metadata
FOR VALUES FROM ('2024-01-01') TO ('2024-02-01');
```

---

## Additional Resources

### Documentation

- [FastAPI Documentation](https://fastapi.tiangolo.com/)
- [SQLAlchemy Documentation](https://docs.sqlalchemy.org/)
- [Gunicorn Documentation](https://docs.gunicorn.org/)
- [Docker Documentation](https://docs.docker.com/)
- [PostgreSQL Documentation](https://www.postgresql.org/docs/)
- [Redis Documentation](https://redis.io/documentation)

### Monitoring and Observability

- **Prometheus + Grafana**: Metrics collection and visualization
- **ELK Stack**: Centralized logging (Elasticsearch, Logstash, Kibana)
- **Datadog**: All-in-one monitoring solution
- **New Relic**: APM and infrastructure monitoring
- **Sentry**: Error tracking and performance monitoring

### Infrastructure as Code

```yaml
# Example Terraform configuration
resource "aws_db_instance" "query_refinement" {
  identifier        = "query-refinement-db"
  engine            = "postgres"
  engine_version    = "16.0"
  instance_class    = "db.t3.medium"
  allocated_storage = 100
  storage_encrypted = true
  
  db_name  = "query_refinement"
  username = "queryrefine"
  password = var.db_password
  
  backup_retention_period = 7
  multi_az               = true
  
  tags = {
    Environment = "production"
    Service     = "query-refinement"
  }
}
```

---

## Support and Contributing

For issues, questions, or contributions, please refer to:
- [Issue Tracker](https://github.com/your-repo/issues)
- [Discussions](https://github.com/your-repo/discussions)
- [Contributing Guide](../CONTRIBUTING.md)

---

**Version**: 1.0.0  
**Last Updated**: 2024-01-15  
**Maintainer**: Your Team
