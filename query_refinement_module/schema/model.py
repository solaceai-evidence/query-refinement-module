"""
Core data model for query refinement aspects.

This module defines the RefinementAspect class which represents a single
characteristic along which a query can be refined.
"""

from dataclasses import dataclass, field, asdict
from typing import List, Optional, Any, Dict, TypedDict, NotRequired
import logging
import json

from ..prompt.system_role import (
    DEFAULT_SYSTEM_PROMPT_REFINEMENT_START,
)

logger = logging.getLogger(__name__)


# Type definitions for example structures - each category has suggested fields
class BaseExample(TypedDict):
    """Base example - must have statement (primary) or query (legacy)."""
    statement: NotRequired[str]  # Primary field: works for questions, aims, descriptions, paragraphs
    query: NotRequired[str]  # Legacy field: maintained for backward compatibility

class ClearExample(BaseExample, total=False):
    """
    Example demonstrating clear, complete specification.
    
    Suggested fields:
        statement: The statement/context for the example (REQUIRED)
        query: Legacy alternative (DEPRECATED)
        rationale: NotRequired[str]
    """
    rationale: NotRequired[str]


class NeedsRefinementExample(BaseExample, total=False):
    """
    Example demonstrating missing or incomplete information.
    
    Suggested fields:
        statement: The statement/context for the example (REQUIRED)
        query: Legacy alternative (DEPRECATED)
        issue: What information is missing or incomplete
        missing: Specifically what details are absent
        example_question: Example question to clarify the gap
    """
    issue: NotRequired[str]
    missing: NotRequired[str]
    example_question: NotRequired[str]


class PartialExample(BaseExample, total=False):
    """
    Example demonstrating partially specified information.
    
    Suggested fields:
        statement: The statement/context for the example (REQUIRED)
        query: Legacy alternative (DEPRECATED)
        has: What information is present
        missing: What information is still needed
        example_question: Example question to get missing details
    """
    has: NotRequired[str]
    missing: NotRequired[str]
    example_question: NotRequired[str]


class AmbiguousExample(BaseExample, total=False):
    """
    Example demonstrating vague or unclear specification.
    
    Suggested fields:
        statement: The statement/context for the example (REQUIRED)
        query: Legacy alternative (DEPRECATED)
        issue: What makes this example ambiguous or vague
        example_question: Example question to clarify the ambiguity
        guidance: Direction for the model on how to handle similar statements.
    """
    issue: NotRequired[str]
    example_question: NotRequired[str]
    guidance: NotRequired[str]


class OtherExample(BaseExample, total=False):
    """
    Example capturing edge cases that do not map cleanly to the predefined buckets.

    Suggested fields:
        query: an example query (REQUIRED if not domain)
        domain: The domain/context for the example (REQUIRED if not query)
        issue: What makes this example unique or edge-case
        note: Additional context describing the pitfall or why it matters.
        guidance: Direction for the model on how to handle similar queries.
        example_question: Example follow-up question if clarification is useful.
    """
    issue: NotRequired[str]
    note: NotRequired[str]
    guidance: NotRequired[str]
    example_question: NotRequired[str]


class ExamplesDict(TypedDict, total=False):
    """
    Structure for examples field - all categories are optional.
    
    Each category uses a specific example type with recommended fields:
        clear: ClearExample - Examples with complete information
        needs_refinement: NeedsRefinementExample - Examples missing critical information
        partial: PartialExample - Examples with some but not all information
        ambiguous: AmbiguousExample - Examples with vague specifications
        other: OtherExample - Edge cases or guidance that does not fit other buckets
    """
    clear: NotRequired[List[ClearExample]]
    needs_refinement: NotRequired[List[NeedsRefinementExample]]
    partial: NotRequired[List[PartialExample]]
    ambiguous: NotRequired[List[AmbiguousExample]]
    other: NotRequired[List[OtherExample]]


__all__ = [
    "RefinementAspect",
    "ExamplesDict",
    "ClearExample",
    "NeedsRefinementExample", 
    "PartialExample",
    "AmbiguousExample",
    "OtherExample",
]


