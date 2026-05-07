"""
Synthesis prompt builder using Pydantic models and Jinja2 templates.

Integrates all refined dimensions into optimized research specification.
"""

import json
import re
from typing import Any, Dict, List
from jinja2 import Environment
import logging

from .response import QueryRefinementResponse


logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Template section extractor
# ---------------------------------------------------------------------------

def _extract_template_section(heading: str) -> str:
    """Return the body text under *heading* from SYNTHESIS_TEMPLATE.

    Stops at the next heading of the same or higher level, or at a ``---``
    separator.  The heading itself is not included in the returned text.
    The original template is never modified.
    """
    from .templates import SYNTHESIS_TEMPLATE
    level = len(heading) - len(heading.lstrip("#"))
    # Locate the heading line
    idx = SYNTHESIS_TEMPLATE.find("\n" + heading + "\n")
    if idx == -1:
        return ""
    start = idx + len("\n" + heading + "\n")
    end = len(SYNTHESIS_TEMPLATE)
    # Stop at any heading with level <= current level, or at a --- separator
    for match in re.finditer(r'\n(#{1,6}) ', SYNTHESIS_TEMPLATE[start:]):
        if len(match.group(1)) <= level:
            end = start + match.start()
            break
    sep = SYNTHESIS_TEMPLATE.find("\n---\n", start)
    if sep != -1 and sep < end:
        end = sep
    return SYNTHESIS_TEMPLATE[start:end].strip()


def _extract_general_rules() -> str:
    """Return the ## General Rules block from SYNTHESIS_TEMPLATE verbatim."""
    return _extract_template_section("## General Rules")



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
        general_rules = _extract_general_rules()
        field_rules = _extract_template_section("### integrated_statement")
        return (
            "You produce only one JSON object matching StatementResponse: "
            '{"integrated_statement": ""}\n\n'
            f"## General Rules\n\n{general_rules}\n\n"
            f"## Field Specification: integrated_statement\n\n{field_rules}"
        )

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
        general_rules = _extract_general_rules()
        field_rules = _extract_template_section("### search_optimized.semantic")
        return (
            "You produce only one JSON object matching SemanticQueryResponse: "
            '{"semantic": ""}\n\n'
            f"## General Rules\n\n{general_rules}\n\n"
            f"## Field Specification: search_optimized.semantic\n\n{field_rules}"
        )

    @staticmethod
    def get_semantic_query_prompt(integrated_statement: str, accepted_dimensions: Dict[str, Any]) -> str:
        return (
            f"## Integrated Statement\n\n{integrated_statement}\n\n"
            f"## Accepted Dimensions\n\n{json.dumps(accepted_dimensions, ensure_ascii=False, indent=2)}\n"
        )

    @staticmethod
    def get_terminology_system_prompt() -> str:
        general_rules = _extract_general_rules()
        field_rules = _extract_template_section("### terminology.synonyms")
        return (
            "You produce only one JSON object matching TerminologyResponse: "
            '{"synonyms": {}}\n\n'
            f"## General Rules\n\n{general_rules}\n\n"
            f"## Field Specification: terminology.synonyms\n\n{field_rules}"
        )

    @staticmethod
    def get_terminology_prompt(integrated_statement: str, concept_inventory: List[str]) -> str:
        return (
            f"## Integrated Statement\n\n{integrated_statement}\n\n"
            f"## Concepts Requiring Synonyms\n\n"
            + "\n".join(f"- {c}" for c in concept_inventory)
            + "\n"
        )

    @staticmethod
    def get_keyword_support_system_prompt() -> str:
        general_rules = _extract_general_rules()
        structured_rules = _extract_template_section("### search_optimized.keyword.structured")
        phrases_rules = _extract_template_section("### search_optimized.keyword.phrases")
        terms_rules = _extract_template_section("### search_optimized.keyword.terms")
        return (
            "You produce only one JSON object matching KeywordSupportResponse: "
            '{"phrases": [], "required": [], "optional": [], "excluded": []}\n\n'
            "Note: `structured` (the Boolean query string) is produced by a separate call. "
            "Do not emit it here.\n\n"
            f"## General Rules\n\n{general_rules}\n\n"
            f"## Field Specification: search_optimized.keyword.structured (for context only)\n\n{structured_rules}\n\n"
            f"## Field Specification: search_optimized.keyword.phrases\n\n{phrases_rules}\n\n"
            f"## Field Specification: search_optimized.keyword.terms\n\n{terms_rules}"
        )

    @staticmethod
    def get_keyword_support_prompt(
        integrated_statement: str,
        concept_inventory: List[str],
        terminology_synonyms: Dict[str, List[str]],
    ) -> str:
        inventory_text = "\n".join(f"- {c}" for c in concept_inventory)
        return (
            f"## Integrated Statement\n\n{integrated_statement}\n\n"
            f"## Concept Inventory\n\n{inventory_text}\n\n"
            f"## Terminology Synonyms\n\n{json.dumps(terminology_synonyms, ensure_ascii=False, indent=2)}\n"
        )

    @staticmethod
    def get_filter_resolution_system_prompt() -> str:
        general_rules = _extract_general_rules()
        years_rules = _extract_template_section("### search_filters.publication_years")
        venues_rules = _extract_template_section("### search_filters.venues")
        authors_rules = _extract_template_section("### search_filters.authors")
        pub_types_rules = _extract_template_section("### search_filters.publication_types")
        fos_rules = _extract_template_section("### search_filters.fields_of_study")
        return (
            "You produce only one JSON object matching FilterSuggestionResponse: "
            '{"publication_years": "", "venues": [], "authors": [], '
            '"publication_types": [], "fields_of_study": []}\n\n'
            f"## General Rules\n\n{general_rules}\n\n"
            f"## Field Specification: search_filters.publication_years\n\n{years_rules}\n\n"
            f"## Field Specification: search_filters.venues\n\n{venues_rules}\n\n"
            f"## Field Specification: search_filters.authors\n\n{authors_rules}\n\n"
            f"## Field Specification: search_filters.publication_types\n\n{pub_types_rules}\n\n"
            f"## Field Specification: search_filters.fields_of_study\n\n{fos_rules}"
        )

    @staticmethod
    def get_filter_resolution_prompt(
        original_input: str,
        accepted_dimensions: Dict[str, Any],
        permitted_values: List[str],
    ) -> str:
        from datetime import datetime
        current_year = datetime.now().year
        return (
            f"## Current Year\n\n{current_year}\n\n"
            f"## Original Input\n\n{original_input}\n\n"
            f"## Accepted Dimensions\n\n{json.dumps(accepted_dimensions, ensure_ascii=False, indent=2)}\n\n"
            f"## Permitted Fields of Study Values\n\n{json.dumps(permitted_values, ensure_ascii=False)}\n"
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