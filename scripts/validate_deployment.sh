#!/bin/bash

# Production Deployment Validation Script
# This script validates the Docker Compose setup and environment configuration

set -e

echo "========================================"
echo "Docker Production Setup Validation"
echo "========================================"
echo ""

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Check functions
check_pass() {
    echo -e "${GREEN}✓${NC} $1"
}

check_fail() {
    echo -e "${RED}✗${NC} $1"
    exit 1
}

check_warn() {
    echo -e "${YELLOW}⚠${NC} $1"
}

# 1. Check Docker is installed
echo "Checking prerequisites..."
if command -v docker &> /dev/null; then
    check_pass "Docker is installed ($(docker --version))"
else
    check_fail "Docker is not installed"
fi

# 2. Check Docker Compose is installed
if docker compose version &> /dev/null; then
    check_pass "Docker Compose is installed ($(docker compose version))"
else
    check_fail "Docker Compose is not installed"
fi

# 3. Check required files exist
echo ""
echo "Checking required files..."
required_files=(
    "docker-compose.yml"
    "docker-compose.prod.yml"
    "Dockerfile"
    "gunicorn_conf.py"
    "nginx/nginx.conf"
    ".env.prod"
)

for file in "${required_files[@]}"; do
    if [ -f "$file" ]; then
        check_pass "Found $file"
    else
        check_fail "Missing required file: $file"
    fi
done

# 4. Check .env file exists
echo ""
echo "Checking environment configuration..."
if [ -f ".env" ]; then
    check_pass "Found .env file"
    
    # Check critical environment variables
    critical_vars=(
        "SECRET_KEY"
        "POSTGRES_PASSWORD"
        "QUERY_REFINEMENT_LLM_API_KEY"
    )
    
    missing_vars=()
    for var in "${critical_vars[@]}"; do
        if grep -q "^${var}=" .env && ! grep -q "^${var}=$" .env && ! grep -q "^${var}=__" .env; then
            check_pass "$var is configured"
        else
            missing_vars+=("$var")
        fi
    done
    
    if [ ${#missing_vars[@]} -gt 0 ]; then
        check_warn "Missing or unconfigured variables: ${missing_vars[*]}"
        echo "       Please configure these in .env file"
    fi
    
else
    check_warn ".env file not found - copy from .env.prod and configure"
fi

# 5. Validate Docker Compose configuration
echo ""
echo "Validating Docker Compose configuration..."
if docker compose -f docker-compose.yml -f docker-compose.prod.yml config > /dev/null 2>&1; then
    check_pass "Docker Compose configuration is valid"
else
    check_fail "Docker Compose configuration has errors"
fi

# 6. Check services defined
echo ""
echo "Checking service definitions..."
services=$(docker compose -f docker-compose.yml -f docker-compose.prod.yml config --services 2>/dev/null)
expected_services=("postgres" "redis" "api" "frontend" "nginx")

for service in "${expected_services[@]}"; do
    if echo "$services" | grep -q "^${service}$"; then
        check_pass "Service '$service' is defined"
    else
        check_fail "Service '$service' is missing"
    fi
done

# 7. Check Docker daemon is running
echo ""
echo "Checking Docker daemon..."
if docker info > /dev/null 2>&1; then
    check_pass "Docker daemon is running"
else
    check_fail "Docker daemon is not running"
fi

# 8. Check available disk space
echo ""
echo "Checking system resources..."
available_space=$(df -h . | awk 'NR==2 {print $4}')
check_pass "Available disk space: $available_space"

# 9. Check if ports are available
echo ""
echo "Checking port availability..."
http_port="80"
https_port="443"
if [ -f ".env" ]; then
    parsed_http=$(grep -E '^NGINX_HTTP_PORT=' .env | tail -n1 | cut -d'=' -f2)
    parsed_https=$(grep -E '^NGINX_HTTPS_PORT=' .env | tail -n1 | cut -d'=' -f2)
    if [ -n "$parsed_http" ]; then
        http_port="$parsed_http"
    fi
    if [ -n "$parsed_https" ]; then
        https_port="$parsed_https"
    fi
fi
ports=($http_port $https_port)
port_issues=()

for port in "${ports[@]}"; do
    if command -v netstat &> /dev/null; then
        if netstat -tuln 2>/dev/null | grep -q ":${port} "; then
            port_issues+=("$port")
        else
            check_pass "Port $port is available"
        fi
    elif command -v lsof &> /dev/null; then
        if lsof -i:${port} &> /dev/null; then
            port_issues+=("$port")
        else
            check_pass "Port $port is available"
        fi
    else
        check_warn "Cannot check port $port (netstat/lsof not available)"
    fi
done

if [ ${#port_issues[@]} -gt 0 ]; then
    check_warn "Ports in use: ${port_issues[*]}"
    echo "       These ports need to be available for production deployment"
fi

# 10. Check if containers are already running
echo ""
echo "Checking for running containers..."
if docker compose -f docker-compose.yml -f docker-compose.prod.yml ps --quiet 2>/dev/null | grep -q .; then
    check_warn "Some containers are already running"
    echo "       Run 'docker compose -f docker-compose.yml -f docker-compose.prod.yml ps' to see them"
else
    check_pass "No containers currently running"
fi

# 11. Optional: Check for existing Docker images
echo ""
echo "Checking Docker images..."
if docker images | grep -q "query-refinement-module"; then
    check_pass "Query Refinement Module images found"
else
    check_warn "No images built yet - run build command to create them"
fi

# Summary
echo ""
echo "========================================"
echo "Validation Summary"
echo "========================================"

if [ ${#port_issues[@]} -eq 0 ] && [ -f ".env" ] && [ ${#missing_vars[@]} -eq 0 ]; then
    echo -e "${GREEN}✓ All checks passed!${NC}"
    echo ""
    echo "Next steps:"
    echo "  1. Review configuration: cat .env"
    echo "  2. Build images: docker compose -f docker-compose.yml -f docker-compose.prod.yml build"
    echo "  3. Start services: docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d"
    echo "  4. Check logs: docker compose -f docker-compose.yml -f docker-compose.prod.yml logs -f"
    echo "  5. Test health: curl http://localhost/health"
else
    echo -e "${YELLOW}⚠ Some issues found - please review warnings above${NC}"
    echo ""
    echo "Required actions:"
    if [ ! -f ".env" ]; then
        echo "  - Copy .env.prod to .env and configure variables"
    fi
    if [ ${#missing_vars[@]} -gt 0 ]; then
        echo "  - Configure missing variables: ${missing_vars[*]}"
    fi
    if [ ${#port_issues[@]} -gt 0 ]; then
        echo "  - Free up ports: ${port_issues[*]}"
    fi
fi

echo ""
echo "For detailed deployment instructions, see:"
echo "  - docs/DEPLOYMENT.md"
echo "  - DEPLOYMENT_CHECKLIST.md"
echo ""
