"""
Synthesis prompt builder using Pydantic models and Jinja2 templates.

Integrates all refined dimensions into optimized research specification.
"""

from typing import Dict, List
from jinja2 import Environment
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
        """
        Get system prompt for synthesis.
        
        Returns:
            Global system prompt for synthesis (same for all tasks for caching)
        """
        from .templates import SYNTHESIS_TEMPLATE
        return SYNTHESIS_TEMPLATE
    
    @staticmethod
    def get_synthesis_prompt(
        original_input: str,
        aspectID_value_mapping: Dict[str, str],
        aspect_list: List
    ) -> str:
        """
        Build user prompt for synthesis with original input and clarified dimensions.
        
        Args:
            original_input: The user's original query/statement
            aspectID_value_mapping: Dict mapping aspect IDs to their refined values
            aspect_list: List of RefinementAspect objects
            
        Returns:
            Formatted user prompt with original input and clarified dimensions
        """
        # Build clarified dimensions section
        dimensions_lines = []
        for aspect in aspect_list:
            value = aspectID_value_mapping.get(aspect.id, "[NOT SET]")
            # Format: **AspectName** (description): value
            dimensions_lines.append(
                f"**{aspect.name}** ({aspect.description}): {value}"
            )
        
        dimensions_text = "\n".join(dimensions_lines)
        
        # Combine into user prompt
        user_prompt = f"""## Original Input

{original_input}

---

## Clarified Dimensions

{dimensions_text}
"""
        return user_prompt
    


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