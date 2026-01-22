# Quick Start: External VM Production Deployment

## Overview

This guide provides step-by-step instructions for deploying the Query Refinement Module to an external VM for production use with the optimized async architecture supporting 50+ concurrent users.

## System Requirements

- **OS**: Ubuntu 22.04 LTS (recommended)
- **CPU**: 4 cores minimum
- **RAM**: 4 GB minimum
- **Storage**: 20 GB SSD
- **Network**: Public IP address
- **Ports**: 80 (HTTP), 443 (HTTPS), 22 (SSH)

## Pre-Installation

### 1. Install Docker and Docker Compose

```bash
# Update system
sudo apt-get update
sudo apt-get upgrade -y

# Install Docker
curl -fsSL https://get.docker.com -o get-docker.sh
sudo sh get-docker.sh
sudo usermod -aG docker $USER

# Install Docker Compose
sudo apt-get install docker-compose-plugin -y

# Verify installation
docker --version
docker compose version
```

### 2. Configure Firewall

```bash
# Allow SSH
sudo ufw allow 22/tcp

# Allow HTTP
sudo ufw allow 80/tcp

# Allow HTTPS
sudo ufw allow 443/tcp

# Enable firewall
sudo ufw enable
```

## Deployment Steps

### 1. Clone Repository

```bash
cd ~
git clone https://github.com/your-org/query-refinement-module.git
cd query-refinement-module
```

### 2. Configure Environment

```bash
# Copy environment template
cp .env.example .env

# Edit environment file
nano .env
```

**Essential Variables to Configure:**

```bash
# Application
ENVIRONMENT=production
SECRET_KEY=__GENERATE_THIS__  # Use: openssl rand -hex 32
ALLOWED_ORIGINS=http://your-vm-ip,https://yourdomain.com

# Database Credentials
POSTGRES_PASSWORD=__CHANGE_THIS__  # Strong password
POSTGRES_DB=query_refinement
POSTGRES_USER=postgres

# Redis
REDIS_PASSWORD=__CHANGE_THIS__  # Strong password

# LLM Provider (OpenAI example)
QUERY_REFINEMENT_LLM_PROVIDER=openai
QUERY_REFINEMENT_LLM_MODEL=gpt-4-turbo-preview
QUERY_REFINEMENT_LLM_API_KEY=__YOUR_API_KEY__

# Async Configuration (Optimized for 50 concurrent users)
LLM_MAX_CONCURRENT=50
LLM_CONNECTION_POOL_SIZE=100
LLM_KEEPALIVE_CONNECTIONS=50
WORKERS=4
WORKER_TIMEOUT=180
MAX_REQUESTS_PER_WORKER=5000
```

**Generate Secret Key:**
```bash
openssl rand -hex 32
```

### 3. Build and Start Services

```bash
# Build all images
docker compose -f docker-compose.yml -f docker-compose.prod.yml build

# Start all services in background
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d

# View logs
docker compose -f docker-compose.yml -f docker-compose.prod.yml logs -f
```

### 4. Verify Deployment

```bash
# Check all services are running
docker compose -f docker-compose.yml -f docker-compose.prod.yml ps

# Expected output:
# NAME                      STATUS          PORTS
# postgres                  Up (healthy)    5432/tcp
# redis                     Up (healthy)    6379/tcp
# api                       Up (healthy)    8000/tcp
# frontend                  Up              80/tcp
# nginx                     Up              0.0.0.0:80->80/tcp

# Test health endpoint
curl http://localhost/health

# Expected: {"status":"healthy","timestamp":"2024-..."}

# Test API endpoint
curl http://localhost/api/health

# Test frontend
curl http://localhost/
```

### 5. Access Application

- **Frontend**: http://your-vm-ip
- **API Docs**: http://your-vm-ip/docs
- **API Health**: http://your-vm-ip/health

## Optional: SSL/TLS Setup (Recommended)

### Using Let's Encrypt (Free SSL)

```bash
# Install Certbot
sudo apt-get install certbot -y

# Stop nginx temporarily
docker compose -f docker-compose.yml -f docker-compose.prod.yml stop nginx

# Obtain certificate
sudo certbot certonly --standalone -d yourdomain.com

# Create SSL directory
mkdir -p nginx/ssl

# Copy certificates
sudo cp /etc/letsencrypt/live/yourdomain.com/fullchain.pem nginx/ssl/
sudo cp /etc/letsencrypt/live/yourdomain.com/privkey.pem nginx/ssl/
sudo chmod 644 nginx/ssl/*.pem

# Update nginx/nginx.conf
# Uncomment HTTPS server block and update domain name

# Restart nginx
docker compose -f docker-compose.yml -f docker-compose.prod.yml start nginx

# Set up auto-renewal
sudo crontab -e
# Add: 0 0 * * * certbot renew --quiet
```

## Management Commands

### View Logs

