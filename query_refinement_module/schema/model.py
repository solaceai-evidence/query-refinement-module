"""
Core data model for query refinement aspects.

This module defines the RefinementAspect class which represents a single
characteristic along which a query can be refined.
"""

from dataclasses import dataclass, field, asdict
from typing import List, Optional, Any, Dict, TypedDict, Required, NotRequired
import logging
import json

logger = logging.getLogger(__name__)


# Type definitions for example structures - each category has suggested fields
class BaseExample(TypedDict):
    """Base example with required query field."""
    query: Required[str]  # Every example must have a query


class ClearExample(BaseExample, total=False):
    """
    Example demonstrating clear, complete specification.
    
    Suggested fields:
        query: The example query (REQUIRED)
        user_answer: The ideal user answer for this query. To be used when generating follow-up questions.
        explanation: Why this example is clear and complete
    """
    user_answer: NotRequired[str]
    explanation: NotRequired[str]


class NeedsRefinementExample(BaseExample, total=False):
    """
    Example demonstrating missing or incomplete information.
    
    Suggested fields:
        query: The example query (REQUIRED)
        user_answer: an answer that addresses the missing information for this query. To be used when generating follow-up questions.
        issue: What information is missing or incomplete
        missing: Specifically what details are absent
        suggested_question: Example question to clarify the gap
    """
    user_answer: NotRequired[str]
    issue: NotRequired[str]
    missing: NotRequired[str]
    suggested_question: NotRequired[str]


class PartialExample(BaseExample, total=False):
    """
    Example demonstrating partially specified information.
    
    Suggested fields:
        query: The example query (REQUIRED)
        user_answer: an answer that addresses the missing information for this query. To be used when generating follow-up questions.
        has: What information is present
        missing: What information is still needed
        suggested_question: Example question to get missing details
    """
    user_answer: NotRequired[str]
    has: NotRequired[str]
    missing: NotRequired[str]
    suggested_question: NotRequired[str]


class AmbiguousExample(BaseExample, total=False):
    """
    Example demonstrating vague or unclear specification.
    
    Suggested fields:
        query: The example query (REQUIRED)
        user_answer: an answer that addresses the ambiguity for this query. To be used when generating follow-up questions.
        issue: What makes this example ambiguous or vague
        suggested_question: Example question to clarify the ambiguity
    """
    user_answer: NotRequired[str]
    issue: NotRequired[str]
    suggested_question: NotRequired[str]


class ExamplesDict(TypedDict, total=False):
    """
    Structure for examples field - all categories are optional.
    
    Each category uses a specific example type with recommended fields:
        clear: ClearExample - Examples with complete information
        needs_refinement: NeedsRefinementExample - Examples missing critical information
        partial: PartialExample - Examples with some but not all information
        ambiguous: AmbiguousExample - Examples with vague specifications
    """
    clear: NotRequired[List[ClearExample]]
    needs_refinement: NotRequired[List[NeedsRefinementExample]]
    partial: NotRequired[List[PartialExample]]
    ambiguous: NotRequired[List[AmbiguousExample]]


