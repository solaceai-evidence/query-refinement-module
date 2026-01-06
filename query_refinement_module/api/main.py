"""Main FastAPI application with production-ready configuration.

Features:
- Environment-specific CORS configuration
- Health check endpoints for orchestration
- Structured error handling
- Request logging and tracing
- Rate limiting middleware
"""
import logging
from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from pydantic import ValidationError

# Load environment variables from .env file
load_dotenv()

from query_refinement_module.api.config import get_settings
from query_refinement_module.api.routes import auth, queries, feedback, refinement
from query_refinement_module.api.exceptions import QueryRefinementException
from query_refinement_module.api.rate_limit import RateLimitMiddleware

logger = logging.getLogger(__name__)
settings = get_settings()

# Initialize FastAPI app
app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    description="AI-powered query refinement API for scientific literature search",
    docs_url="/docs",
    redoc_url="/redoc",
)

# Configure CORS with environment-specific settings
logger.info(
    f"Configuring CORS | environment={settings.environment}, "
    f"origins={len(settings.allowed_origins)}, "
    f"credentials={settings.cors_allow_credentials}"
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=settings.cors_allow_credentials,
    allow_methods=settings.cors_allow_methods,
    allow_headers=settings.cors_allow_headers,
    max_age=settings.cors_max_age,
)

# Configure rate limiting (60 requests per minute)
app.add_middleware(
    RateLimitMiddleware,
    requests_per_minute=60,
    exempt_paths=["/docs", "/redoc", "/openapi.json", "/health", "/"]
)

# Exception handlers
@app.exception_handler(QueryRefinementException)
async def query_refinement_exception_handler(request: Request, exc: QueryRefinementException):
    """Handle custom query refinement exceptions."""
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.message}
    )


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    """Handle Pydantic validation errors with detailed messages."""
    errors = []
    for error in exc.errors():
        field = " -> ".join(str(loc) for loc in error["loc"])
        errors.append({
            "field": field,
            "message": error["msg"],
            "type": error["type"]
        })
    
    return JSONResponse(
        status_code=422,
        content={
            "detail": "Validation error",
            "errors": errors
        }
    )


# Health check endpoints (for load balancers and orchestration)
@app.get("/health", tags=["Health"])
async def health_check():
    """
    Basic health check endpoint.
    
    Returns 200 OK if the application is running.
    Use this for container health checks and load balancer probes.
    """
    return {
        "status": "healthy",
        "service": settings.app_name,
        "version": settings.app_version,
        "environment": settings.environment
    }


@app.get("/ready", tags=["Health"])
async def readiness_check():
    """
    Readiness check endpoint with dependency validation.
    
    Returns 200 OK if the application can serve requests.
    Checks:
    - Database connectivity
    - Redis connectivity (if configured)
    
    Use this for Kubernetes readiness probes.
    """
    from query_refinement_module.db.database import engine
    
    checks = {
        "status": "ready",
        "checks": {}
    }
    
    # Check database connectivity
    try:
        from sqlalchemy import text
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        checks["checks"]["database"] = "ok"
    except Exception as e:
        logger.error(f"Database health check failed: {e}")
        checks["checks"]["database"] = f"error: {str(e)}"
        checks["status"] = "unhealthy"
    
    # Check Redis connectivity (if using Redis for sessions)
    if settings.session_storage_backend == "redis":
        try:
            import redis
            r = redis.from_url(settings.redis_url, socket_connect_timeout=2)
            r.ping()
            checks["checks"]["redis"] = "ok"
        except Exception as e:
            logger.warning(f"Redis health check failed: {e}")
            checks["checks"]["redis"] = f"warning: {str(e)}"
            # Don't mark as unhealthy - Redis failure is degraded but functional
    
    status_code = 200 if checks["status"] == "ready" else 503
    return JSONResponse(content=checks, status_code=status_code)


# Root endpoint
@app.get("/", tags=["Root"])
async def root():
    """API root endpoint with service information."""
    return {
        "service": settings.app_name,
        "version": settings.app_version,
        "environment": settings.environment,
        "docs": "/docs",
        "health": "/health",
        "ready": "/ready"
    }


# Include routers
app.include_router(auth.router, prefix="/api")
app.include_router(queries.router, prefix="/api")
app.include_router(feedback.router, prefix="/api")
app.include_router(refinement.router, prefix="/api")


@app.on_event("startup")
def on_startup():
    """
    Application startup tasks with enhanced logging.
    
    Note: Database schema should be managed via Alembic migrations.
    Run 'alembic upgrade head' before starting the server.
    """
    logger.info(
        f"Application starting | environment={settings.environment}, "
        f"version={settings.app_version}, database={settings.database_url.split('@')[-1] if '@' in settings.database_url else 'sqlite'}"
    )
    logger.info(f"CORS origins: {settings.allowed_origins}")
    logger.info(f"Database pooling: size={settings.db_pool_size}, max_overflow={settings.db_max_overflow}")
    logger.info(f"Health checks available at: /health, /ready")
