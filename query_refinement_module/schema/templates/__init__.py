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
_LLM_MODEL_ENV = "QUERY_REFINEMENT_LLM_MODEL"
_OPEN_MODEL_MARKERS = ("ollama/", "qwen", "llama", "mistral", "gemma", "deepseek")


def _infer_open_llm_from_model() -> bool:
    model = os.getenv(_LLM_MODEL_ENV, "").strip().lower()
    return any(marker in model for marker in _OPEN_MODEL_MARKERS)


def _use_open_llm_templates() -> bool:
    raw_variant = os.getenv(_PROMPT_VARIANT_ENV)
    if raw_variant is None or raw_variant.strip() == "":
        return _infer_open_llm_from_model()

    variant = raw_variant.strip().lower()
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
