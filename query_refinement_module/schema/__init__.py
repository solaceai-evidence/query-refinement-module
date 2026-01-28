"""
Query refinement framework with Pydantic models and Jinja2 templates.
"""

# Core model (dataclass-based for now)
from .model import RefinementAspect

# Response models
from .response import (
    DimensionEvaluationResponse,
    QueryRefinementResponse,
)

# Registry
from .registry import (
    list_frameworks,
    get_framework,
    describe_framework,
    reload_from_env,
    get_last_load_error,
    FrameworkLoadError,
)

# Dependencies
from .dependencies import (
    validate_dependencies,
    sort_aspects_by_dependencies,
)

# Synthesis
from .synthesis import (
    SynthesisPromptBuilder,
    validate_synthesis_response,
)

# NOTE: The following are not yet implemented (Phase 2):
# - .models (Pydantic models: RefinementDimension, UserContext, etc.)
# - .loaders (YAML loaders for new Pydantic models)
# - .prompt_builder (Jinja2 prompt builder with Pydantic models)
# These will be implemented after current system is stabilized.

__version__ = "2.0.0"

__all__ = [
    # Core model
    "RefinementAspect",
    
    # Response models
    "DimensionEvaluationResponse",
    "QueryRefinementResponse",
    
    # Registry
    "list_frameworks",
    "get_framework",
    "describe_framework",
    "reload_from_env",
    "get_last_load_error",
    "FrameworkLoadError",
    
    # Dependencies
    "validate_dependencies",
    "sort_aspects_by_dependencies",
    
    # Synthesis
    "SynthesisPromptBuilder",
    "validate_synthesis_response",
]