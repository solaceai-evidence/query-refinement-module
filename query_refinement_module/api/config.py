"""
FastAPI application configuration and settings.
"""
from functools import lru_cache
from typing import List, Optional

import json
from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def _env_json_loads(value):
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return []
        if stripped.startswith("["):
            return json.loads(stripped)
        return [origin.strip() for origin in stripped.split(",") if origin.strip()]
    return value


class Settings(BaseSettings):
    """
    Application settings automatically loaded from environment variables.
    
    Supports environment-specific configuration for development, staging, and production.
    Set ENVIRONMENT=production to enable production settings.
    """
    
    # App metadata
    app_name: str = "Query Refinement API"
    app_version: str = "0.3.0"
    debug: bool = False
    environment: str = Field(default="development", description="Environment: development, staging, production")
    
    # Database Configuration
    # SQLite for development: sqlite:///query_refinement.db
    # PostgreSQL for production: postgresql://user:password@host:port/dbname
    database_url: str = Field(default="sqlite:///query_refinement.db")
    
    # Database Connection Pooling (for PostgreSQL)
    db_pool_size: int = Field(default=5, description="Number of persistent connections to maintain")
    db_max_overflow: int = Field(default=10, description="Max connections beyond pool_size")
    db_pool_timeout: float = Field(default=30.0, description="Seconds to wait for connection from pool")
    db_pool_recycle: int = Field(default=3600, description="Recycle connections after N seconds")
    db_pool_pre_ping: bool = Field(default=True, description="Test connections before using")
    db_echo: bool = Field(default=False, description="Log all SQL queries")
    
    # Security
    secret_key: str = Field(default="your-secret-key-change-this-in-production")
    allow_registration: bool = Field(default=False, description="Allow self-service user registration")
    enforce_workflow_limit: bool = Field(
        default=True,
        description="If true, non-superusers are limited to one completed workflow",
    )
    
    @model_validator(mode='after')
    def validate_secret_key_in_production(self) -> 'Settings':
        """Ensure SECRET_KEY is not the default or weak in production."""
        _INSECURE_DEFAULTS = {
            "your-secret-key-change-this-in-production",
            "please-change-this-secret-key-in-production",
            "generate-with-python-c-import-secrets-print-secrets-token-urlsafe-32",
        }
        if self.environment == "production":
            key = self.secret_key or ""
            if not key or key in _INSECURE_DEFAULTS:
                raise ValueError(
                    "SECRET_KEY must be set to a secure value in production. "
                    "Generate one with: python -c \"import secrets; print(secrets.token_urlsafe(32))\""
                )
            if len(key) < 32:
                raise ValueError(
                    "SECRET_KEY must be at least 32 characters long. "
                    "Generate one with: python -c \"import secrets; print(secrets.token_urlsafe(32))\""
                )
        return self
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 480  # 8 hours (increased from 30 minutes)

    # Service-to-service integration auth (prototype)
    integration_api_key: Optional[str] = Field(
        default=None,
        description="Optional API key for trusted external integrations (X-API-Key header)",
    )
    integration_service_username: str = Field(
        default="api_integration_service",
        description="Username for internal service account used by API integrations",
    )
    
    # CORS Configuration (environment-specific)
    # Development: localhost origins
    # Production: Add your frontend domains, e.g., "https://yourdomain.com,https://app.yourdomain.com"
    allowed_origins_raw: str = Field(
        default="http://localhost:3000,http://localhost:5173,http://localhost:8001",
        description="CORS allowed origins (comma-separated in env: ALLOWED_ORIGINS=https://app.com,https://www.app.com)"
    )

    @property
    def allowed_origins(self) -> List[str]:
        return _env_json_loads(self.allowed_origins_raw)
    cors_allow_credentials: bool = Field(default=True, description="Allow credentials in CORS requests")
    cors_allow_methods: List[str] = Field(default=["GET", "POST", "PUT", "DELETE", "OPTIONS"], description="Allowed HTTP methods")
    cors_allow_headers: List[str] = Field(default=["*"], description="Allowed headers")
    cors_max_age: int = Field(default=600, description="CORS preflight cache duration in seconds")
    
    # Logging Configuration
    log_level: str = Field(default="INFO", description="Logging level: DEBUG, INFO, WARNING, ERROR, CRITICAL")
    log_format: str = Field(default="text", description="Log format: text or json (use json for production)")
    log_file: Optional[str] = Field(default=None, description="Path to log file (None = stdout only)")
    
    # Server Configuration
    host: str = Field(default="0.0.0.0", description="Server bind address")
    port: int = Field(default=8001, description="Server port")
    workers: int = Field(default=4, description="Number of Gunicorn worker processes (production)")
    worker_class: str = Field(default="uvicorn.workers.UvicornWorker", description="Gunicorn worker class")
    worker_timeout: int = Field(default=120, description="Worker timeout in seconds")
    keepalive: int = Field(default=5, description="Keepalive seconds")
    max_requests: int = Field(default=1000, description="Max requests per worker before restart")
    max_requests_jitter: int = Field(default=100, description="Jitter for max_requests")
    
    # LLM Provider (automatically loaded from .env with case-insensitive matching)
    refinement_framework_path: str = Field(default="/dev/null")
    query_refinement_llm_model: str = Field(default="anthropic/claude-sonnet-4-20250514")
    query_refinement_llm_api_key: str = Field(default="")
    query_refinement_llm_temperature: float = Field(default=0.2)
    
    # Rate Limiting Configuration
    # Global limits (across all users and sessions)
    llm_rate_limit_rpm: int = Field(default=50, description="Global requests per minute limit")
    llm_rate_limit_tpm: Optional[int] = Field(default=None, description="Global tokens per minute limit (None = unlimited)")
    llm_max_concurrent: int = Field(default=5, description="Global max concurrent requests")
    
    # Per-user limits (fairness in multi-tenant deployments)
    llm_rate_limit_per_user_rpm: int = Field(default=10, description="Per-user requests per minute limit")
    llm_max_concurrent_per_user: int = Field(default=3, description="Per-user max concurrent requests")
    
    # Adaptive rate limiting
    llm_adaptive_rate_limiting: bool = Field(default=True, description="Enable adaptive rate limit adjustments")
    llm_adaptive_decrease_factor: float = Field(default=0.8, description="Decrease factor on 429 errors (0.8 = 20% reduction)")
    llm_adaptive_increase_factor: float = Field(default=1.05, description="Increase factor during recovery (1.05 = 5% increase)")
    llm_adaptive_increase_interval: int = Field(default=60, description="Recovery adjustment interval in seconds")
    
    # Redis Configuration (shared across features)
    redis_url: str = Field(default="redis://localhost:6379/0", description="Redis URL for caching and rate limiting")
    
    # Session Management
    session_storage_backend: str = Field(default="redis", description="Session storage: 'redis' or 'memory'")
    session_ttl_seconds: int = Field(default=3600, description="Session expiration time in seconds (1 hour)")
    session_key_prefix: str = Field(default="qr:session:", description="Redis key prefix for sessions")
    
    # Rate limiter backend
    rate_limiter_backend: str = Field(default="memory", description="Rate limiter backend: 'memory' or 'redis'")
    redis_rate_limit_prefix: str = Field(default="qr:ratelimit", description="Redis key prefix for rate limit data")
    
    # Configuration using pydantic-settings v2 style
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,  # DATABASE_URL or database_url both work
        extra="ignore",  # Ignore extra fields from .env that aren't defined here
        env_json_loads=_env_json_loads,
    )


@lru_cache()
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()
