"""
Synthesis prompt builder using Pydantic models and Jinja2 templates.

Integrates all refined dimensions into optimized research specification.
"""

import json
from typing import Any, Dict, List
import logging

from .response import QueryRefinementResponse


logger = logging.getLogger(__name__)


# ============================================================================
# Synthesis Prompt Builder
# ============================================================================

class SynthesisPromptBuilder:
    """
    Builds synthesis prompts for integrating refined dimensions.
    """

    @staticmethod
    def get_system_prompt() -> str:
        from .templates import SYNTHESIS_TEMPLATE
        return SYNTHESIS_TEMPLATE

    @staticmethod
    def get_synthesis_prompt(
        original_input: str,
        aspectID_value_mapping: Dict[str, str],
        aspect_list: List
    ) -> str:
        dimensions_lines = []
        for aspect in aspect_list:
            value = aspectID_value_mapping.get(aspect.id, "[NOT SET]")
            dimensions_lines.append(
                f"**{aspect.name}** ({aspect.description}): {value}"
            )

        dimensions_text = "\n".join(dimensions_lines)

        user_prompt = f"""## Original Input

{original_input}

---

## Clarified Dimensions

{dimensions_text}
"""
        return user_prompt

    @staticmethod
    def _serialize_value(value: Any) -> str:
        if value is None:
            return "[SKIPPED]"
        if isinstance(value, (dict, list)):
            return json.dumps(value, ensure_ascii=False)
        return str(value)

    @classmethod
    def _build_canonical_context(
        cls,
        original_input: str,
        aspectID_value_mapping: Dict[str, Any],
        aspect_list: List,
    ) -> str:
        dimensions_lines = []
        for aspect in aspect_list:
            value = cls._serialize_value(aspectID_value_mapping.get(aspect.id, "[NOT SET]"))
            dimensions_lines.append(f"- {aspect.id}: {value}")

        dimensions_text = "\n".join(dimensions_lines)
        return (
            f"## Original Input\n\n{original_input}\n\n"
            f"## Canonical Dimensions\n\n{dimensions_text}\n"
        )




def validate_synthesis_response(response_dict: Dict) -> QueryRefinementResponse:
    """
    Validate synthesis response using Pydantic.
    
    Args:
        response_dict: Raw response dictionary from LLM
        
    Returns:
        Validated SynthesisResponse object
        
    Raises:
        ValidationError: If response doesn't match schema
    """
    return QueryRefinementResponse(**response_dict)


__all__ = [
    "SynthesisPromptBuilder",
    "validate_synthesis_response",
]