@dataclass
class RefinementAspect:
    """ 
    A refinement aspect along which a query can be refined.

    Each aspect represents a specific characteristic of the query that may need 
    clarification, such as temporal scope, target population, methodology, etc.

    The aspect includes:
    - An analysis prompt to determine if refinement is needed
    - Optional system prompt to set the AI's role/persona
    - Optional example queries for few-shot learning and prompt engineering
    - A response format specification for consistent, structured responses
    - Optional follow-up configuration
    - Extensible metadata

    Response Format Structure:
    - Base fields (always included): is_complete, reasoning, refined_value, next_question

    Attributes:
        id: Unique identifier for the refinement aspect
        aspect_name: Human-readable refinement aspect name
        aspect_description: Brief description of what this refinement aspect refines
        system_prompt: Optional system-level prompt defining the AI's role/persona for this refinement aspect
        refinement_instructions: Developer-based Prompt template for analyzing the query (must include {query})
        examples: Optional example queries for few-shot learning and prompt engineering
        response_format: Expected response structure (optional, for structured responses)
        depends_on: List of refinement aspect IDs this refinement aspect depends on (for context)
        allow_follow_up: Whether follow-up questions are allowed (default: True)
        max_follow_ups: Maximum number of follow-up rounds allowed (default: 3)
        metadata: Additional metadata for extensibility
    """
    id: str
    aspect_name: str
    aspect_description: str
    # developer prompt - should focus on analysis logic, not response format (REQUIRED)
    refinement_instructions: str
    
    # Optional: System prompt defining AI role/persona for this refinement aspect (if none, use system-level default)
    # Example: "You are a clinical research expert specializing in population definition."
    system_prompt: Optional[str] = None

    # Optional: Example queries for few-shot learning and prompt engineering
    # Helps the LLM understand what constitutes clear, incomplete, or ambiguous specifications
    # All categories are optional, but if provided must follow ExamplesDict structure
    examples: Optional[ExamplesDict] = None
    
    # Optional: Define expected response format separately from the prompt
    # This allows for consistent response structures and validation
    response_format: Optional[Dict[str, Any]] = None
    
    # DEPRECATED fields - kept for backward compatibility
    value_field_type: str = "string"
    value_field_description: Optional[str] = None
    
    # Dependencies: List of refinement aspect IDs this refinement aspect depends on
    # Only declared dependencies will be included in the analysis context
    depends_on: List[str] = field(default_factory=list)
    
    # Should this refinement aspect support follow-up question to the initial suggested question?
    allow_follow_up: bool = True
    # Maximum number of follow-ups allowed (if follow-ups are allowed)
    max_follow_ups: int = 3

    # Optional metadata for extensibility
    # e.g., domain, priority, examples, options, etc.
    metadata: Dict[str, Any] = field(default_factory=dict)

    # Base schema fields for unified response format (used by unified_analysis_prompt.py)
    BASE_SCHEMA_FIELDS = {
        "is_complete": "boolean",
        "reasoning": "string",
        "refinement_aspect_value": "string",
        "next_question": "string"
    }

    # Field descriptions for the base schema fields
    BASE_FIELD_DESCRIPTIONS = {
        "is_complete": "Whether this aspect is sufficiently refined and clear (true/false)",
        "reasoning": "Brief explanation of why the aspect is/isn't complete",
        "refinement_aspect_value": "Extracted or synthesized value (required if is_complete=true)",
        "next_question": "Focused clarifying question (required if is_complete=false)"
    }
    
    # Unified analysis prompt template (used for both initial and follow-up analysis)
    UNIFIED_ANALYSIS_PROMPT = """
**Dimension to evaluate:** {aspect_name}
**Definition:** {aspect_description}

**Original Research Input:** "{original_query}"

{conversation_section}

{dependency_section}

---

{refinement_instructions}

{examples_section}

---

{output_format_section}
"""

    def __post_init__(self):
        """Validate schema structure at load time."""
        # 1. Validate value_field_type
        valid_types = {"string", "boolean", "integer", "float", "array", "object"}
        if self.value_field_type.lower() not in valid_types:
            raise ValueError(
                f"Invalid value_field_type '{self.value_field_type}' for aspect '{self.id}'. "
                f"Valid types: {', '.join(sorted(valid_types))}"
            )
        
        # 2. Validate response_format structure (if provided)
        if self.response_format:
            self._validate_response_format_structure()
        
        # 3. Validate examples structure (if provided)
        if self.examples:
            self._validate_examples_structure()
    
    def _validate_response_format_structure(self):
        """
        Validate the response_format configuration structure at load time.
        
        Checks that:
        - Field types are from the allowed set
        - Field descriptions reference valid fields
        
        Raises:
            ValueError: If response_format structure is invalid
        """
        valid_types = {"string", "boolean", "integer", "float", "array", "object"}
        
        # Check additional_fields uses valid types
        additional_fields = self.response_format.get("additional_fields", {}) if self.response_format else {}
        if additional_fields:
            if not isinstance(additional_fields, dict):
                raise ValueError(
                    f"Schema '{self.aspect_name}': 'additional_fields' must be a dictionary"
                )
            
            for field_name, field_type in additional_fields.items():
                if not isinstance(field_type, str):
                    raise ValueError(
                        f"Schema '{self.aspect_name}': Field type for '{field_name}' must be a string"
                    )
                
                if field_type.lower() not in valid_types:
                    raise ValueError(
                        f"Schema '{self.aspect_name}': Invalid type '{field_type}' for field '{field_name}'. "
                        f"Valid types: {', '.join(sorted(valid_types))}"
                    )
        
        # Check field_descriptions keys match additional_fields (warning, not error)
        field_descriptions = self.response_format.get("field_descriptions", {}) if self.response_format else {}
        if field_descriptions:
            if not isinstance(field_descriptions, dict):
                logger.warning(
                    f"Schema '{self.aspect_name}': 'field_descriptions' should be a dictionary"
                )
            else:
                # Check for descriptions of fields that don't exist
                defined_fields = set(additional_fields.keys()) if additional_fields else set()
                extra_descriptions = set(field_descriptions.keys()) - defined_fields
                
                if extra_descriptions:
                    logger.warning(
                        f"Schema '{self.aspect_name}': field_descriptions contains keys not in additional_fields: "
                        f"{', '.join(sorted(extra_descriptions))}"
                    )
    
    def _validate_examples_structure(self):
        """
        Validate the examples structure at load time.
        
    Ensures:
    - examples is a dict
    - Only valid category keys are used (clear, needs_refinement, partial, vague_ambiguous, other)
        - Each category contains a list
        - Each example in the list is a dict with at least a 'query'/'statement' field
        
        Raises:
            ValueError: If examples structure is invalid
        """
        if not isinstance(self.examples, dict):
            raise ValueError(
                f"Schema '{self.aspect_name}': 'examples' must be a dictionary"
            )
        
        # Valid category keys
        valid_categories = {"clear", "needs_refinement", "partial", "vague_ambiguous", "other"}
        
        # Check for invalid category keys
        invalid_keys = set(self.examples.keys()) - valid_categories
        if invalid_keys:
            raise ValueError(
                f"Schema '{self.aspect_name}': Invalid example categories: {', '.join(sorted(invalid_keys))}. "
                f"Valid categories: {', '.join(sorted(valid_categories))}"
            )
        
        # Validate each category
        for category, examples_list in self.examples.items():
            if not isinstance(examples_list, list):
                raise ValueError(
                    f"Schema '{self.aspect_name}': examples['{category}'] must be a list"
                )
            
            # Validate each example in the category
            for idx, example in enumerate(examples_list, 1):
                if not isinstance(example, dict):
                    raise ValueError(
                        f"Schema '{self.aspect_name}': examples['{category}'][{idx}] must be a dictionary"
                    )
                
                # Validate that example has at least query or statement
                if "query" not in example and "statement" not in example:
                    raise ValueError(
                        f"Schema '{self.aspect_name}': examples['{category}'][{idx}] must have either 'query' or 'statement' field"
                    )
                
                if "query" in example and not isinstance(example["query"], str):
                    raise ValueError(
                        f"Schema '{self.aspect_name}': examples['{category}'][{idx}]['query'] must be a string"
                    )
                
                if "statement" in example and not isinstance(example["statement"], str):
                    raise ValueError(
                        f"Schema '{self.aspect_name}': examples['{category}'][{idx}]['statement'] must be a string"
                    )
            
                
                # Validate optional fields are strings if present
                optional_fields = {
                    "rationale",
                    "issue",
                    "missing",
                    "has",
                    "example_question",
                    "clarifying_question",
                    "explanation",
                    "note",
                    "guidance",
                    "domain",
                }
                for field_name in example.keys():
                    if field_name == "query" or field_name == "statement":
                        continue  # Already validated
                    
                    if field_name not in optional_fields:
                        logger.warning(
                            f"Schema '{self.aspect_name}': examples['{category}'][{idx}] has unexpected field '{field_name}'. "
                            f"Valid fields: query (required), {', '.join(sorted(optional_fields))} (optional)"
                        )
                    
                    # Ensure the field value is a string
                    if not isinstance(example[field_name], str):
                        raise ValueError(
                            f"Schema '{self.aspect_name}': examples['{category}'][{idx}]['{field_name}'] must be a string"
                        )

    def get_refinement_instructions_prompt(self, statement: str) -> str:
        """
        Generate the developer prompt including examples and response format instructions.
        
        Args:
            statement: The user's statement to be analyzed and refined
        Returns:
            Complete developer prompt with statement inserted and response format appended
        """
        prompt_parts = []

        # Always start with the user's research input explicitly stated
        
        # Check if refinement_instructions contains {query}/{input}/{statement} placeholder
        if "{input}" in self.refinement_instructions or "{statement}" in self.refinement_instructions or "{query}" in self.refinement_instructions:
            # Format the developer prompt with the statement submitted by the user
            prompt_parts.append(
                self.refinement_instructions.format(query=statement, statement=statement,input=statement)
            )
        else:
            # Prepend the user's input explicitly, then add the analysis prompt as-is
            prompt_parts.append(f"## Analyze this research input: {statement}.\n")
            prompt_parts.append(self.refinement_instructions)
        
        # Inject examples if available
        if self.examples:
            examples_section = self._format_examples()
            if examples_section:
                prompt_parts.append(examples_section)
        
        # Always append response format (base schema at minimum)
        prompt_parts.append(self._format_response_instructions())
        
        return "\n\n".join(prompt_parts)
    
    def get_system_role(self) -> str:
        """
        Get the system role prompt for this refinement aspect.
        
        Returns:
            System role prompt if defined, otherwise a generic default with description
        """
        if self.system_prompt and self.system_prompt.strip():
            return self.system_prompt
        
        # Default system prompt (concise to save tokens) - format template variables
        try:
            return DEFAULT_SYSTEM_PROMPT_REFINEMENT_START.format(
                self=self
            )
        except (KeyError, AttributeError):
            # Fallback if formatting fails
            return DEFAULT_SYSTEM_PROMPT_REFINEMENT_START
    
    def get_prompts(self, query: str) -> tuple[str, str]:
        """
        Get both system and developer prompts for this refinement aspect.
        
        Args:
            query: The user's query to analyze
            
        Returns:
            Tuple of (system_prompt, developer_prompt)
        """
        return self.get_system_role(), self.get_refinement_instructions_prompt(query)

    def _format_examples(self) -> str:
        """
        Format examples into a readable section for prompt inclusion.
        
        Supports multiple example categories:
        - clear: Examples with all information properly specified
        - needs_refinement: Examples missing critical information
        - partial: Examples with some but not all information
        - ambiguous: Examples with vague or unclear specifications
        - other: Edge cases or guidance that fall outside the standard buckets
        
        Returns:
            Formatted examples section, or empty string if no examples
        """
        if not self.examples:
            return ""
        
        sections = []
        
        # Category display config: (key, header, prefix)
        category_config = [
            ("clear", "CLEAR SPECIFICATIONS:"),
            ("needs_refinement", "NEEDS CLARIFICATION:"),
            ("partial", "PARTIAL INFORMATION:"),
            ("vague_ambiguous", "VAGUE OR AMBIGUOUS:"),
            ("other", "ADDITIONAL GUIDANCE:"),
        ]
        
        def ensure_period(text: str) -> str:
            """Add period only if text doesn't end with punctuation."""
            return text if text.rstrip().endswith(('.', '!', '?')) else text.rstrip() + '.'
        
        for category_key, header in category_config:
            if category_key in self.examples and self.examples[category_key]:
                sections.append(header)
                
                for example in self.examples[category_key]:
                    # Support both 'statement' (primary) and 'query' (legacy) as the main example field
                    statement = example.get("statement", "") or example.get("query", "")
                    statement = ensure_period(statement)
                    
                    # Build example line based on available fields
                    # Prefix the example with the field name for clarity (statement or legacy query)
                    primary_field = "statement" if "statement" in example else "query"
                    line_parts = [f"{primary_field}: \"{statement}\""]
                    
                    # Add explanatory fields in priority order
                    if "rationale" in example:
                        line_parts.append(f"rationale: {ensure_period(example['rationale'])}")
                    elif "issue" in example:
                        line_parts.append(f"Issue: {ensure_period(example['issue'])}")
                    elif "missing" in example:
                        line_parts.append(f"Missing: {ensure_period(example['missing'])}")
                    
                    # Add context about what's present (for partial examples)
                    if "has" in example:
                        line_parts.append(f"Has: {ensure_period(example['has'])}")
                    
                    # Add optional suggested question for refinement examples
                    if "example_question" in example:
                        line_parts.append(f"Example Q: \"{ensure_period(example['example_question'])}\"")
                    
                    # Add notes/guidance for 'other' examples 
                    if "note" in example:
                        line_parts.append(f"Note: {ensure_period(example['note'])}")

                    if "guidance" in example:
                        line_parts.append(f"Guidance: {ensure_period(example['guidance'])}")

                    sections.append("  - " + " ".join(line_parts))
                
                sections.append("")  # Blank line after each category
        
        if not sections:
            return ""
        
        # Add header for the entire examples section
        return "--- GUIDANCE EXAMPLES ---\n" + "\n".join(sections)
    
    def _get_complete_schema_fields(self) -> Dict[str, str]:
        """
        Get complete schema fields including base fields and dynamic value field.
        
        Returns:
            Dictionary mapping field names to types
        """
        # Start with base fields
        schema = self.BASE_SCHEMA_FIELDS.copy()
        
        # Add dynamic value field using aspect.id as field name
        schema[self.id] = self.value_field_type
        
        # Add any additional custom fields from response_format
        if self.response_format:
            additional = self.response_format.get("additional_fields", {})
            schema.update(additional)
        
        return schema
    
    def _get_complete_field_descriptions(self) -> Dict[str, str]:
        """
        Get complete field descriptions including auto-generated synthesis instructions.
        
        Returns:
            Dictionary mapping field names to descriptions
        """
        descriptions = self.BASE_FIELD_DESCRIPTIONS.copy()
        
        
        user_desc = self.value_field_description or f"The {self.aspect_name}"
        
        synthesis_instructions = (
            "\nSYNTHESIS REQUIRED: Update this field incrementally at EVERY response. "
            "Combine ALL previous user responses into this single field. "
            "Remove conversational language, filler words, and meta-commentary. "
            "Keep only factual content in clear, declarative form."
        )
        
        descriptions[self.id] = f"{user_desc}{synthesis_instructions}"
        
        # Add custom descriptions from response_format
        if self.response_format:
            custom = self.response_format.get("field_descriptions", {})
            descriptions.update(custom)
        
        return descriptions
    
    def _format_response_instructions(self) -> str:
        """
        Format response_format into clear instructions.
        Includes base fields, dynamic value field, and any additional custom fields.
        """
        instructions = ["Respond in the following JSON format:"]
        
        # Get complete schema with dynamic field
        complete_schema = self._get_complete_schema_fields()
        complete_descriptions = self._get_complete_field_descriptions()
        
        # Show schema example
        schema_example = {key: f"<{ftype}>" for key, ftype in complete_schema.items()}
        instructions.append(f"\n```json\n{json.dumps(schema_example, indent=2)}\n```")
        
        # Add field descriptions
        instructions.append("\nField descriptions:")
        for field_name, ftype in complete_schema.items():
            desc = complete_descriptions.get(field_name, f"Value of type {ftype}")
            
            # Mark required fields (base fields + dynamic value field)
            is_required = (
                field_name in self.BASE_SCHEMA_FIELDS or 
                field_name == self.id  # Dynamic value field is REQUIRED
            )
            required_tag = " (REQUIRED)" if is_required else " (optional)"
            
            instructions.append(f"- {field_name} ({ftype}){required_tag}: {desc}")
        
        return "\n".join(instructions)
    
    def validate_response(self, response: Dict[str, Any]) -> tuple[bool, Optional[str]]:
        """
        Validate that a response contains all required fields with correct types.
        Validates base fields, dynamic value field, and custom fields.
        
        Args:
            response: The response dictionary to validate
            
        Returns:
            Tuple of (is_valid, error_message)
        """
        # Check base fields for unified response format
        missing_fields = []
        
        # Required fields: is_complete, reasoning
        if "is_complete" not in response:
            missing_fields.append("is_complete")
        if "reasoning" not in response:
            missing_fields.append("reasoning")
        
        # Either refinement_aspect_value OR next_question must be present (mutually exclusive)
        has_refined = "refinement_aspect_value" in response
        has_next_q = "next_question" in response
        if not has_refined and not has_next_q:
            missing_fields.append("refinement_aspect_value OR next_question")

        if missing_fields:
            return False, f"Missing required fields: {', '.join(missing_fields)}"
        
        # Validate base field types
        validation_errors = []
        
        # Validate is_complete (boolean)
        if not isinstance(response.get("is_complete"), bool):
            validation_errors.append("'is_complete' must be a boolean")
        
        # Validate reasoning (string)
        if not isinstance(response.get("reasoning"), str):
            validation_errors.append("'reasoning' must be a string")
        
        # Validate conditional fields based on is_complete
        is_complete = response.get("is_complete", False)
        if is_complete:
            refinement_aspect_value = response.get("refinement_aspect_value")
            if not refinement_aspect_value or not isinstance(refinement_aspect_value, str):
                validation_errors.append("'refinement_aspect_value' required as non-empty string when is_complete=true")
        else:
            next_question = response.get("next_question")
            if not next_question or not isinstance(next_question, str):
                validation_errors.append("'next_question' required as non-empty string when is_complete=false")
        
        # Legacy: Validate dynamic value field type if present (deprecated)
        if self.id in response:
            value = response[self.id]
            type_valid, type_error = self._validate_field_type(
                self.id, value, self.value_field_type
            )
            if not type_valid:
                validation_errors.append(type_error)
        
        # Validate custom fields if response_format is defined
        if self.response_format:
            additional_fields = self.response_format.get("additional_fields", {})
            
            for field_name, field_type in additional_fields.items():
                if field_name in response:
                    # Validate the type
                    value = response[field_name]
                    type_valid, type_error = self._validate_field_type(
                        field_name, value, field_type
                    )
                    if not type_valid:
                        validation_errors.append(type_error)
        
        if validation_errors:
            return False, "; ".join(validation_errors)
        
        return True, None
    
    def _validate_field_type(
        self, field_name: str, value: Any, expected_type: str
    ) -> tuple[bool, Optional[str]]:
        """
        Validate that a field value matches its expected type.
        
        Args:
            field_name: Name of the field being validated
            value: The actual value to validate
            expected_type: Expected type as string (e.g., "string", "integer", "array")
            
        Returns:
            Tuple of (is_valid, error_message)
        """
        type_map = {
            "string": str,
            "boolean": bool,
            "integer": int,
            "float": (int, float),  # Accept both int and float for float fields
            "array": list,
            "object": dict,
        }
        
        expected_type_lower = expected_type.lower()
        
        if expected_type_lower not in type_map:
            # Unknown type, skip validation but log warning
            logger.warning(
                f"Unknown type '{expected_type}' for field '{field_name}'. "
                f"Skipping type validation."
            )
            return True, None
        
        expected_python_type = type_map[expected_type_lower]
        
        if not isinstance(value, expected_python_type):
            actual_type = type(value).__name__
            return False, f"Field '{field_name}' must be {expected_type} (got {actual_type})"
        
        # Additional validation for specific types
        if expected_type_lower == "float" and isinstance(value, bool):
            # bool is a subclass of int in Python, so we need to explicitly reject it for float
            return False, f"Field '{field_name}' must be float (got boolean)"
        
        if expected_type_lower == "integer" and isinstance(value, bool):
            # Same issue with boolean being treated as int
            return False, f"Field '{field_name}' must be integer (got boolean)"
        
        return True, None
    
    def validate_response_strict(
        self, response: Dict[str, Any]
    ) -> tuple[bool, Optional[str], List[str]]:
        """
        Strict validation that also checks for unexpected fields.
        
        Args:
            response: The response dictionary to validate
            
        Returns:
            Tuple of (is_valid, error_message, warnings)
        """
        # First do standard validation
        is_valid, error_message = self.validate_response(response)
        
        if not is_valid:
            return False, error_message, []
        
        # Check for unexpected fields
        warnings = []
        expected_fields = set(self.BASE_SCHEMA_FIELDS.keys())
        
        # Add dynamic value field to expected fields
        expected_fields.add(self.id)
        
        if self.response_format:
            additional_fields = self.response_format.get("additional_fields", {})
            expected_fields.update(additional_fields.keys())
        
        actual_fields = set(response.keys())
        unexpected_fields = actual_fields - expected_fields
        
        if unexpected_fields:
            warnings.append(
                f"Response contains unexpected fields: {', '.join(unexpected_fields)}"
            )
        
        return True, None, warnings

    def build_unified_prompt(
        self,
        original_query: str,
        follow_up_history: List[Dict[str, str]],
        dependency_context: Dict[str, Dict[str, Any]],
        mode: str = 'initial'
    ) -> str:
        """
        Build complete unified prompt for refinement analysis.
        
        This orchestrates all sections of the prompt including conversation history,
        dependencies, instructions, and examples.
        
        Args:
            original_query: The original user query
            follow_up_history: List of Q&A exchanges for this aspect
            dependency_context: Dict mapping aspect IDs to their completed values
            mode: 'initial' or 'followup' (determines if conversation history is shown)
        
        Returns:
            Complete formatted prompt ready for LLM
        """
        # Build each section
        conversation_section = self._build_conversation_section(follow_up_history, mode)
        dependency_section = self._build_dependency_section(dependency_context)
        refinement_instructions = self._build_refinement_instructions_section(original_query)
        examples_section = self._build_examples_section_for_prompt()
        output_format_section = self._build_output_format_section()
        
        # Format the complete prompt
        return self.UNIFIED_ANALYSIS_PROMPT.format(
            aspect_name=self.aspect_name,
            aspect_description=self.aspect_description,
            original_query=original_query,
            conversation_section=conversation_section,
            dependency_section=dependency_section,
            refinement_instructions=refinement_instructions,
            examples_section=examples_section,
            output_format_section=output_format_section
        )
    
    def _build_output_format_section(self) -> str:
        """
        Build the output format section dynamically from BASE_SCHEMA_FIELDS and BASE_FIELD_DESCRIPTIONS.
        
        This ensures single source of truth - if field definitions change, the prompt updates automatically.
        
        Returns:
            Formatted output format section with JSON schema and rules
        """
        lines = ["**OUTPUT (JSON):**", ""]
        
        # Build JSON example from BASE_SCHEMA_FIELDS
        json_example = "{"
        for field_name, field_type in self.BASE_SCHEMA_FIELDS.items():
            # Show example values based on type
            if field_type == "boolean":
                example_value = "true/false"
            elif field_type == "float":
                example_value = "0.0-1.0"
            elif field_type == "string":
                # Use description hints for string fields
                if field_name == "reasoning":
                    example_value = '"why complete/incomplete (1-2 sentences)"'
                elif field_name == "refinement_aspect_value":
                    example_value = '"clear, specific value (if complete) OR null"'
                elif field_name == "next_question":
                    example_value = '"focused question with inline examples (if incomplete) OR null"'
                else:
                    example_value = '"<string>"'
            else:
                example_value = f'"<{field_type}>"'
            
            lines.append(f'  "{field_name}": {example_value},')
        
        # Remove trailing comma from last field
        if lines[-1].endswith(','):
            lines[-1] = lines[-1][:-1]
        
        lines.append("}")
        lines.append("")
        
        # Add rules section
        lines.append("**Rules:**")
        lines.append("- `is_complete=true` → `refinement_aspect_value` must be non-null, `next_question` must be null")
        lines.append("- `is_complete=false` → `next_question` must be non-null, `refinement_aspect_value` must be null")
        
        # Add field-specific guidance from descriptions
        refinement_desc = self.BASE_FIELD_DESCRIPTIONS.get("refinement_aspect_value", "")
        if "verbatim" in refinement_desc.lower() or "exact" in refinement_desc.lower():
            lines.append("- `refinement_aspect_value`: Extract verbatim from original input/dependency context, or combine user's answers preserving their exact wording and intended meaning. Do NOT rephrase or reinterpret—capture what the user actually said.")
        
        next_q_desc = self.BASE_FIELD_DESCRIPTIONS.get("next_question", "")
        if "example" in next_q_desc.lower():
            lines.append("- `next_question`: Include concrete options or examples inline within the question text")
        
        return "\n".join(lines)
    
    def _build_conversation_section(
        self,
        follow_up_history: List[Dict[str, str]],
        mode: str
    ) -> str:
        """
        Build conversation history section.
        
        Args:
            follow_up_history: List of Q&A exchanges
            mode: 'initial' (no history) or 'followup' (with history)
        
        Returns:
            Formatted conversation section (empty for initial mode)
        """
        if mode == 'initial' or not follow_up_history:
            return ""
        
        lines = ["**Conversation History:**\n"]
        for i, turn in enumerate(follow_up_history, 1):
            question = turn.get('question', '')
            response = turn.get('response', '')
            lines.append(f"Q{i}: {question}")
            lines.append(f"A{i}: {response}\n")
        
        return "\n".join(lines)
    
    def _build_dependency_section(
        self,
        dependency_context: Dict[str, Dict[str, Any]]
    ) -> str:
        """
        Build dependency context showing completed aspects.
        
        If current aspect depends on shown aspects, adds a visual marker.
        
        Args:
            dependency_context: Dict mapping aspect IDs to their context
        
        Returns:
            Formatted dependency section (empty if no dependencies)
        """
        if not dependency_context:
            return ""
        
        lines = ["**Completed Aspects (for context):**\n"]
        
        has_dependencies = bool(self.depends_on)
        
        for dep_id, context in dependency_context.items():
            aspect_name = context.get('name', dep_id)
            aspect_desc = context.get('description', '')
            refined_value = context.get('value', '')
            
            # Mark if current aspect depends on this
            dependency_marker = ""
            if has_dependencies and dep_id in self.depends_on:
                dependency_marker = " ⚠️ (this aspect depends on this)"
            
            lines.append(f"**{aspect_name}**{dependency_marker}")
            if aspect_desc:
                lines.append(f"  Description: {aspect_desc}")
            lines.append(f"  Refined Value: {refined_value}\n")
        
        if has_dependencies:
            lines.append("\n⚠️ = Consider these values when analyzing the current aspect\n")
        
        return "\n".join(lines)
    
    def _build_refinement_instructions_section(self, query: str) -> str:
        """
        Build refinement instructions section.
        
        This uses the aspect's refinement_instructions which contains
        type-specific evaluation criteria and objectives.
        
        Args:
            query: Original query to analyze
        
        Returns:
            Formatted refinement instructions with header
        """
        # Get the refinement instructions (already formatted)
        instructions = self.get_refinement_instructions_prompt(statement=query)
        
        # Add a header
        return f"**Analysis Guidelines:**\n\n{instructions}\n"
    
    def _build_examples_section_for_prompt(self) -> str:
        """
        Build examples section from aspect schema for inclusion in unified prompt.
        
        Examples come AFTER refinement instructions in the prompt.
        Categories: clear, needs_refinement, partial, vague_ambiguous, other
        
        Returns:
            Formatted examples section (empty if no examples)
        """
        if not self.examples:
            return ""
        
        lines = ["**Examples:**\n"]
        
        # Process each category
        category_map = {
            'clear': 'Clear Examples',
            'needs_refinement': 'Needs Refinement',
            'partial': 'Partial Examples',
            'vague_ambiguous': 'Vague/Ambiguous Examples',
            'other': 'Other Cases'
        }
        
        for category, examples_list in self.examples.items():
            if not examples_list:
                continue
            
            category_title = category_map.get(category, category.replace('_', ' ').title())
            lines.append(f"\n{category_title}:")
            
            # Ensure examples_list is actually a list
            if not isinstance(examples_list, list):
                logger.warning(f"Examples category '{category}' is not a list, skipping")
                continue
            
            for ex in examples_list:
                # Get statement or query (statement preferred)
                statement = ex.get('statement') or ex.get('query', '')
                if statement:
                    lines.append(f"- Statement: {statement}")
                
                # Add contextual fields (rationale, issue, missing, etc.)
                for key in ['rationale', 'issue', 'missing', 'has', 'example_question', 'note', 'guidance']:
                    if key in ex:
                        key_title = key.replace('_', ' ').title()
                        lines.append(f"  {key_title}: {ex[key]}")
                
                lines.append("")  # Blank line between examples
        
        return "\n".join(lines)

    def to_dict(self) -> Dict[str, Any]:
        """Convert refinement aspect to dictionary for serialization."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "RefinementAspect":
        """Create RefinementAspect from dictionary."""
        return cls(**data)