```bash
# All services
docker compose -f docker-compose.yml -f docker-compose.prod.yml logs -f

# Specific service
docker compose -f docker-compose.yml -f docker-compose.prod.yml logs -f api

# Last 100 lines
docker compose -f docker-compose.yml -f docker-compose.prod.yml logs --tail=100
```

### Restart Services

```bash
# Restart all
docker compose -f docker-compose.yml -f docker-compose.prod.yml restart

# Restart API only
docker compose -f docker-compose.yml -f docker-compose.prod.yml restart api
```

### Update Application

```bash
# Pull latest code
git pull origin main

# Rebuild and restart
docker compose -f docker-compose.yml -f docker-compose.prod.yml build
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d
```

### Stop Services

```bash
# Stop all services
docker compose -f docker-compose.yml -f docker-compose.prod.yml down

# Stop and remove volumes (WARNING: deletes data)
docker compose -f docker-compose.yml -f docker-compose.prod.yml down -v
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

## Monitoring

### Check Resource Usage

```bash
# Real-time stats
docker stats

# Disk usage
df -h
docker system df
```

### Check Service Health

```bash
# API health
curl http://localhost/health

# Database connection
docker compose -f docker-compose.yml -f docker-compose.prod.yml exec postgres \
  psql -U postgres -d query_refinement -c "SELECT 1;"

# Redis connection
docker compose -f docker-compose.yml -f docker-compose.prod.yml exec redis \
  redis-cli ping
```

## Troubleshooting

### Service Not Starting

```bash
# Check logs
docker compose -f docker-compose.yml -f docker-compose.prod.yml logs api

# Common issues:
# 1. Missing environment variables (.env not configured)
# 2. Port already in use (check with: sudo netstat -tlnp | grep :80)
# 3. Database connection failed (check postgres logs)
```

### Database Connection Failed

```bash
# Check database is running
docker compose -f docker-compose.yml -f docker-compose.prod.yml ps postgres

# View database logs
docker compose -f docker-compose.yml -f docker-compose.prod.yml logs postgres

# Test connection manually
docker compose -f docker-compose.yml -f docker-compose.prod.yml exec postgres \
  psql -U postgres -c "\l"
```

### High Memory Usage

```bash
# Check current usage
docker stats --no-stream

# Solutions:
# 1. Reduce WORKERS in .env (default: 4)
# 2. Reduce LLM_MAX_CONCURRENT (default: 50)
# 3. Restart services to clear memory
docker compose -f docker-compose.yml -f docker-compose.prod.yml restart
```

### API Returns 502 Bad Gateway

```bash
# Check API is running
docker compose -f docker-compose.yml -f docker-compose.prod.yml ps api

# Check API logs
docker compose -f docker-compose.yml -f docker-compose.prod.yml logs api

# Restart API
docker compose -f docker-compose.yml -f docker-compose.prod.yml restart api
```

## Performance Tuning

### For 50+ Concurrent Users

The default configuration is optimized for 50 concurrent users:

```bash
# In .env:
WORKERS=4                        # 4 async workers
LLM_MAX_CONCURRENT=50           # 50 concurrent LLM calls
LLM_CONNECTION_POOL_SIZE=100    # 100 HTTP connections
WORKER_TIMEOUT=180              # 180s timeout for LLM calls
MAX_REQUESTS_PER_WORKER=5000    # 5000 requests before worker restart
```

### For 100+ Concurrent Users

Edit `.env`:

```bash
WORKERS=8                        # Increase workers
LLM_MAX_CONCURRENT=100          # Increase concurrent calls
LLM_CONNECTION_POOL_SIZE=200    # Increase connection pool
```

Then restart:
```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d
```

## Security Checklist

- ✅ Change default passwords (POSTGRES_PASSWORD, REDIS_PASSWORD)
- ✅ Generate unique SECRET_KEY
- ✅ Configure ALLOWED_ORIGINS with your domain
- ✅ Enable firewall (ufw)
- ✅ Use HTTPS in production (Let's Encrypt)
- ✅ Keep Docker and system packages updated
- ✅ Regular database backups
- ✅ Monitor logs for suspicious activity

## Support

For detailed documentation:
- [Full Production Deployment Guide](./production_deployment.md)
- [API Documentation](./api_service.md)
- [Load Testing Guide](./load_testing_guide.md)

## Summary

✅ **5-Minute Setup**: Clone → Configure → Deploy
✅ **Optimized**: 50+ concurrent users, async architecture
✅ **Production Ready**: Health checks, logging, monitoring
✅ **Secure**: Firewall, SSL/TLS, strong passwords
✅ **Scalable**: Easy horizontal scaling
✅ **Monitored**: Comprehensive logging and health endpoints

Your application is now running at: **http://your-vm-ip**

Next steps:
1. Configure domain name and SSL
2. Set up automated backups
3. Configure monitoring (Prometheus/Grafana)
4. Load test with your expected traffic
