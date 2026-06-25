"""
Query refinement framework with Pydantic models and Jinja2 templates.
"""

# Pydantic models (new - preferred)
from .models import (
    RefinementDimension,
    RefinementAspect,  # Alias for backward compatibility
    CompletedDimension,
    ExamplesCollection,
    ClearExample,
    NeedsRefinementExample,
    PartialExample,
    AmbiguousExample,
    OtherExample,
)

# Response models
from .response import (
    DimensionEvaluationResponse,
    QueryRefinementResponse,
    SearchAspect,
    AspectSafety,
    DEFAULT_ASPECT_SAFETY,
    ExpansionStrategy,
    SearchAspectAssessment,
    SearchAspectAssessmentResponse,
    SearchAspectAssessmentSummary,
    SearchExpansionLevel,
    SearchExpansionResponse,
    SearchExpansionContext,
    SearchExpansionInput,
    VocabularyHint,
    ConceptEntry,
    ResearchStatementResponse,
    SemanticRepresentationResponse,
    SearchConstructionResponse,
)

from .search_expansion import SearchExpansionPromptBuilder

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
    NormalizationPromptBuilder,
    SemanticRepresentationPromptBuilder,
    SearchConstructionPromptBuilder,
    validate_synthesis_response,
)

# Prompt builder
from .prompt_builder import (
    PromptBuilder,
    render_template,
    get_prompt_builder,
)

# Templates
from .templates import (
    GLOBAL_SYSTEM_PROMPT,
    SYNTHESIS_TEMPLATE,
    DIMENSION_REFINEMENT_TEMPLATE,
    DIMENSIONS_CLARIFIED_AND_DEPENDENCIES_TEMPLATE,
)

__version__ = "2.0.0"

__all__ = [
    # Pydantic models
    "RefinementDimension",
    "RefinementAspect",  # Alias
    "CompletedDimension",
    "ExamplesCollection",
    "ClearExample",
    "NeedsRefinementExample",
    "PartialExample",
    "AmbiguousExample",
    "OtherExample",
    
    # Response models
    "DimensionEvaluationResponse",
    "QueryRefinementResponse",
    "SearchAspect",
    "AspectSafety",
    "DEFAULT_ASPECT_SAFETY",
    "ExpansionStrategy",
    "SearchAspectAssessment",
    "SearchAspectAssessmentResponse",
    "SearchAspectAssessmentSummary",
    "SearchExpansionLevel",
    "SearchExpansionResponse",
    "SearchExpansionContext",
    "SearchExpansionInput",
    "SearchExpansionPromptBuilder",
    
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
    
    # Prompt builder
    "PromptBuilder",
    "render_template",
    "get_prompt_builder",

    # Templates
    "GLOBAL_SYSTEM_PROMPT",
    "SYNTHESIS_TEMPLATE",
    "DIMENSION_REFINEMENT_TEMPLATE",
    "DIMENSIONS_CLARIFIED_AND_DEPENDENCIES_TEMPLATE",
]