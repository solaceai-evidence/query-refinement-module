# Docker Production Setup - Complete Guide

## Quick Links

- 🚀 **[Quick Start VM Deployment](./QUICK_START_VM_DEPLOYMENT.md)** - 5-minute setup guide
- 📊 **[Optimization Summary](./DOCKER_OPTIMIZATION_SUMMARY.md)** - Technical details and changes
- 📖 **[Full Production Guide](./production_deployment.md)** - Comprehensive deployment documentation

## Overview

This directory contains the complete Docker-based production setup for deploying the Query Refinement Module to an external VM. The setup supports:

- ✅ **50+ concurrent users** with async architecture
- ✅ **Full stack deployment** (API + Frontend + Database + Cache + Proxy)
- ✅ **Zero-downtime deployments** with health checks
- ✅ **Horizontal scaling** for increased capacity
- ✅ **Production-grade security** and resource limits
- ✅ **SSL/TLS ready** for HTTPS

## File Structure

```
query-refinement-module/
├── docker-compose.yml              # Base configuration (all environments)
├── docker-compose.prod.yml         # Production overrides (NEW)
├── Dockerfile                      # API service container (UPDATED)
├── gunicorn_conf.py               # Gunicorn async configuration (UPDATED)
├── nginx/
│   └── nginx.conf                 # Nginx reverse proxy config (UPDATED)
├── frontend/
│   ├── Dockerfile.production      # Frontend React build
│   └── nginx.conf                 # Frontend nginx config
├── scripts/
│   └── validate_deployment.sh     # Pre-deployment validation (NEW)
└── docs/
    ├── QUICK_START_VM_DEPLOYMENT.md       # Quick start guide (NEW)
    ├── DOCKER_OPTIMIZATION_SUMMARY.md     # Technical summary (NEW)
    ├── DOCKER_SETUP_README.md             # This file (NEW)
    └── production_deployment.md           # Full deployment guide
```

## Services Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                      External VM                             │
│                                                              │
│  ┌────────────────────────────────────────────────────────┐ │
│  │              Nginx (Reverse Proxy)                     │ │
│  │              Port 80 (HTTP) / 443 (HTTPS)              │ │
│  └───────────┬─────────────────────────┬──────────────────┘ │
│              │                         │                     │
│     ┌────────▼────────┐       ┌───────▼──────────┐         │
│     │  Backend API    │       │    Frontend      │         │
│     │  (FastAPI)      │       │    (React)       │         │
│     │                 │       │                  │         │
│     │  - 4 Workers    │       │  - Static Build  │         │
│     │  - 50 LLM calls │       │  - SPA Router    │         │
│     │  - 180s timeout │       │  - Nginx Server  │         │
│     └────────┬────────┘       └──────────────────┘         │
│              │                                               │
│     ┌────────▼────────┐       ┌──────────────────┐         │
│     │  PostgreSQL 16  │       │    Redis 7       │         │
│     │                 │       │                  │         │
│     │  - Pooling      │       │  - Sessions      │         │
│     │  - Persistence  │       │  - Rate Limits   │         │
│     │  - 100 max conn │       │  - 512MB mem     │         │
│     └─────────────────┘       └──────────────────┘         │
└─────────────────────────────────────────────────────────────┘
```

## Service Configuration

| Service    | Purpose                          | Port  | Resources      |
|------------|----------------------------------|-------|----------------|
| nginx      | Reverse proxy, SSL, load balance | 80    | 0.5 CPU, 256MB |
| api        | FastAPI backend                  | 8000  | 2 CPU, 2GB     |
| frontend   | React SPA                        | 80    | 0.5 CPU, 256MB |
| postgres   | Database                         | 5432  | 1 CPU, 1GB     |
| redis      | Cache & sessions                 | 6379  | 0.5 CPU, 512MB |

**Total**: ~4.5 CPU cores, 4 GB RAM required

## Prerequisites

### System Requirements
- **OS**: Ubuntu 22.04 LTS or similar
- **CPU**: 4 cores minimum (5 recommended)
- **RAM**: 4 GB minimum (6 GB recommended)
- **Storage**: 20 GB SSD minimum
- **Network**: Public IP, ports 80/443/22 accessible

### Software Requirements
- Docker 24.0+
- Docker Compose 2.20+
- Git

## Quick Start

### 1. Validate Setup

```bash
# Clone repository
git clone <repository-url>
cd query-refinement-module

# Run validation script
./scripts/validate_deployment.sh
```

### 2. Configure Environment

```bash
# Copy template
cp .env.example .env

# Edit configuration
nano .env

# Essential variables:
# - SECRET_KEY (generate: openssl rand -hex 32)
# - POSTGRES_PASSWORD
# - QUERY_REFINEMENT_LLM_API_KEY
# - ALLOWED_ORIGINS
```

### 3. Deploy

```bash
# Build images
docker compose -f docker-compose.yml -f docker-compose.prod.yml build

# Start services
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d

# Check status
docker compose -f docker-compose.yml -f docker-compose.prod.yml ps

# View logs
docker compose -f docker-compose.yml -f docker-compose.prod.yml logs -f
```

### 4. Verify

```bash
# Test health endpoint
curl http://localhost/health

