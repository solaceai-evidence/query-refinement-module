"""
Synthesis prompt builder using Pydantic models and Jinja2 templates.

Integrates all refined dimensions into optimized research specification.
"""

import json
from typing import Any, Dict, List
import logging

from .response import (
    QueryRefinementResponse,
    ResearchStatementResponse,
    SemanticRepresentationResponse,
    SearchConstructionResponse,
)


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




class NormalizationPromptBuilder:
    """Builds prompts for Agent A (research statement normalization)."""

    @staticmethod
    def get_system_prompt() -> str:
        from .templates.normalization import NORMALIZATION_TEMPLATE
        return NORMALIZATION_TEMPLATE

    @staticmethod
    def get_user_prompt(
        original_input: str,
        aspectID_value_mapping: Dict[str, Any],
        aspect_list: List,
    ) -> str:
        lines = []
        for aspect in aspect_list:
            value = aspectID_value_mapping.get(aspect.id, "[SKIPPED]")
            if value is None:
                value = "[SKIPPED]"
            lines.append(f"**{aspect.name}** ({aspect.description}): {value}")
        dimensions_text = "\n".join(lines)
        return (
            f"## Original Input\n\n{original_input}\n\n"
            f"---\n\n"
            f"## Clarified Dimensions\n\n{dimensions_text}\n"
        )


class SemanticRepresentationPromptBuilder:
    """Builds prompts for Agent B (semantic representation)."""

    @staticmethod
    def get_system_prompt() -> str:
        from .templates.semantic_representation import SEMANTIC_REPRESENTATION_TEMPLATE
        return SEMANTIC_REPRESENTATION_TEMPLATE

    @staticmethod
    def get_user_prompt(research_statement: str) -> str:
        return f"## Research Statement\n\n{research_statement}\n"


class SearchConstructionPromptBuilder:
    """Builds prompts for Agent D (anchor search construction)."""

    @staticmethod
    def get_system_prompt() -> str:
        from .templates.search_construction import SEARCH_CONSTRUCTION_TEMPLATE
        return SEARCH_CONSTRUCTION_TEMPLATE

    @staticmethod
    def get_user_prompt(
        research_statement: str,
        concept_graph: Dict[str, Any],
        additional_guidance: str = "",
    ) -> str:
        graph_json = json.dumps(concept_graph, ensure_ascii=False, indent=2)
        parts = [
            f"## Research Statement\n\n{research_statement}",
            f"## Concept Graph\n\n{graph_json}",
        ]
        if additional_guidance:
            parts.append(f"## Additional Guidance\n\n{additional_guidance.strip()}")
        return "\n\n---\n\n".join(parts) + "\n"


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
    "NormalizationPromptBuilder",
    "SemanticRepresentationPromptBuilder",
    "SearchConstructionPromptBuilder",
    "validate_synthesis_response",
]