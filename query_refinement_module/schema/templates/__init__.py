"""
Jinja2 templates for prompt generation.

Split into separate modules for maintainability:
- global_system: Global system prompt
- synthesis: Synthesis/integration prompts
- dimension: Dimension evaluation prompts
- user_context: User context adaptation prompts
"""

from .global_system import GLOBAL_SYSTEM_PROMPT
from .synthesis import SYNTHESIS_TEMPLATE
from .dimension import (
    DIMENSION_REFINEMENT_TEMPLATE,
    EXAMPLES_SECTION_TEMPLATE,
    INITIAL_USER_INPUT_TEMPLATE,
    FOLLOW_USER_INPUT_TEMPLATE,
)
from .user_context import (
    USER_CONTEXT_PROFILE_TEMPLATE,
    DIMENSIONS_CLARIFIED_AND_DEPENDENCIES_TEMPLATE,
)

__all__ = [
    "GLOBAL_SYSTEM_PROMPT",
    "SYNTHESIS_TEMPLATE",
    "DIMENSION_REFINEMENT_TEMPLATE",
    "EXAMPLES_SECTION_TEMPLATE",
    "INITIAL_USER_INPUT_TEMPLATE",
    "FOLLOW_USER_INPUT_TEMPLATE",
    "USER_CONTEXT_PROFILE_TEMPLATE",
    "DIMENSIONS_CLARIFIED_AND_DEPENDENCIES_TEMPLATE",
]
