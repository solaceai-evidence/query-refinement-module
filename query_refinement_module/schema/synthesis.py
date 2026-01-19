"""
Synthesis prompt builder for combining refined aspects into final query.

This module handles prompt construction for the final synthesis step,
where all aspect refinements are combined into a coherent refined query.
"""

from typing import Dict, Any, List
from .model import RefinementAspect


class SynthesisPromptBuilder:
    """
    Builds structured prompts for query synthesis.
    
    Similar architecture to RefinementAspect.build_unified_prompt() but focused
    on the final synthesis step that combines all aspect refinements.
    """
    
    # Template for synthesis prompt (similar to UNIFIED_ANALYSIS_PROMPT)
    SYNTHESIS_PROMPT_TEMPLATE = """
# Task: Synthesize Refined Query

Transform the refined aspects below into an enhanced, coherent research statement optimized for semantic search retrieval.

## Original Research Input
"{original_query}"

---

{aspects_section}

---

## Synthesis Instructions

**Synthesis Quality Requirements:**
- Remove ALL conversational language ("I think", "maybe", "probably", "I guess", "kind of", "sort of")
- Remove ALL filler words and unnecessary elaboration ("well", "you know", "obviously", "definitely", "actually")
- Remove ALL meta-commentary ("The user wants to study", "This research focuses on", "I'm interested in", "The goal is to")
- Write in clear, professional, declarative statements
- Preserve ALL key factual details from the original input and refinements
- Maintain technical precision and domain-specific terminology
- Use complete, well-formed sentences that sound natural and authoritative

## Example Transformations
Before: "Well, I think I want to maybe study adults, you know, probably around 18 to 65 or so, who have Type 2 diabetes"
After: "Adults aged 18-65 with Type 2 diabetes"

Before: "This research focuses on investigating the potential effects of machine learning approaches on protein folding prediction"
After: "Machine learning approaches for protein folding prediction"

---

{output_format_section}
"""
    
    # Base schema for synthesis output
    BASE_SYNTHESIS_FIELDS = {
        "refined_query": "string",
        "refinement_aspects": "object",
        "confidence": "float",
        "key_changes": "array"
    }
    
    # Field descriptions for synthesis output
    SYNTHESIS_FIELD_DESCRIPTIONS = {
        "refined_query": "The final synthesized query combining all refinements",
        "refinement_aspects": "Map of aspect_id → refinement_aspect_value for traceability",
        "confidence": "LLM confidence in synthesis quality (0.0-1.0)",
        "key_changes": "List of key changes from original query"
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
            original_query: The user's original query
            refinement_aspect_values: Dict mapping aspect_id → refined value
            aspects: List of RefinementAspect objects for context
            
        Returns:
            Complete formatted synthesis prompt
        """
        aspects_section = SynthesisPromptBuilder._build_aspects_section(
            refinement_aspect_values,
            aspects
        )
        output_format_section = SynthesisPromptBuilder._build_output_format_section()
        
        return SynthesisPromptBuilder.SYNTHESIS_PROMPT_TEMPLATE.format(
            original_query=original_query,
            aspects_section=aspects_section,
            output_format_section=output_format_section
        )
    
    @staticmethod
    def _build_aspects_section(
        refinement_aspect_values: Dict[str, Any],
        aspects: List[RefinementAspect]
    ) -> str:
        """
        Build section showing all refined aspect values.
        
        Format:
        **Refined Aspects:**
        
        1. **Aspect Name** (Description)
           Refined Value: <value>
        
        Args:
            refinement_aspect_values: Map of aspect_id → value
            aspects: List of aspects for metadata (names, descriptions)
            
        Returns:
            Formatted aspects section
        """
        if not refinement_aspect_values:
            return "**Refined Aspects:** None (using original query as-is)"
        
        # Create lookup map
        aspect_map = {a.id: a for a in aspects}
        
        lines = ["**Refined Aspects:**", ""]
        
        item_number = 0
        for aspect_id, value in refinement_aspect_values.items():
            aspect = aspect_map.get(aspect_id)
            
            # Handle skipped/clear aspects
            if value == "[SKIPPED]":
                continue  # Don't include skipped aspects
            elif value == "[CLEAR_IN_ORIGINAL]":
                if aspect:
                    item_number += 1
                    lines.append(f"{item_number}. **{aspect.aspect_name}** ({aspect.aspect_description})")
                    lines.append(f"   Status: ✓ Already clear in original query")
                    lines.append("")
                continue
            
            # Regular refined value
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
        lines = ["**OUTPUT FORMAT (JSON):**", ""]
        
        # Build JSON example structure
        lines.append("{")
        lines.append('  "refined_query": "The synthesized, search-optimized query combining all refinements",')
        lines.append('  "refinement_aspects": {')
        lines.append('    "aspect_id_1": "value from refinement (for traceability)",')
        lines.append('    "aspect_id_2": "value from refinement"')
        lines.append('  },')
        lines.append('  "confidence": 0.0-1.0,')
        lines.append('  "key_changes": [')
        lines.append('    "Description of major change 1",')
        lines.append('    "Description of major change 2"')
        lines.append('  ],')
        lines.append('  "publication_years": "Temporal constraints (e.g., \'2020-2025\') or empty string",')
        lines.append('  "venues": "Comma-separated venue names or empty string",')
        lines.append('  "authors": ["Author 1", "Author 2"] or [],')
        lines.append('  "fields_of_study": "Comma-separated fields or empty string",')
        lines.append('  "refined_statement": "Natural-language statement optimized for semantic search",')
        lines.append('  "refined_statement_keywords": "Keyword-optimized version"')
        lines.append("}")
        lines.append("")
        
        # Add field requirements
        lines.append("**Field Requirements:**")
        for field_name, field_type in SynthesisPromptBuilder.BASE_SYNTHESIS_FIELDS.items():
            desc = SynthesisPromptBuilder.SYNTHESIS_FIELD_DESCRIPTIONS.get(field_name, f"Value of type {field_type}")
            lines.append(f"- `{field_name}` ({field_type}): REQUIRED - {desc}")
        
        lines.append("- All metadata fields (publication_years, venues, authors, fields_of_study): Extract if mentioned, otherwise empty")
        lines.append("- `refined_statement`: Alternative phrasing for semantic search")
        lines.append("- `refined_statement_keywords`: Keyword version")
        lines.append("")
        
        # Add processing rules
        lines.append("**Processing Rules:**")
        lines.append("- Current year is 2026 for temporal interpretation")
        lines.append("- Preserve user's intended meaning exactly")
        lines.append("- Extract metadata into separate fields (don't duplicate in refined_query)")
        lines.append("- All topical content should appear in refined_query or refined_statement")
        lines.append("- `refinement_aspects` must contain the same aspect_id keys from the input with their refined values")
        
        return "\n".join(lines)
    
    @staticmethod
    def get_system_prompt() -> str:
        """
        Get the system prompt for synthesis role.
        
        Returns:
            System prompt defining the synthesis role
        """
        return """You are a research query synthesis expert. Your role is to integrate and enhance a user's original input (query, statement, topic, idea, etc.) with refined aspect details.

You will receive:
1. The user's original research input
2. Refined aspect values (specific parameters elicited through conversation)

Your task:
- INTEGRATE the original input intent with refined aspect details into a coherent whole
- The original input establishes the research question or idea or goal; aspects provide specificity and clarity
- Apply controlled normalization while preserving user intent
- Ensure cross-aspect consistency and alignment with original query goal
- Produce structured output suitable for literature search (e.g., semantic search)

Core principles:
- Combine both original input and refined aspects - don't omit either
- Maintain technical precision and domain-specific terminology
- Write in clear, professional, declarative statements
- Avoid conversational language, filler words, and meta-commentary
- Preserve semantic meaning from both original input and refined aspects
- Standardize terminology to research/domain conventions"""