"""
Jinja2 templates for prompt generation.

Split into separate modules for maintainability:
- global_system: Global system prompt
- synthesis: Synthesis/integration prompts
- dimension: Dimension evaluation prompts
- user_context: User context adaptation prompts
"""

from __future__ import annotations

import os

_PROMPT_VARIANT_ENV = "QUERY_REFINEMENT_PROMPT_VARIANT"


def _use_open_llm_templates() -> bool:
    variant = os.getenv(_PROMPT_VARIANT_ENV, "default").strip().lower()
    return variant in {"open_llm", "open-llm", "open", "qwen", "ollama"}


if _use_open_llm_templates():
    from .global_system_open_llm import GLOBAL_SYSTEM_PROMPT
    from .user_context_open_llm import (
        USER_CONTEXT_PROFILE_TEMPLATE,
        DIMENSIONS_CLARIFIED_AND_DEPENDENCIES_TEMPLATE,
    )
else:
    from .global_system import GLOBAL_SYSTEM_PROMPT
    from .user_context import (
        USER_CONTEXT_PROFILE_TEMPLATE,
        DIMENSIONS_CLARIFIED_AND_DEPENDENCIES_TEMPLATE,
    )

from .synthesis import SYNTHESIS_TEMPLATE
from .dimension import DIMENSION_REFINEMENT_TEMPLATE

__all__ = [
    "GLOBAL_SYSTEM_PROMPT",
    "SYNTHESIS_TEMPLATE",
    "DIMENSION_REFINEMENT_TEMPLATE",
    "USER_CONTEXT_PROFILE_TEMPLATE",
    "DIMENSIONS_CLARIFIED_AND_DEPENDENCIES_TEMPLATE",
]
