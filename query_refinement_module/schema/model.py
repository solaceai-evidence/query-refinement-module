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
    - An to determine if refinement is needed
    - Optional system prompt to set the AI's role/persona
    - Optional example queries for few-shot learning and prompt engineering
    - A response format specification for consistent, structured responses
    - Optional follow-up configuration
    - Extensible metadata

    Response Format Structure:
    - Base fields (always included): needs_refinement, explanation, example_question
    - Custom fields: Add domain-specific fields via 'additional_fields'
    
    Example response_format:
        {
            "type": "json",
            "additional_fields": {
                "priority": "string",
                "confidence": "float"
            },
            "field_descriptions": {
                "priority": "Urgency level: high, medium, low",
                "confidence": "Confidence score 0.0-1.0"
            }
        }

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
    
    # Optional: System prompt defining AI role/persona for this refinement aspect
    # Example: "You are a clinical research expert specializing in population definition."
    system_prompt: Optional[str] = None

    # Optional: Example queries for few-shot learning and prompt engineering
    # Helps the LLM understand what constitutes clear, incomplete, or ambiguous specifications
    # All categories are optional, but if provided must follow ExamplesDict structure
    examples: Optional[ExamplesDict] = None
    
    # Optional: Define expected response format separately from the prompt
    # This allows for consistent response structures and validation
    response_format: Optional[Dict[str, Any]] = None
    
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

    # Base schema fields that are always required in the response format
    BASE_SCHEMA_FIELDS = {
        "needs_refinement": "boolean",
        "explanation": "string",
        "clarifying_question": "string"
    }

    # Field descriptions for the base schema fields
    BASE_FIELD_DESCRIPTIONS = {
        "needs_refinement": "Whether this query specification needs clarification (true/false)",
        "explanation": "Brief explanation of why the query does or does not need refinement",
        "clarifying_question": "The clarifying question to ask the user if refinement is needed; otherwise empty"
    }

    def __post_init__(self):
        """Validate schema structure at load time."""
        # 1. Validate response_format structure (if provided)
        if self.response_format:
            self._validate_response_format_structure()
        
        # 2. Validate examples structure (if provided)
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
        additional_fields = self.response_format.get("additional_fields", {})
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
        field_descriptions = self.response_format.get("field_descriptions", {})
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
        
        # Default system prompt (concise to save tokens)
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
            ("needs_refinement", "NEEDS REFINEMENT:"),
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
    
    def _format_response_instructions(self) -> str:
        """
        Format response_format into clear instructions.
        Always includes base fields, plus any additional custom fields.
        """
        instructions = ["Respond in the following JSON format:"]
        
        # Build complete schema: base fields + additional fields
        complete_schema = self.BASE_SCHEMA_FIELDS.copy()
        complete_descriptions = self.BASE_FIELD_DESCRIPTIONS.copy()
        
        # Add additional fields if specified
        if self.response_format:
            additional_fields = self.response_format.get("additional_fields", {})
            complete_schema.update(additional_fields)
            
            # Add custom field descriptions if provided
            custom_descriptions = self.response_format.get("field_descriptions", {})
            complete_descriptions.update(custom_descriptions)
        
        if self.response_format:
            schema_example = {key: f"<{ftype}>" for key, ftype in complete_schema.items()}
            instructions.append(f"\n```json\n{json.dumps(schema_example, indent=2)}\n```")
        
        # Add field descriptions
        instructions.append("\nField descriptions:")
        for field_name, ftype in complete_schema.items():
            desc = complete_descriptions.get(field_name, f"Value of type {ftype}")
            required = " (REQUIRED)" if field_name in self.BASE_SCHEMA_FIELDS else " (optional)"
            instructions.append(f"- {field_name} ({ftype}){required}: {desc}")
        
        return "\n".join(instructions)
    
    def validate_response(self, response: Dict[str, Any]) -> tuple[bool, Optional[str]]:
        """
        Validate that a response contains all required fields with correct types.
        Validates both base fields and custom fields defined in response_format.
        
        Args:
            response: The response dictionary to validate
            
        Returns:
            Tuple of (is_valid, error_message)
        """
        # Check all base fields are present
        missing_fields = []
        for field_name in self.BASE_SCHEMA_FIELDS.keys():
            if field_name not in response:
                missing_fields.append(field_name)

        if missing_fields:
            return False, f"Missing required base fields: {', '.join(missing_fields)}"
        
        # Validate base field types
        validation_errors = []
        
        if not isinstance(response.get("needs_refinement"), bool):
            validation_errors.append("'needs_refinement' must be a boolean")
        
        if not isinstance(response.get("explanation"), str):
            validation_errors.append("'explanation' must be a string")
        
        if not isinstance(response.get("clarifying_question"), str):
            validation_errors.append("'clarifying_question' must be a string")
        
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

    def to_dict(self) -> Dict[str, Any]:
        """Convert refinement aspect to dictionary for serialization."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "RefinementAspect":
        """Create RefinementAspect from dictionary."""
        return cls(**data)
