"""
FastAPI dependencies for the query refinement API.
"""
from functools import lru_cache
from typing import Optional

from query_refinement_module.core import QueryRefinementManager
from query_refinement_module.providers import LiteLLMProvider
from query_refinement_module.settings import LLMSettings
from query_refinement_module.schema import registry
from query_refinement_module.rate_limiter import (
    TokenBucketRateLimiter,
    BackoffStrategy,
)
from query_refinement_module.interfaces import RateLimitConfig
from .config import get_settings
from .session_manager import SessionManager, InMemorySessionManager


# Load frameworks from environment on module import
try:
    registry.reload_from_env(raise_on_error=False)
except Exception:
    pass  # Continue even if framework loading fails


@lru_cache()
def get_refinement_manager() -> QueryRefinementManager:
    """
    Get or create a singleton RefinementManager instance.
    
    This dependency provides a configured manager with:
    - LiteLLM provider for LLM completions
    - Uses initialize_sequential for analysis (analyzer deprecated)
    """
    # Get LLM settings from environment
    llm_settings = LLMSettings.from_env(require_model=False)
    
    # Initialize LLM provider
    llm_provider = LiteLLMProvider(**llm_settings.as_provider_kwargs())
    
    # Create manager (analyzer removed in v2.0 - uses initialize_sequential)
    manager = QueryRefinementManager(
        llm_provider=llm_provider,
        terminal_reinforcement_threshold=llm_settings.terminal_reinforcement_threshold
    )
    
    return manager


@lru_cache()
def get_session_manager() -> SessionManager:
    """
    Get or create a singleton SessionManager instance.
    
    Provides Redis-backed session storage for QueryRefinementSession objects.
    Falls back to in-memory if Redis is unavailable (logs warning).
    """
    settings = get_settings()
    
    try:
        manager = SessionManager(
            redis_url=settings.redis_url,
            session_ttl_seconds=settings.session_ttl_seconds,
            key_prefix=settings.session_key_prefix
        )
        return manager
    except Exception as e:
        import logging
        logging.warning(
            "Redis unavailable (%s). Using in-memory session storage. "
            "Sessions will NOT persist across server restarts.",
            e
        )
        # Return an in-memory fallback manager
        return InMemorySessionManager(
            session_ttl_seconds=settings.session_ttl_seconds
        )
