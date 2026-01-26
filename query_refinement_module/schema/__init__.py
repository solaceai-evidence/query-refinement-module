"""
Query refinement framework with Pydantic models and Jinja2 templates.
"""

# Core models
from .models import (
    RefinementDimension,
    UserContext,
    CompletedDimension,
    ExamplesCollection,
    ResponseFormat,
)

# Response models
from .response import (
    DimensionEvaluationResponse,
    QueryRefinementResponse,
    QueryRefinementResponse,  # Backward compatibility
)

# Loaders
from .loaders import (
    load_dimension_from_yaml,
    load_user_context_from_yaml,
    load_dimensions_from_directory,
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
    sort_dimensions_by_dependencies,
)

# Prompt builders
from .prompt_builder import (
    PromptBuilder,
    create_dimension_prompt,
    create_synthesis_prompt as create_synthesis_prompt_new,
)

# Synthesis
from .synthesis import (
    SynthesisPromptBuilder,
    create_synthesis_prompt,
    validate_synthesis_response,
)

__version__ = "2.0.0"

__all__ = [
    # Models
    "RefinementDimension",
    "UserContext",
    "CompletedDimension",
    "ExamplesCollection",
    "ResponseFormat",
    
    # Response models
    "DimensionEvaluationResponse",
    "QueryRefinementResponse",
    "QueryRefinementResponse",
    
    # Loaders
    "load_dimension_from_yaml",
    "load_user_context_from_yaml",
    "load_dimensions_from_directory",
    
    # Registry
    "list_frameworks",
    "get_framework",
    "describe_framework",
    "reload_from_env",
    "get_last_load_error",
    "FrameworkLoadError",
    
    # Dependencies
    "validate_dependencies",
    "sort_dimensions_by_dependencies",
    
    # Prompt builders
    "PromptBuilder",
    "create_dimension_prompt",
    "create_synthesis_prompt",
    "validate_synthesis_response",
]