# Test API
curl http://localhost/api/health

# Test frontend
curl http://localhost/

# Check API docs
curl http://localhost/docs
```

## Configuration Details

### Environment Variables

**Critical Variables** (must be configured):
```bash
SECRET_KEY=                      # Generate with: openssl rand -hex 32
POSTGRES_PASSWORD=               # Strong database password
QUERY_REFINEMENT_LLM_API_KEY=   # Your LLM provider API key
ALLOWED_ORIGINS=                 # Your domain(s)
```

**Async Architecture** (optimized for 50 users):
```bash
LLM_MAX_CONCURRENT=50           # Concurrent LLM calls
LLM_CONNECTION_POOL_SIZE=100    # HTTP connection pool
LLM_KEEPALIVE_CONNECTIONS=50    # Persistent connections
WORKERS=4                        # Async workers
WORKER_TIMEOUT=180              # Worker timeout (seconds)
MAX_REQUESTS_PER_WORKER=5000    # Requests before restart
```

**Database**:
```bash
POSTGRES_HOST=postgres
POSTGRES_PORT=5432
POSTGRES_DB=query_refinement
POSTGRES_USER=postgres
POSTGRES_PASSWORD=              # Set this!
DB_POOL_SIZE=20
DB_MAX_OVERFLOW=40
```

**Redis**:
```bash
REDIS_HOST=redis
REDIS_PORT=6379
REDIS_PASSWORD=                 # Optional but recommended
```

### Resource Limits

Configured in [docker-compose.prod.yml](../docker-compose.prod.yml):

```yaml
api:
  deploy:
    resources:
      limits:
        cpus: '2.0'
        memory: 2G

postgres:
  deploy:
    resources:
      limits:
        cpus: '1.0'
        memory: 1G

redis:
  deploy:
    resources:
      limits:
        cpus: '0.5'
        memory: 512M
```

## Management Commands

### Viewing Logs

```bash
# All services
docker compose -f docker-compose.yml -f docker-compose.prod.yml logs -f

# Specific service
docker compose -f docker-compose.yml -f docker-compose.prod.yml logs -f api

# Last 100 lines
docker compose -f docker-compose.yml -f docker-compose.prod.yml logs --tail=100 api
```

### Restarting Services

```bash
# Restart all
docker compose -f docker-compose.yml -f docker-compose.prod.yml restart

# Restart specific service
docker compose -f docker-compose.yml -f docker-compose.prod.yml restart api

# Zero-downtime API restart
docker compose -f docker-compose.yml -f docker-compose.prod.yml scale api=2
docker compose -f docker-compose.yml -f docker-compose.prod.yml restart api
docker compose -f docker-compose.yml -f docker-compose.prod.yml scale api=1
```

### Updating Application

```bash
# Pull latest code
git pull origin main

# Rebuild and restart
docker compose -f docker-compose.yml -f docker-compose.prod.yml build
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d
```

### Scaling Services

```bash
# Scale API to 3 replicas
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --scale api=3

# Check running containers
docker compose -f docker-compose.yml -f docker-compose.prod.yml ps
```

### Stopping Services

```bash
# Stop all services
docker compose -f docker-compose.yml -f docker-compose.prod.yml down

# Stop and remove volumes (WARNING: deletes data)
docker compose -f docker-compose.yml -f docker-compose.prod.yml down -v
```

## Health Checks

All services have health checks configured:

```bash
# Check service health status
docker compose -f docker-compose.yml -f docker-compose.prod.yml ps

# Manual health check
curl http://localhost/health

# Database health
docker compose -f docker-compose.yml -f docker-compose.prod.yml exec postgres \
  psql -U postgres -d query_refinement -c "SELECT 1;"

# Redis health
docker compose -f docker-compose.yml -f docker-compose.prod.yml exec redis \
  redis-cli ping
```

## Monitoring

### Resource Usage

```bash
# Real-time resource monitoring
docker stats

# Disk usage
docker system df

