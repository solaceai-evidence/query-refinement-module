# Query Refinement API - Production Dockerfile
#
# Multi-stage build for optimized production image
# - Stage 1: Builder - Install dependencies
# - Stage 2: Runtime - Minimal image with application
#
# Build: docker build -t query-refinement-api:latest .
# Run: docker run -p 8000:8000 query-refinement-api:latest

# ============================================================================
# Builder Stage: Install dependencies
# ============================================================================
FROM python:3.12-slim as builder

# Install system dependencies required for building Python packages
RUN apt-get update && apt-get install -y \
    gcc \
    postgresql-client \
    libpq-dev \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install Poetry
ENV POETRY_VERSION=1.7.1 \
    POETRY_HOME="/opt/poetry" \
    POETRY_NO_INTERACTION=1 \
    POETRY_VIRTUALENVS_CREATE=false

RUN curl -sSL https://install.python-poetry.org | python3 -
ENV PATH="$POETRY_HOME/bin:$PATH"

# Set working directory
WORKDIR /app

# Copy dependency files
COPY pyproject.toml poetry.lock* ./

# Install dependencies (main/runtime dependencies only) into system Python
RUN poetry install --only main --no-root --no-interaction --no-ansi && \
    python -m pip install --no-cache-dir requests alembic gunicorn && \
    python -m pip check

# ============================================================================
# Runtime Stage: Minimal production image
# ============================================================================
FROM python:3.12-slim

# Install runtime dependencies only
RUN apt-get update && apt-get install -y \
    postgresql-client \
    libpq5 \
    && rm -rf /var/lib/apt/lists/*

# Create non-root user for security
RUN useradd -m -u 1000 appuser

# Set working directory
WORKDIR /app

# Copy installed Python packages from builder
COPY --from=builder /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages

# Copy application code
COPY --chown=appuser:appuser . .

# Runtime environment
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# Create directories for logs and data
RUN mkdir -p /app/logs /app/data && \
    chown -R appuser:appuser /app

# Switch to non-root user
USER appuser

# Expose port
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD python -c "import requests; requests.get('http://localhost:8000/health', timeout=5)" || exit 1

# Default command: Run with Gunicorn
CMD ["gunicorn", "-c", "gunicorn_conf.py", "query_refinement_module.api.main:app"]
