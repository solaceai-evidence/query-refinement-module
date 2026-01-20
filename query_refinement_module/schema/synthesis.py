"""
Synthesis prompt builder for combining refined aspects into final query.

This module handles prompt construction for the final synthesis step,
where all aspect refinements are combined into a coherent refined query.
"""

from typing import Dict, Any, List
from .model import RefinementAspect
from ..prompt.system_role import SYNTHESIS_SYSTEM_PROMPT
from ..prompt.user import SYNTHESIS_PROMPT_TEMPLATE


class SynthesisPromptBuilder:
    """
    Builds structured prompts for query synthesis.
    
    """
    
    # Template for synthesis prompt 
    
    
    # Base schema for synthesis output
    BASE_SYNTHESIS_FIELDS = {
        "refined_query": "string",
        "refinement_aspects": "object"
    }
    
    # Field descriptions for synthesis output
    SYNTHESIS_FIELD_DESCRIPTIONS = {
        "refined_query": "The final synthesized query combining all refinements",
        "refinement_aspects": "Map of aspect_id → refinement_aspect_value for traceability"
    }
    
    @staticmethod
    def build_synthesis_prompt(
        original_query: str,
        refinement_aspect_values: Dict[str, Any],
        aspects: List[RefinementAspect]
    ) -> str:
        """
        Build complete synthesis prompt with all refined aspect values.
        
        Args:
            original_input: The user's original research input
            refinement_aspect_values: Dict mapping aspect_id → refined value
            aspects: List of RefinementAspect objects for context (names, descriptions)
            
        Returns:
            Complete formatted synthesis prompt
        """
        aspects_section = SynthesisPromptBuilder._build_aspects_section(
            refinement_aspect_values,
            aspects
        )
        output_format_section = SynthesisPromptBuilder._build_output_format_section()
        
        # Use replace() instead of format() to avoid issues with JSON examples in template
        return (SYNTHESIS_PROMPT_TEMPLATE
                .replace("{original_input}", original_query)
                .replace("{aspects_section}", aspects_section)
                .replace("{output_format_section}", output_format_section)
        )
    
    @staticmethod
    def _build_aspects_section(
        refinement_aspect_values: Dict[str, Any],
        aspects: List[RefinementAspect]
    ) -> str:
        """
        Build section showing all refined aspect values.
        
        Format:
        
        1. **Aspect Name** (Description)
           Refined Value: <value>
        
        Args:
            refinement_aspect_values: Map of aspect_id → value
            aspects: List of aspects for metadata (names, descriptions)
            
        Returns:
            Formatted aspects section
        """
        if not refinement_aspect_values:
            return "None (using original query as-is)"
        
        # Create lookup map
        aspect_map = {a.id: a for a in aspects}
        
        lines = [""]
        
        item_number = 0
        for aspect_id, value in refinement_aspect_values.items():
            aspect = aspect_map.get(aspect_id)
            
            # Show actual refined value (including values extracted from original input)
            item_number += 1
            if aspect:
                lines.append(f"{item_number}. **{aspect.aspect_name}** ({aspect.aspect_description})")
                # Convert value to string if it's complex type
                value_str = str(value) if not isinstance(value, str) else value
                lines.append(f"   Refined Value: {value_str}")
            else:
                lines.append(f"{item_number}. **{aspect_id}**")
                value_str = str(value) if not isinstance(value, str) else value
                lines.append(f"   Refined Value: {value_str}")
            lines.append("")
        
        return "\n".join(lines)
    
    @staticmethod
    def _build_output_format_section() -> str:
        """
        Build output format specification for synthesis response.
        
        Dynamically generates the format from BASE_SYNTHESIS_FIELDS to ensure
        single source of truth (similar to RefinementAspect._build_output_format_section).
        
        Returns:
            Formatted output format section with JSON schema
        """
        # Build dynamic field requirements from BASE_SYNTHESIS_FIELDS
        field_requirements = []
        for field_name, field_type in SynthesisPromptBuilder.BASE_SYNTHESIS_FIELDS.items():
            desc = SynthesisPromptBuilder.SYNTHESIS_FIELD_DESCRIPTIONS.get(field_name, f"Value of type {field_type}")
            field_requirements.append(f"- `{field_name}` ({field_type}): REQUIRED - {desc}")
        
        field_requirements_text = "\n".join(field_requirements)
        
        return f"""**OUTPUT FORMAT (JSON):**

{{
  "refined_query": "The synthesized, search-optimized query combining all refinements",
  "refinement_aspects": {{
    "population": "refined value for population aspect",
    "intervention": "refined value for intervention aspect",
    "outcome": "refined value for outcome aspect"
  }},
  "publication_years": "Temporal constraints (e.g., '2020-2025') or empty string",
  "venues": "Comma-separated venue names or empty string",
  "authors": ["Author 1", "Author 2"] or [],
  "fields_of_study": "Comma-separated fields or empty string",
  "refined_statement": "Natural-language statement optimized for semantic search",
  "refined_statement_keywords": "Keyword-optimized version"
}}

**Field Requirements:**
{field_requirements_text}
- All metadata fields (publication_years, venues, authors, fields_of_study): Extract if mentioned, otherwise empty
- `refined_statement`: Alternative phrasing for semantic search
- `refined_statement_keywords`: Keyword version

**Processing Rules:**
- Current year is 2026 for temporal interpretation
- Preserve user's intended meaning exactly
- Extract metadata into separate fields (don't duplicate in refined_query)
- All topical content should appear in refined_query or refined_statement
- **IMPORTANT**: `refinement_aspects` must be a JSON object where each key is an aspect ID from the "Refined Aspects" section above, and each value is the corresponding "Refined Value" shown for that aspect"""
    
    @staticmethod
    def get_system_prompt() -> str:
        """
        Get the system prompt for synthesis role.
        
        Returns:
            System prompt defining the synthesis role
        """
        return SYNTHESIS_SYSTEM_PROMPT