"""
FastAPI dependencies for the query refinement API.
"""
from functools import lru_cache
from typing import Optional
from urllib.parse import urlsplit, urlunsplit

from query_refinement_module.core import QueryRefinementManager
from query_refinement_module.providers import LiteLLMProvider
from query_refinement_module.settings import LLMSettings
from query_refinement_module.schema import registry
from .config import get_settings
from .session_manager import SessionManager, InMemorySessionManager


# Load frameworks from environment on module import
try:
    registry.reload_from_env(raise_on_error=False)
except Exception:
    pass  # Continue even if framework loading fails


def _local_redis_fallback_url(redis_url: str) -> Optional[str]:
    """Map the Docker Redis hostname to localhost for local development runs."""
    parsed = urlsplit(redis_url)
    if parsed.hostname != "redis":
        return None

    netloc = parsed.netloc.replace("redis", "localhost", 1)
    return urlunsplit((parsed.scheme, netloc, parsed.path, parsed.query, parsed.fragment))


@lru_cache()
def get_refinement_manager() -> QueryRefinementManager:
    """
    Get or create a singleton RefinementManager instance.
    
    This dependency provides a configured manager with:
    - LiteLLM provider for LLM completions
    - Uses initialize_sequential for analysis (analyzer deprecated)
    """
    # Get LLM settings from environment
    llm_settings = LLMSettings.from_env(require_model=False, load_env_file=True)
    
    # Initialize LLM provider
    llm_provider = LiteLLMProvider(**llm_settings.as_provider_kwargs())
    
    # Create manager (analyzer removed in v2.0 - uses initialize_sequential)
    manager = QueryRefinementManager(
        llm_provider=llm_provider,
        default_temperature=getattr(llm_settings, "temperature", 0.0),
        default_max_tokens=getattr(llm_settings, "max_tokens", 4096) or 4096,
        terminal_reinforcement_threshold=llm_settings.terminal_reinforcement_threshold
    )
    
    return manager


def get_llm_provider() -> LiteLLMProvider:
    """
    Returns the shared LiteLLMProvider from the singleton refinement manager.

    Using the manager's provider ensures circuit-breaker and rate-limiter state
    is shared across all routes rather than split across two instances.
    """
    return get_refinement_manager().llm_provider


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
            key_prefix=settings.session_key_prefix,
            lock_timeout_seconds=settings.session_lock_timeout_seconds,
            lock_blocking_timeout_seconds=settings.session_lock_blocking_timeout_seconds,
        )
        return manager
    except Exception as e:
        import logging

        fallback_redis_url = _local_redis_fallback_url(settings.redis_url)
        if fallback_redis_url:
            try:
                logging.warning(
                    "Redis unavailable at %s (%s). Retrying with local Redis URL %s.",
                    settings.redis_url,
                    e,
                    fallback_redis_url,
                )
                return SessionManager(
                    redis_url=fallback_redis_url,
                    session_ttl_seconds=settings.session_ttl_seconds,
                    key_prefix=settings.session_key_prefix,
                    lock_timeout_seconds=settings.session_lock_timeout_seconds,
                    lock_blocking_timeout_seconds=settings.session_lock_blocking_timeout_seconds,
                )
            except Exception as fallback_exc:
                logging.warning(
                    "Local Redis fallback unavailable (%s). Using in-memory session storage.",
                    fallback_exc,
                )

        logging.warning(
            "Redis unavailable (%s). Using in-memory session storage. "
            "Sessions will NOT persist across server restarts.",
            e
        )
        # Return an in-memory fallback manager
        return InMemorySessionManager(
            session_ttl_seconds=settings.session_ttl_seconds
        )