# Detailed disk usage
du -sh /var/lib/docker/volumes/*
```

### Service Status

```bash
# All services status
docker compose -f docker-compose.yml -f docker-compose.prod.yml ps

# Container inspection
docker inspect <container-name>

# Service logs
docker compose -f docker-compose.yml -f docker-compose.prod.yml logs --tail=100
```

## Backup and Restore

### Database Backup

```bash
# Create backup
docker compose -f docker-compose.yml -f docker-compose.prod.yml exec postgres \
  pg_dump -U postgres query_refinement > backup_$(date +%Y%m%d_%H%M%S).sql

# Verify backup
ls -lh backup_*.sql
```

### Database Restore

```bash
# Restore from backup
docker compose -f docker-compose.yml -f docker-compose.prod.yml exec -T postgres \
  psql -U postgres query_refinement < backup_20240115_120000.sql
```

### Automated Backups

Add to crontab:
```bash
# Daily backup at 2 AM
0 2 * * * cd /path/to/query-refinement-module && docker compose -f docker-compose.yml -f docker-compose.prod.yml exec -T postgres pg_dump -U postgres query_refinement > backups/backup_$(date +\%Y\%m\%d).sql
```

## SSL/TLS Configuration

### Using Let's Encrypt

```bash
# Install Certbot
sudo apt-get install certbot -y

# Stop nginx
docker compose -f docker-compose.yml -f docker-compose.prod.yml stop nginx

# Obtain certificate
sudo certbot certonly --standalone -d yourdomain.com

# Copy certificates
mkdir -p nginx/ssl
sudo cp /etc/letsencrypt/live/yourdomain.com/fullchain.pem nginx/ssl/
sudo cp /etc/letsencrypt/live/yourdomain.com/privkey.pem nginx/ssl/

# Update nginx.conf (uncomment HTTPS server block)
nano nginx/nginx.conf

# Restart nginx
docker compose -f docker-compose.yml -f docker-compose.prod.yml start nginx
```

## Troubleshooting

### Common Issues

**1. Service won't start**
```bash
# Check logs for errors
docker compose -f docker-compose.yml -f docker-compose.prod.yml logs <service>

# Common causes:
# - Missing environment variables
# - Port already in use
# - Insufficient resources
```

**2. Database connection failed**
```bash
# Verify database is running
docker compose -f docker-compose.yml -f docker-compose.prod.yml ps postgres

# Check database logs
docker compose -f docker-compose.yml -f docker-compose.prod.yml logs postgres

# Test connection
docker compose -f docker-compose.yml -f docker-compose.prod.yml exec postgres \
  psql -U postgres -c "\l"
```

**3. 502 Bad Gateway**
```bash
# Check API is running
docker compose -f docker-compose.yml -f docker-compose.prod.yml ps api

# Check API logs
docker compose -f docker-compose.yml -f docker-compose.prod.yml logs api

# Restart API
docker compose -f docker-compose.yml -f docker-compose.prod.yml restart api
```

**4. High memory usage**
```bash
# Check resource usage
docker stats

# Reduce workers in .env
WORKERS=2

# Reduce concurrent operations
LLM_MAX_CONCURRENT=25

# Restart services
docker compose -f docker-compose.yml -f docker-compose.prod.yml restart
```

## Performance Tuning

### For 100+ Concurrent Users

Edit `.env`:
```bash
WORKERS=8                        # More workers
LLM_MAX_CONCURRENT=100          # More concurrent LLM calls
LLM_CONNECTION_POOL_SIZE=200    # Larger connection pool
```

Scale API:
```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --scale api=3
```

### Database Optimization

For higher load, increase PostgreSQL settings in [docker-compose.prod.yml](../docker-compose.prod.yml):

```yaml
postgres:
  command:
    - "postgres"
    - "-c" "max_connections=200"        # More connections
    - "-c" "shared_buffers=512MB"       # More cache
    - "-c" "effective_cache_size=2GB"   # More cache
```

## Security Best Practices

- ✅ **Strong passwords**: Use strong, unique passwords for all services
- ✅ **Environment secrets**: Never commit `.env` to version control
- ✅ **SSL/TLS**: Always use HTTPS in production
- ✅ **Firewall**: Only expose necessary ports (80, 443, 22)
- ✅ **Updates**: Keep Docker images and packages updated
- ✅ **Monitoring**: Monitor logs for suspicious activity
- ✅ **Backups**: Regular automated backups
- ✅ **Resource limits**: Prevent resource exhaustion attacks

## Support

### Documentation
- [Quick Start Guide](./QUICK_START_VM_DEPLOYMENT.md)
- [Optimization Summary](./DOCKER_OPTIMIZATION_SUMMARY.md)
- [Full Production Guide](./production_deployment.md)
- [API Documentation](./api_service.md)
- [Load Testing Guide](./load_testing_guide.md)

### Validation
- Run `./scripts/validate_deployment.sh` for pre-deployment checks

### Common Commands Reference

```bash
# Validate configuration
./scripts/validate_deployment.sh

# Build and deploy
docker compose -f docker-compose.yml -f docker-compose.prod.yml build
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d

# View logs
docker compose -f docker-compose.yml -f docker-compose.prod.yml logs -f

# Check status
docker compose -f docker-compose.yml -f docker-compose.prod.yml ps

# Test health
curl http://localhost/health

# Restart services
docker compose -f docker-compose.yml -f docker-compose.prod.yml restart

# Update application
git pull && docker compose -f docker-compose.yml -f docker-compose.prod.yml build && \
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d

# Stop services
docker compose -f docker-compose.yml -f docker-compose.prod.yml down
```

## What's New

### Recent Optimizations (Current Version)

- ✅ **Async architecture**: 50 concurrent LLM calls with semaphore control
- ✅ **Connection pooling**: 100 HTTP connections with keepalive
- ✅ **Resource limits**: CPU and memory limits for all services
- ✅ **Production tuning**: PostgreSQL and Redis optimized
- ✅ **Full stack setup**: Complete docker-compose.prod.yml
- ✅ **Health checks**: Automatic restart on failure
- ✅ **Documentation**: Comprehensive guides and validation scripts

## License

See [LICENSE](../LICENSE) for details.
