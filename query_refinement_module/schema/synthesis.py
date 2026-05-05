"""
Synthesis prompt builder using Pydantic models and Jinja2 templates.

Integrates all refined dimensions into optimized research specification.
"""

import json
from typing import Any, Dict, List
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

    @staticmethod
    def get_statement_system_prompt() -> str:
        return """
You produce only one JSON object matching StatementResponse.
Task: write `integrated_statement` from the original input and canonical dimensions.
Rules:
- use only supported input content
- dimension values override conflicting original-query content
- do not add unstated constraints
- return a non-empty string
""".strip()

    @classmethod
    def get_statement_prompt(
        cls,
        original_input: str,
        aspectID_value_mapping: Dict[str, Any],
        aspect_list: List,
    ) -> str:
        return cls._build_canonical_context(original_input, aspectID_value_mapping, aspect_list)

    @staticmethod
    def get_semantic_query_system_prompt() -> str:
        return """
You produce only one JSON object matching SemanticQueryResponse.
Task: write `semantic` as a natural-language retrieval query.
Rules:
- ground the output in `integrated_statement`
- do not add new constraints
- exclude authors, venues, and publication-type labels
- return one non-empty sentence
""".strip()

    @staticmethod
    def get_semantic_query_prompt(integrated_statement: str, accepted_dimensions: Dict[str, Any]) -> str:
        return (
            f"## Integrated Statement\n\n{integrated_statement}\n\n"
            f"## Accepted Dimensions\n\n{json.dumps(accepted_dimensions, ensure_ascii=False, indent=2)}\n"
        )

    @staticmethod
    def get_terminology_system_prompt() -> str:
        return """
You produce only one JSON object matching TerminologyResponse.
Task: return `synonyms` for grounded concepts only.
Rules:
- include only same-level lexical variants and established abbreviations
- do not add broader terms, narrower terms, or loosely related concepts
- use empty objects or arrays when support is insufficient
""".strip()

    @staticmethod
    def get_terminology_prompt(integrated_statement: str, concept_inventory: Dict[str, List[str]]) -> str:
        return (
            f"## Integrated Statement\n\n{integrated_statement}\n\n"
            f"## Concept Inventory\n\n{json.dumps(concept_inventory, ensure_ascii=False, indent=2)}\n"
        )

    @staticmethod
    def get_keyword_support_system_prompt() -> str:
        return """
You produce only one JSON object matching KeywordSupportResponse.
Task: return grounded `phrases`, `required`, and `optional` keyword support.
Rules:
- every term must be traceable to the provided concept inventory or terminology
- do not output exclusions
- do not duplicate the same concept across `required` and `optional`
- keep lists short and retrieval-oriented
""".strip()

    @staticmethod
    def get_keyword_support_prompt(
        integrated_statement: str,
        concept_inventory: Dict[str, List[str]],
        terminology_synonyms: Dict[str, List[str]],
    ) -> str:
        return (
            f"## Integrated Statement\n\n{integrated_statement}\n\n"
            f"## Concept Inventory\n\n{json.dumps(concept_inventory, ensure_ascii=False, indent=2)}\n\n"
            f"## Terminology Synonyms\n\n{json.dumps(terminology_synonyms, ensure_ascii=False, indent=2)}\n"
        )

    @staticmethod
    def get_filter_resolution_system_prompt() -> str:
        return """
You produce only one JSON object matching FilterSuggestionResponse.
Task: suggest `fields_of_study` only when the topic directly and unambiguously entails them.
Rules:
- choose only from the permitted-values list
- return an empty list when classification requires interpretation rather than entailment
- do not emit years, venues, authors, or publication types
""".strip()

    @staticmethod
    def get_filter_resolution_prompt(
        original_input: str,
        accepted_dimensions: Dict[str, Any],
        permitted_values: List[str],
    ) -> str:
        return (
            f"## Original Input\n\n{original_input}\n\n"
            f"## Accepted Dimensions\n\n{json.dumps(accepted_dimensions, ensure_ascii=False, indent=2)}\n\n"
            f"## Permitted Values\n\n{json.dumps(permitted_values, ensure_ascii=False)}\n"
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