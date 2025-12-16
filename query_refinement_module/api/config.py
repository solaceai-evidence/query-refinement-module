"""
FastAPI application configuration and settings.
"""
from functools import lru_cache
from typing import List, Optional

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings automatically loaded from environment variables."""
    
    # App metadata
    app_name: str = "Query Refinement API"
    app_version: str = "0.2.0"
    debug: bool = False
    
    # Database
    database_url: str = Field(default="sqlite:///query_refinement.db")
    
    # Security
    secret_key: str = Field(default="your-secret-key-change-this-in-production")
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 30
    
    # CORS
    allowed_origins: List[str] = ["http://localhost:3000", "http://localhost:8000"]
    
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
    
    # Parallel Execution Configuration
    parallel_execution_enabled: bool = Field(default=False, description="Enable parallel aspect analysis")
    parallel_max_concurrent: int = Field(default=5, description="Max concurrent aspects per dependency level")
    parallel_max_retries: int = Field(default=3, description="Max retry attempts for rate-limited calls")
    parallel_backoff_base_delay: float = Field(default=1.0, description="Base delay for exponential backoff (seconds)")
    parallel_backoff_max_delay: float = Field(default=60.0, description="Max delay for exponential backoff (seconds)")
    parallel_backoff_multiplier: float = Field(default=2.0, description="Exponential multiplier for backoff")
    parallel_backoff_jitter: float = Field(default=0.1, description="Jitter factor for backoff (0.0-1.0)")
    
    # Configuration using pydantic-settings v2 style
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,  # DATABASE_URL or database_url both work
        extra="ignore"  # Ignore extra fields from .env that aren't defined here
    )


@lru_cache()
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()
