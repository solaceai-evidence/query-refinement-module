#!/bin/bash
# Production startup script for Query Refinement API
#
# This script performs pre-flight checks and starts the application safely.
# It should be run in the production environment before launching the server.
#
# Usage:
#   chmod +x start_production.sh
#   ./start_production.sh

set -e  # Exit on error

echo "=========================================="
echo "Query Refinement API - Production Startup"
echo "=========================================="
echo ""

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Function to print colored messages
print_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

print_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

print_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

resolve_database_url() {
    if [ -n "${DATABASE_URL:-}" ]; then
        echo "$DATABASE_URL"
        return
    fi

    if [ -n "${POSTGRES_USER:-}" ] && [ -n "${POSTGRES_PASSWORD:-}" ] && [ -n "${POSTGRES_DB:-}" ]; then
        local host="${POSTGRES_HOST:-localhost}"
        local port="${POSTGRES_PORT:-5432}"
        echo "postgresql+psycopg2://${POSTGRES_USER}:${POSTGRES_PASSWORD}@${host}:${port}/${POSTGRES_DB}"
        return
    fi

    echo ""
}

# Check if running in production environment
if [ "${ENVIRONMENT}" != "production" ] && [ "${ENVIRONMENT}" != "staging" ]; then
    print_warn "ENVIRONMENT is not set to 'production' or 'staging'"
    print_warn "Current ENVIRONMENT: ${ENVIRONMENT:-development}"
    print_warn "Set ENVIRONMENT=production for production deployment"
    echo ""
fi

# 1. Check required environment variables
print_info "Checking required environment variables..."

required_vars=(
    "SECRET_KEY"
)

# API key is only required for cloud providers (Anthropic, OpenAI).
# Self-hosted backends (Ollama, vLLM) set an empty or placeholder value.
EFFECTIVE_LLM_API_BASE="${LLM_API_BASE:-}"
EFFECTIVE_LLM_API_KEY="${LLM_API_KEY:-}"
if [ -z "${EFFECTIVE_LLM_API_BASE}" ]; then
    if [ -z "${EFFECTIVE_LLM_API_KEY}" ]; then
        required_vars+=("LLM_API_KEY")
    fi
fi

missing_vars=()
for var in "${required_vars[@]}"; do
    if [ -z "${!var}" ]; then
        missing_vars+=("$var")
    fi
done

EFFECTIVE_DATABASE_URL="$(resolve_database_url)"
if [ -z "$EFFECTIVE_DATABASE_URL" ]; then
    missing_vars+=("DATABASE_URL or POSTGRES_USER/POSTGRES_PASSWORD/POSTGRES_DB")
fi

if [ ${#missing_vars[@]} -gt 0 ]; then
    print_error "Missing required environment variables:"
    for var in "${missing_vars[@]}"; do
        echo "  - $var"
    done
    print_error "Please set these variables in .env or environment"
    exit 1
fi

print_info "✓ All required environment variables are set"
echo ""

# 2. Check database connectivity
print_info "Checking database connectivity..."

# Extract database info from resolved DB URL
if [[ $EFFECTIVE_DATABASE_URL == postgresql://* ]] || [[ $EFFECTIVE_DATABASE_URL == postgresql+psycopg2://* ]]; then
    print_info "Using PostgreSQL database"
    
    # Test connection with timeout
    if poetry run python -c "from sqlalchemy import create_engine; engine = create_engine('${EFFECTIVE_DATABASE_URL}', connect_args={'connect_timeout': 5}); conn = engine.connect(); conn.close(); print('OK')" > /dev/null 2>&1; then
        print_info "✓ Database connection successful"
    else
        print_error "Failed to connect to database"
        print_error "Please check DATABASE_URL (or POSTGRES_* values) and ensure PostgreSQL is running"
        exit 1
    fi
elif [[ $EFFECTIVE_DATABASE_URL == sqlite://* ]]; then
    print_warn "Using SQLite database (not recommended for production)"
    print_warn "Consider migrating to PostgreSQL for better performance"
else
    print_error "Unsupported database URL: ${EFFECTIVE_DATABASE_URL}"
    exit 1
fi
echo ""

# 3. Check Redis connectivity (if configured)
EFFECTIVE_RATE_LIMITER_BACKEND="${API_RATE_LIMITER_BACKEND:-memory}"
if [ "${SESSION_STORAGE_BACKEND}" == "redis" ] || [ "${EFFECTIVE_RATE_LIMITER_BACKEND}" == "redis" ]; then
    print_info "Checking Redis connectivity..."
    
    if poetry run python -c "import redis; r = redis.from_url('${REDIS_URL}', socket_connect_timeout=5); r.ping(); print('OK')" > /dev/null 2>&1; then
        print_info "✓ Redis connection successful"
    else
        print_error "Failed to connect to Redis"
        print_error "Please check REDIS_URL and ensure Redis is running"
        print_error "Or set SESSION_STORAGE_BACKEND=memory and API_RATE_LIMITER_BACKEND=memory"
        exit 1
    fi
    echo ""
fi

# 4. Run database migrations
print_info "Running database migrations..."
if poetry run alembic upgrade head; then
    print_info "✓ Database migrations completed successfully"
else
    print_error "Database migration failed"
    print_error "Please check the error above and fix any issues"
    exit 1
fi
echo ""

# 5. Verify framework configuration
print_info "Checking refinement framework configuration..."
if [ -f "${REFINEMENT_FRAMEWORK_PATH}" ]; then
    print_info "✓ Framework file found: ${REFINEMENT_FRAMEWORK_PATH}"
else
    print_error "Framework file not found: ${REFINEMENT_FRAMEWORK_PATH}"
    print_error "Please set REFINEMENT_FRAMEWORK_PATH to a valid YAML file"
    exit 1
fi
echo ""

# 6. Check disk space
print_info "Checking disk space..."
disk_usage=$(df -h . | tail -1 | awk '{print $5}' | sed 's/%//')
if [ "$disk_usage" -gt 90 ]; then
    print_warn "Disk usage is high: ${disk_usage}%"
    print_warn "Consider cleaning up logs or increasing disk space"
else
    print_info "✓ Disk usage: ${disk_usage}%"
fi
echo ""

# 7. Display configuration summary
print_info "Configuration Summary:"
echo "  Environment: ${ENVIRONMENT:-development}"
echo "  Database: ${EFFECTIVE_DATABASE_URL#*@}"  # Hide credentials
echo "  Redis: ${REDIS_URL:-not configured}"
echo "  Workers: ${WORKERS:-4}"
  echo "  Worker Timeout: ${WORKER_TIMEOUT:-180}s"
echo "  Log Level: ${LOG_LEVEL:-INFO}"
echo "  Log Format: ${LOG_FORMAT:-json}"
echo "  CORS Origins: ${ALLOWED_ORIGINS:-localhost}"
echo ""

# 8. Start the application
print_info "Starting application with Gunicorn..."
echo "=========================================="
echo ""

# Start Gunicorn with configuration
exec poetry run gunicorn -c gunicorn_conf.py query_refinement_module.api.main:app
