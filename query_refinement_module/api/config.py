"""
FastAPI application configuration and settings.
"""
from pydantic_settings import BaseSettings
from functools import lru_cache
import os
from dotenv import load_dotenv

load_dotenv()


class Settings(BaseSettings):
    """Application settings."""
    
    # App metadata
    app_name: str = "Query Refinement API"
    app_version: str = "0.2.0"
    debug: bool = False
    
    # Database
    database_url: str = os.getenv("DATABASE_URL", "sqlite:///query_refinement.db")
    
    # Security
    secret_key: str = os.getenv("SECRET_KEY", "your-secret-key-change-this-in-production")
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 30
    
    # CORS
    allowed_origins: list = ["http://localhost:3000", "http://localhost:8000"]
    
    # LLM Provider
    refinement_framework_path: str = os.getenv("REFINEMENT_FRAMEWORK_PATH", "/dev/null")
    query_refinement_llm_model: str = os.getenv("QUERY_REFINEMENT_LLM_MODEL", "anthropic/claude-sonnet-4-20250514")
    query_refinement_llm_api_key: str = os.getenv("QUERY_REFINEMENT_LLM_API_KEY", "")
    query_refinement_llm_temperature: float = float(os.getenv("QUERY_REFINEMENT_LLM_TEMPERATURE", "0.2"))
    
    class Config:
        env_file = ".env"
        extra = "ignore"  # Ignore extra fields from .env


@lru_cache()
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()
