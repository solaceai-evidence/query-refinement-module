"""
Prompt builder using Jinja2 templates and Pydantic models.

Separates data validation (Pydantic) from presentation (Jinja2).
"""

from typing import Dict, List, Optional
from jinja2 import Environment, Template
import logging

from .models import (
    RefinementDimension,
    UserContext,
    CompletedDimension,
    ExamplesCollection
)
from .templates import (
    DIMENSION_REFINEMENT_TEMPLATE,
    SYNTHESIS_TEMPLATE,
    EXAMPLES_SECTION_TEMPLATE
)

logger = logging.getLogger(__name__)


class PromptBuilder:
    """
    Builds prompts from Pydantic models using Jinja2 templates.
    
    Handles:
    - Template rendering with type-safe data
    - Examples formatting
    - Dependency context building
    - Schema generation for output format
    """
    
    def __init__(self):
        """Initialize Jinja2 environment."""
        self.env = Environment(
            trim_blocks=True,
            lstrip_blocks=True,
            keep_trailing_newline=False
        )
        
        # Precompile templates
        self.dimension_template = self.env.from_string(DIMENSION_REFINEMENT_TEMPLATE)
        self.synthesis_template = self.env.from_string(SYNTHESIS_TEMPLATE)
        self.examples_template = self.env.from_string(EXAMPLES_SECTION_TEMPLATE)
    
    def build_dimension_refinement_prompt(
        self,
        dimension: RefinementDimension,
        user_context: UserContext,
        original_input: str,
        completed_dimensions: List[CompletedDimension],
        dependency_values: Dict[str, str]
    ) -> str:
        """
        Build dimension refinement prompt.
        
        Args:
            dimension: Dimension to refine
            user_context: User context for adaptation
            original_input: User's original research input
            completed_dimensions: Previously completed dimensions
            dependency_values: Dict mapping dimension IDs to assembled values
            
        Returns:
            Complete prompt string ready for LLM
        """
        # Format evaluation instructions with user input
        evaluation_instructions = self._format_evaluation_instructions(
            dimension.evaluation_instructions,
            original_input
        )
        
        # Build examples section if available
        examples_section = ""
        if dimension.has_examples:
            examples_section = self.examples_template.render(
                examples=dimension.examples
            )
        
        # Build dependencies list with reasons
        dependencies = []
        if dimension.has_dependencies:
            for dep_id in dimension.depends_on:
                # Find the completed dimension
                dep_dim = next(
                    (d for d in completed_dimensions if d.id == dep_id),
                    None
                )
                if dep_dim:
                    dependencies.append({
                        'name': dep_dim.name,
                        'assembled_value': dep_dim.assembled_value,
                        'reason': f"Required for {dimension.aspect_name.lower()}"
                    })
        
        # Get complete schema and descriptions
        schema = dimension.get_complete_schema()
        descriptions = dimension.get_complete_descriptions()
        
        # Render template
        return self.dimension_template.render(
            dimension=dimension,
            user_context=user_context,
            completed_dimensions=completed_dimensions,
            dependencies=dependencies,
            evaluation_instructions=evaluation_instructions,
            examples_section=examples_section,
            schema=schema,
            descriptions=descriptions
        )
    
    def build_synthesis_prompt(
        self,
        all_dimensions: List[CompletedDimension],
        original_input: str,
        user_context: UserContext,
        synthesis_purpose: str = "literature search and methodology design"
    ) -> str:
        """
        Build synthesis prompt.
        
        Args:
            all_dimensions: All completed dimensions
            original_input: Original user input
            user_context: User context
            synthesis_purpose: What the output will be used for
            
        Returns:
            Complete synthesis prompt
        """
        return self.synthesis_template.render(
            all_dimensions=all_dimensions,
            original_input=original_input,
            user_context=user_context,
            synthesis_purpose=synthesis_purpose
        )
    
    def _format_evaluation_instructions(
        self,
        instructions: str,
        original_input: str
    ) -> str:
        """
        Format evaluation instructions with user input.
        
        Handles {input}, {statement}, {query} placeholders.
        """
        return instructions.format(
            input=original_input,
            statement=original_input,
            query=original_input
        )


# ============================================================================
# Convenience Functions
# ============================================================================

def create_dimension_prompt(
    dimension: RefinementDimension,
    user_context: UserContext,
    original_input: str,
    completed_dimensions: List[CompletedDimension] = None,
    dependency_values: Dict[str, str] = None
) -> str:
    """
    Convenience function to create dimension refinement prompt.
    
    Args:
        dimension: Dimension to refine
        user_context: User context
        original_input: User's research input
        completed_dimensions: Previously completed dimensions
        dependency_values: Dependency values dict
        
    Returns:
        Formatted prompt string
    """
    builder = PromptBuilder()
    return builder.build_dimension_refinement_prompt(
        dimension=dimension,
        user_context=user_context,
        original_input=original_input,
        completed_dimensions=completed_dimensions or [],
        dependency_values=dependency_values or {}
    )


def create_synthesis_prompt(
    all_dimensions: List[CompletedDimension],
    original_input: str,
    user_context: UserContext,
    synthesis_purpose: str = "literature search and methodology design"
) -> str:
    """
    Convenience function to create synthesis prompt.
    
    Args:
        all_dimensions: All completed dimensions
        original_input: Original user input
        user_context: User context
        synthesis_purpose: Purpose of synthesis
        
    Returns:
        Formatted synthesis prompt
    """
    builder = PromptBuilder()
    return builder.build_synthesis_prompt(
        all_dimensions=all_dimensions,
        original_input=original_input,
        user_context=user_context,
        synthesis_purpose=synthesis_purpose
    )


__all__ = [
    "PromptBuilder",
    "create_dimension_prompt",
    "create_synthesis_prompt",
]