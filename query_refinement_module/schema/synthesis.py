"""
Synthesis prompt builder for integrating clarified details with input to synthesize final output.
"""

from typing import Dict, Any, List
from .model import RefinementAspect
from ..prompt.system_role import SYNTHESIS_SYSTEM_PROMPT
from ..prompt.user import SYNTHESIS_PROMPT_TEMPLATE

class SynthesisPromptBuilder:
    """
    Builds structured prompts for query synthesis.
    
    """
    
    @staticmethod
    def _build_output_format_section() -> str:
        """
        Generate JSON structure specification from RefinedQuery Pydantic model.
        
        Returns:
            Formatted output format section for the prompt
        """
        return """## OUTPUT FORMAT

Return a single JSON object with this exact structure:
```json
{
  "synthesized_statement": "string - Faithful integration of original input with all clarified details",
  
  "detail_values": {
    "aspect_id_1": "string - normalized value for this aspect",
    "aspect_id_2": "string - normalized value for this aspect"
  },
  
  "search_optimized": {
    "semantic": "string - Natural language query optimized for vector/embedding search (40-80 words)",
    
    "keyword": {
      "structured": "string - Boolean query with AND/OR/NOT operators and parentheses",
      
      "phrases": [
        "string - exact phrase 1 (2-4 words)",
        "string - exact phrase 2"
      ],
      
      "terms": {
        "required": ["string - must appear", "string - must appear"],
        "optional": ["string - improves relevance", "string - improves relevance"],
        "excluded": ["string - filter out", "string - filter out"]
      }
    },
    
    "grey_literature": {
      "broad_concepts": [
        "string - accessible terminology",
        "string - policy/practice language"
      ],
      "organizational_terms": [
        "string - NGO/government terminology",
        "string - program/initiative language"
      ],
      "geographic_variants": [
        "string - regional terminology",
        "string - local health system terms"
      ]
    }
  },
  
  "search_filters": {
    "publication_years": "string - YYYY-YYYY format or empty string",
    "venues": "string - comma-separated venue names or empty string",
    "authors": ["string - author name", "string - author name"],
    "publication_types": ["string - study type", "string - study type"],
    "fields_of_study": "string - comma-separated fields or empty string"
  },
  
  "terminology": {
    "primary_terms": [
      "string - core concept 1",
      "string - core concept 2"
    ],
    
    "synonyms": {
      "primary_term_1": ["string - variant 1", "string - variant 2"],
      "primary_term_2": ["string - variant 1", "string - variant 2"]
    },
    
    "domain_specific": [
      "string - technical term",
      "string - scientific nomenclature"
    ],
    
    "colloquial": [
      "string - plain language equivalent",
      "string - accessible terminology"
    ]
  },
  
  "metadata": {
    "temporal": "string or null - temporal context",
    "geographic": "string or null - geographic context",
    "source_types": ["string - source type", "string - source type"],
    "other": {
      "key": "value - additional metadata"
    }
  },
  
  "processing_log": {
    "preserved": [
      "string - what was kept from original input"
    ],
    
    "normalized": [
      "string - what was standardized/cleaned"
    ],
    
    "integrated": [
      "string - how details were combined"
    ],
    
    "expanded": [
      "string - what was added/enriched"
    ]
  }
}
```

**Important:**
- Return ONLY valid JSON, no markdown formatting, no preamble
- All string fields must be strings (use empty string "" not null for optional strings)
- All array fields must be arrays (use [] for empty, never null)
- metadata.temporal and metadata.geographic can be null
- Ensure proper JSON syntax (commas, quotes, brackets)
"""
    
    @staticmethod
    def build_synthesis_prompt(
        original_input: str,
        aspectID_value_mapping: Dict[str, Any],
        aspect_list: List[RefinementAspect]
    ) -> str:
        """
        Build complete synthesis prompt with all refined aspect values.
        
        Args:
            original_input: The user's original research input
            aspectID_value_mapping: Dict mapping aspect_id → normalized value
            aspect_list: List of RefinementAspect objects for context (names, descriptions)
            
        Returns:
            Complete formatted synthesis prompt
        """
        aspects_section = SynthesisPromptBuilder._build_aspects_section(
            aspectID_value_mapping,
            aspect_list
        )
        output_format_section = SynthesisPromptBuilder._build_output_format_section()
        
        # Use replace() instead of format() to avoid issues with JSON examples in template
        return (SYNTHESIS_PROMPT_TEMPLATE
                .replace("{original_input}", original_input)
                .replace("{aspects_section}", aspects_section)
                .replace("{output_format_section}", output_format_section)
        )
    
    @staticmethod
    def _build_aspects_section(
        aspectId2Spec_dict: Dict[str, Any],
        aspect_list: List[RefinementAspect]
    ) -> str:
        """Build the clarified details section for the prompt."""

        if not aspectId2Spec_dict:
            return "None (using original input as-is)"
        
        # Create lookup dict for aspect names/descriptions
        aspect_info = {
            aspect.id: (aspect.aspect_name, aspect.aspect_description)
            for aspect in aspect_list
        }
        
        sections = []
        for aspect_id, value in aspectId2Spec_dict.items():
            name, description = aspect_info.get(aspect_id, (aspect_id, ""))
            # Handle skipped aspects
            display_value = "[SKIPPED]" if value is None or value == "" else value

            sections.append(
                f"- **{name}** ({description})\n"
                f"  Specification: {display_value}"
            )
        return "\n".join(sections)
    
    @staticmethod
    def get_system_prompt() -> str:
        """
        Get the system prompt for synthesis role.
        
        Returns:
            System prompt defining the synthesis role
        """
        return SYNTHESIS_SYSTEM_PROMPT