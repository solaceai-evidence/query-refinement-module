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
    Builds synthesis prompts
    """
    
    @staticmethod
    def get_synthesis_prompt() -> str:
        """
        Get system prompt for synthesis.
        
        Returns:
            Global system prompt (same for all tasks for caching)
        """
        from .templates import SYNTHESIS_TEMPLATE
        return SYNTHESIS_TEMPLATE
    


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