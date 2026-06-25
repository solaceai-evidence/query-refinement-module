"""
Jinja2 templates for prompt generation.

Split into separate modules for maintainability:
- global_system: Global system prompt
- synthesis: Synthesis/integration prompts
- dimension: Dimension evaluation prompts
- user_context: Completed dimensions and dependencies
"""

from __future__ import annotations

from .global_system import GLOBAL_SYSTEM_PROMPT
from .user_context import DIMENSIONS_CLARIFIED_AND_DEPENDENCIES_TEMPLATE
from .synthesis import SYNTHESIS_TEMPLATE
from .dimension import DIMENSION_REFINEMENT_TEMPLATE
from .search_expansion import SEARCH_EXPANSION_TEMPLATE
from .normalization import NORMALIZATION_TEMPLATE
from .semantic_representation import SEMANTIC_REPRESENTATION_TEMPLATE
from .search_construction import SEARCH_CONSTRUCTION_TEMPLATE

__all__ = [
    "GLOBAL_SYSTEM_PROMPT",
    "SYNTHESIS_TEMPLATE",
    "SEARCH_EXPANSION_TEMPLATE",
    "DIMENSION_REFINEMENT_TEMPLATE",
    "DIMENSIONS_CLARIFIED_AND_DEPENDENCIES_TEMPLATE",
    "NORMALIZATION_TEMPLATE",
    "SEMANTIC_REPRESENTATION_TEMPLATE",
    "SEARCH_CONSTRUCTION_TEMPLATE",
]