__all__ = [
    "RefinementAspect",
    "ExamplesDict",
    "ClearExample",
    "NeedsRefinementExample", 
    "PartialExample",
    "AmbiguousExample",
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
    - Base fields (always included): needs_refinement, reason, suggested_question
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
        name: Human-readable name
        description: Brief description of what this refinement aspect refines
        system_prompt: Optional system-level prompt defining the AI's role/persona for this refinement aspect
        analysis_prompt: Prompt template for analyzing the query (must include {query})
        examples: Optional example queries for few-shot learning and prompt engineering
        response_format: Expected response structure (optional, for structured responses)
        depends_on: List of refinement aspect IDs this refinement aspect depends on (for context)
        allow_follow_up: Whether follow-up questions are allowed
        max_follow_ups: Maximum number of follow-up rounds
        metadata: Additional metadata for extensibility
    """
    id: str
    name: str
    description: str
    
    # Analysis prompt - should focus on analysis logic, not response format (REQUIRED)
    analysis_prompt: str

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
    
    # Should this refinement aspect support follow-ups?
    allow_follow_up: bool = False
    # Maximum number of follow-ups allowed (if follow-ups are allowed) default = 3
    max_follow_ups: int = 3  

    # Optional metadata for extensibility
    # e.g., domain, priority, examples, options, etc.
    metadata: Dict[str, Any] = field(default_factory=dict)  

    # Base schema fields that are always required in the response format
    BASE_SCHEMA_FIELDS = {
        "needs_refinement": "boolean",
        "reason": "string",
        "suggested_question": "string"
    }

    # Field descriptions for the base schema fields
    BASE_FIELD_DESCRIPTIONS = {
        "needs_refinement": "Whether this refinement aspect needs clarification (true/false)",
        "reason": "Brief explanation of why refinement is or isn't needed",
        "suggested_question": "The question to ask the user (if needs_refinement is true, otherwise can be empty)"
    }

    def __post_init__(self):
        """Validate schema structure at load time."""
        # 1. Check required placeholder
        required_placeholders = ["{query}"]
        for ph in required_placeholders:
            if ph not in self.analysis_prompt:
                raise ValueError(
                    f"Schema '{self.name}': Missing required placeholder: {ph}"
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
        additional_fields = self.response_format.get("additional_fields", {})
        if additional_fields:
            if not isinstance(additional_fields, dict):
                raise ValueError(
                    f"Schema '{self.name}': 'additional_fields' must be a dictionary"
                )
            
            for field_name, field_type in additional_fields.items():
                if not isinstance(field_type, str):
                    raise ValueError(
                        f"Schema '{self.name}': Field type for '{field_name}' must be a string"
                    )
                
                if field_type.lower() not in valid_types:
                    raise ValueError(
                        f"Schema '{self.name}': Invalid type '{field_type}' for field '{field_name}'. "
                        f"Valid types: {', '.join(sorted(valid_types))}"
                    )
        
        # Check field_descriptions keys match additional_fields (warning, not error)
        field_descriptions = self.response_format.get("field_descriptions", {})
        if field_descriptions:
            if not isinstance(field_descriptions, dict):
                logger.warning(
                    f"Schema '{self.name}': 'field_descriptions' should be a dictionary"
                )
            else:
                # Check for descriptions of fields that don't exist
                defined_fields = set(additional_fields.keys()) if additional_fields else set()
                extra_descriptions = set(field_descriptions.keys()) - defined_fields
                
                if extra_descriptions:
                    logger.warning(
                        f"Schema '{self.name}': field_descriptions contains keys not in additional_fields: "
                        f"{', '.join(sorted(extra_descriptions))}"
                    )
    
    def _validate_examples_structure(self):
        """
        Validate the examples structure at load time.
        
        Ensures:
        - examples is a dict
        - Only valid category keys are used (clear, needs_refinement, partial, ambiguous)
        - Each category contains a list
        - Each example in the list is a dict with at least a 'query' field
        
        Raises:
            ValueError: If examples structure is invalid
        """
        if not isinstance(self.examples, dict):
            raise ValueError(
                f"Schema '{self.name}': 'examples' must be a dictionary"
            )
        
        # Valid category keys
        valid_categories = {"clear", "needs_refinement", "partial", "ambiguous"}
        
        # Check for invalid category keys
        invalid_keys = set(self.examples.keys()) - valid_categories
        if invalid_keys:
            raise ValueError(
                f"Schema '{self.name}': Invalid example categories: {', '.join(sorted(invalid_keys))}. "
                f"Valid categories: {', '.join(sorted(valid_categories))}"
            )
        
        # Validate each category
        for category, examples_list in self.examples.items():
            if not isinstance(examples_list, list):
                raise ValueError(
                    f"Schema '{self.name}': examples['{category}'] must be a list"
                )
            
            # Validate each example in the category
            for idx, example in enumerate(examples_list, 1):
                if not isinstance(example, dict):
                    raise ValueError(
                        f"Schema '{self.name}': examples['{category}'][{idx}] must be a dictionary"
                    )
                
                # Check for required 'query' field
                if "query" not in example:
                    raise ValueError(
                        f"Schema '{self.name}': examples['{category}'][{idx}] missing required 'query' field"
                    )
                
                if not isinstance(example["query"], str):
                    raise ValueError(
                        f"Schema '{self.name}': examples['{category}'][{idx}]['query'] must be a string"
                    )
                
                # Validate optional fields are strings if present
                optional_fields = {"explanation", "issue", "missing", "has", "suggested_question", "user_answer"}
                for field_name in example.keys():
                    if field_name == "query":
                        continue  # Already validated
                    
                    if field_name not in optional_fields:
                        logger.warning(
                            f"Schema '{self.name}': examples['{category}'][{idx}] has unexpected field '{field_name}'. "
                            f"Valid fields: query (required), {', '.join(sorted(optional_fields))} (optional)"
                        )
                    
                    # Ensure the field value is a string
                    if not isinstance(example[field_name], str):
                        raise ValueError(
                            f"Schema '{self.name}': examples['{category}'][{idx}]['{field_name}'] must be a string"
                        )

    def get_user_prompt(self, query: str, include_examples: bool = True, include_user_answer: bool = False) -> str:
        """
        Generate the full user prompt including examples by default and response format instructions.
        
        Args:
            query: The user's query to analyze
            include_examples: Whether to include examples in the prompt (default: True)
            
        Returns:
            Complete user prompt with query inserted and response format appended
        """
        # Format the analysis prompt with query
        prompt = self.analysis_prompt.format(query=query)
        
        # Inject examples if available and requested
        if include_examples and self.examples:
            examples_section = self._format_examples(include_user_answer=include_user_answer)
            if examples_section:
                prompt += "\n\n" + examples_section
        
        # Always append response format (base schema at minimum)
        prompt += "\n\n" + self._format_response_instructions()
        
        return prompt
    
    def get_system_prompt(self) -> str:
        """
        Get the system prompt for this refinement aspect.
        
        Returns:
            System prompt if defined, otherwise a generic default with description
        """
        if self.system_prompt:
            return self.system_prompt
        
        # Default system prompt (concise to save tokens)
        return (
            f"You refine scientific queries by analyzing: {self.name} ({self.description}).\n"
            f"Determine if this aspect is missing, incomplete, or ambiguous. "
            f"If yes, ask ONE specific question to clarify."
        )
    
    def get_prompts(self, query: str) -> tuple[str, str]:
        """
        Get both system and user prompts for this refinement aspect.
        
        Args:
            query: The user's query to analyze
            
        Returns:
            Tuple of (system_prompt, user_prompt)
        """
        return self.get_system_prompt(), self.get_user_prompt(query)

    def _format_examples(self, include_user_answer: bool = False) -> str:
        """
        Format examples into a readable section for prompt inclusion.
        
        Supports multiple example categories:
        - clear: Examples with all information properly specified
        - needs_refinement: Examples missing critical information
        - partial: Examples with some but not all information
        - ambiguous: Examples with vague or unclear specifications
        
        Returns:
            Formatted examples section, or empty string if no examples
        """
        if not self.examples:
            return ""
        
        sections = []
        
        # Category display config: (key, header, prefix)
        category_config = [
            ("clear", "EXAMPLES OF CLEAR SPECIFICATIONS:"),
            ("needs_refinement", "EXAMPLES NEEDING REFINEMENT:"),
            ("partial", "EXAMPLES WITH PARTIAL INFORMATION:"),
            ("ambiguous", "EXAMPLES WITH AMBIGUOUS SPECIFICATIONS:"),
        ]
        
        for category_key, header in category_config:
            if category_key in self.examples and self.examples[category_key]:
                sections.append(header)
                
                for example in self.examples[category_key]:
                    query = example.get("query", "")
                    
                    # Build example line based on available fields
                    line_parts = [f'"{query}"']
                    
                    # Add explanatory fields in priority order
                    if "explanation" in example:
                        line_parts.append(f"Explanation: {example['explanation']}")
                    elif "issue" in example:
                        line_parts.append(f"Issue: {example['issue']}")
                    elif "missing" in example:
                        line_parts.append(f"Missing: {example['missing']}")
                    
                    # Add context about what's present (for partial examples)
                    if "has" in example:
                        line_parts.append(f"Has: {example['has']}")
                    
                    # Add optional suggested question for refinement examples
                    if "suggested_question" in example:
                        if include_user_answer in example:
                            line_parts.append(f"Q: \"{example['suggested_question']}\"")
                        else:
                            line_parts.append(f"Ask: \"{example['suggested_question']}\"")
                    
                    # Add optional user answer to the suggested query for refinement examples
                    if include_user_answer and "user_answer" in example:
                        line_parts.append(f"A: \"{example['user_answer']}\"")

                    sections.append("  " + " ".join(line_parts))
                
                sections.append("")  # Blank line after each category
        
        if not sections:
            return ""
        
        # Add header for the entire examples section
        return "--- EXAMPLES FOR GUIDANCE ---\n" + "\n".join(sections)
    
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
        
        # Format the schema as JSON example
        schema_example = {field: f"<{ftype}>" for field, ftype in complete_schema.items()}
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
        
        if not isinstance(response.get("reason"), str):
            validation_errors.append("'reason' must be a string")
        
        if not isinstance(response.get("suggested_question"), str):
            validation_errors.append("'suggested_question' must be a string")
        
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
