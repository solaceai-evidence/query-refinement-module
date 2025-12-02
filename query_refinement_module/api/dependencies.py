"""
FastAPI dependencies for the query refinement API.
"""
from functools import lru_cache

from query_refinement_module.core import QueryRefinementManager
from query_refinement_module.providers import LiteLLMProvider
from query_refinement_module.analyzers import LLMQueryAnalyzer
from query_refinement_module.settings import LLMSettings
from query_refinement_module.schema import registry


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
