"""
FastAPI application configuration and settings.
"""
from functools import lru_cache
from typing import List

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
