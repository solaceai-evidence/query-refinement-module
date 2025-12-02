"""
Main FastAPI application.
"""
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from pydantic import ValidationError

from query_refinement_module.api.config import get_settings
from query_refinement_module.api.routes import auth, queries, feedback, refinement
from query_refinement_module.api.exceptions import QueryRefinementException
from query_refinement_module.api.rate_limit import RateLimitMiddleware

settings = get_settings()

# Initialize FastAPI app
app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    description="AI-powered query refinement API for scientific literature search",
    docs_url="/docs",
    redoc_url="/redoc",
)

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
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


# Include routers
app.include_router(auth.router, prefix="/api")
app.include_router(queries.router, prefix="/api")
app.include_router(feedback.router, prefix="/api")
app.include_router(refinement.router, prefix="/api")


@app.on_event("startup")
def on_startup():
    """
    Application startup tasks.
    
    Note: Database schema should be managed via Alembic migrations.
    Run 'alembic upgrade head' before starting the server.
    """
    # Database is now managed by Alembic migrations
    # Run: poetry run alembic upgrade head
    pass


@app.get("/")
def root():
    """Root endpoint with API information."""
    return {
        "message": "Welcome to Query Refinement API",
        "version": settings.app_version,
        "docs": "/docs",
        "redoc": "/redoc"
    }


@app.get("/health")
def health_check():
    """Health check endpoint."""
    return {"status": "healthy"}
