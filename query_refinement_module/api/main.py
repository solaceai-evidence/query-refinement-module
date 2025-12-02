"""
Main FastAPI application.
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from query_refinement_module.api.config import get_settings
from query_refinement_module.api.routes import auth, queries, feedback
from query_refinement_module.db.database import init_db

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

# Include routers
app.include_router(auth.router, prefix="/api")
app.include_router(queries.router, prefix="/api")
app.include_router(feedback.router, prefix="/api")


@app.on_event("startup")
def on_startup():
    """Initialize database on application startup."""
    init_db()


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
