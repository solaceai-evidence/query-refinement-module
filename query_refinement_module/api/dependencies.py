"""
FastAPI dependencies for the query refinement API.
"""
from functools import lru_cache
from typing import Optional

from query_refinement_module.core import QueryRefinementManager
from query_refinement_module.providers import LiteLLMProvider
from query_refinement_module.analyzers import LLMQueryAnalyzer
from query_refinement_module.settings import LLMSettings
from query_refinement_module.schema import registry
from query_refinement_module.parallel import ParallelConfig
from query_refinement_module.rate_limiter import (
    TokenBucketRateLimiter,
    BackoffStrategy,
)
from query_refinement_module.interfaces import RateLimitConfig
from .config import get_settings


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
    - Query analyzer for aspect analysis
    """
    # Get LLM settings from environment
    llm_settings = LLMSettings.from_env(require_model=False)
    
    # Initialize LLM provider
    llm_provider = LiteLLMProvider(**llm_settings.as_provider_kwargs())
    
    # Initialize query analyzer
    query_analyzer = LLMQueryAnalyzer(
        llm_provider=llm_provider,
        **llm_settings.as_analyzer_kwargs()
    )
    
    # Create manager
    manager = QueryRefinementManager(
        llm_provider=llm_provider,
        query_analyzer=query_analyzer
    )
    
    return manager


def get_parallel_config() -> Optional[ParallelConfig]:
    """
    Get parallel execution configuration from settings.
    
    Returns None if parallel execution is disabled, otherwise returns
    a configured ParallelConfig with rate limiting.
    """
    settings = get_settings()
    
    if not settings.parallel_execution_enabled:
        return None
    
    # Create rate limiter for parallel execution
    rate_limit_config = RateLimitConfig(
        requests_per_minute=settings.llm_rate_limit_rpm,
        tokens_per_minute=settings.llm_rate_limit_tpm,
        max_concurrent=settings.llm_max_concurrent,
        adaptive_backoff=settings.llm_adaptive_rate_limiting,
        adaptive_decrease_factor=settings.llm_adaptive_decrease_factor,
        adaptive_increase_factor=settings.llm_adaptive_increase_factor,
        adaptive_increase_interval=settings.llm_adaptive_increase_interval,
    )
    
    rate_limiter = TokenBucketRateLimiter(
        config=rate_limit_config,
        scope="global"
    )
    
    # Create backoff strategy
    backoff_strategy = BackoffStrategy(
        base_delay=settings.parallel_backoff_base_delay,
        max_delay=settings.parallel_backoff_max_delay,
        multiplier=settings.parallel_backoff_multiplier,
        jitter=settings.parallel_backoff_jitter,
    )
    
    # Create parallel config
    parallel_config = ParallelConfig(
        enabled=True,
        max_concurrent=settings.parallel_max_concurrent,
        rate_limiter=rate_limiter,
        backoff_strategy=backoff_strategy,
        max_retries=settings.parallel_max_retries,
    )
    
    return parallel_config

