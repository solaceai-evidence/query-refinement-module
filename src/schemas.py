"""
This module provides custom refinement schemas loaded from an external YAML file.

Users must specify the path to their custom schemas YAML file using the 
CUSTOM_SCHEMAS_PATH environment variable.

Set the environment variable:
    export CUSTOM_SCHEMAS_PATH=/path/to/your/custom_schemas.yaml

The YAML file should follow this format:

schema_name:
  - id: dimension_id
    name: Dimension Name
    description: Description of the dimension
    
    # Optional: System prompt defining AI's role/persona for this dimension
    system_prompt: |
      You are a [domain] expert specializing in [aspect].
      Your role is to [purpose].
    
    analysis_prompt: |
      Analyze the query: {query}
      
      Focus on analysis logic here, not response format.
      The response format is specified separately below.
    
    # Optional: Define expected response format (recommended for consistency)
    response_format:
      type: json  # or "structured"
      schema:
        needs_refinement: boolean
        reason: string
        suggested_question: string
      field_descriptions:
        needs_refinement: Whether this dimension needs clarification
        reason: Brief explanation of why refinement is or isn't needed
        suggested_question: The question to ask the user (if needs_refinement is true)
    
    allow_follow_up: false  # optional, default=false
    max_follow_ups: 2       # optional, default=2
    metadata:               # optional
      domain: general
      priority: high
"""

import os
from pathlib import Path
from dataclasses import dataclass, field, asdict
from typing import List, Optional, Any, Dict
import logging

logger = logging.getLogger(__name__)

__all__ = [
    # core class
    "RefinementDimension",
    # schema loading functions
    "list_schemas",
    "get_schema",
    "describe_schema"
]


@dataclass
class RefinementDimension:
    """ 
    A dimension along which a query can be refined.

    Each dimension represents a specific aspect or characteristic of the query that may need 
    clarification, such as temporal scope, target population, methodology, etc.

    The dimension includes:
    - An analysis prompt to determine if refinement is needed
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
        id: Unique identifier for the dimension
        name: Human-readable name
        description: Brief description of what this dimension refines
        system_prompt: Optional system-level prompt defining the AI's role/persona for this dimension
        analysis_prompt: Prompt template for analyzing the query (must include {query})
        response_format: Expected response structure (optional, for structured responses)
        allow_follow_up: Whether follow-up questions are allowed
        max_follow_ups: Maximum number of follow-up rounds
        metadata: Additional metadata for extensibility
    """
    id: str
    name: str
    description: str
    
    # Analysis prompt - should focus on analysis logic, not response format
    analysis_prompt: str
    
    # Optional: System prompt defining AI role/persona for this dimension
    # Example: "You are a clinical research expert specializing in population definition."
    system_prompt: Optional[str] = None
    
    # Optional: Define expected response format separately from the prompt
    # This allows for consistent response structures and validation
    response_format: Optional[Dict[str, Any]] = None
    
    # Should this dimension support follow-ups?
    allow_follow_up: bool = False
    # Maximum number of follow-ups allowed (if follow-ups are allowed) default = 2
    max_follow_ups: Optional[int] = 2  

    # Optional metadata for extensibility
    # e.g., domain, priority, related dimensions, examples, options, etc.
    metadata: Dict[str, Any] = field(default_factory=dict)  

    # Base schema fields that are always required
    BASE_SCHEMA_FIELDS = {
        "needs_refinement": "boolean",
        "reason": "string",
        "suggested_question": "string"
    }
    
    BASE_FIELD_DESCRIPTIONS = {
        "needs_refinement": "Whether this dimension needs clarification (true/false)",
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

    def get_full_prompt(self, query: str) -> str:
        """
        Generate the full user prompt including response format instructions.
        
        For system prompt, use get_system_prompt() or get_prompts() for both.
        
        Args:
            query: The user's query to analyze
            
        Returns:
            Complete user prompt with query inserted and response format appended
        """
        prompt = self.analysis_prompt.format(query=query)
        
        # Always append response format (base schema at minimum)
        prompt += "\n\n" + self._format_response_instructions()
        
        return prompt
    
    def get_system_prompt(self) -> str:
        """
        Get the system prompt for this dimension.
        
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
        Get both system and user prompts for this dimension.
        
        Args:
            query: The user's query to analyze
            
        Returns:
            Tuple of (system_prompt, user_prompt)
        """
        return self.get_system_prompt(), self.get_full_prompt(query)
    
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
        import json
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
        """Convert dimension to dictionary for serialization."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "RefinementDimension":
        """Create RefinementDimension from dictionary."""
        return cls(**data)

# ===============
# Custom Schema Loading
# ===============

def _load_custom_schemas() -> Dict[str, List[RefinementDimension]]:
    """
    Load custom schemas from external YAML file specified by CUSTOM_SCHEMAS_PATH.
    
    The CUSTOM_SCHEMAS_PATH environment variable must point to a YAML file containing
    schema definitions.
    
    Returns:
        Dictionary mapping schema names to lists of RefinementDimension objects
    """
    custom_schemas: Dict[str, List[RefinementDimension]] = {}
    
    # Check if PyYAML is available
    try:
        import yaml
    except ImportError:
        logger.error(
            "PyYAML not installed. Custom schemas require PyYAML. "
            "Install with: pip install pyyaml"
        )
        return custom_schemas
    
    # Get path from environment variable
    env_path = os.getenv("CUSTOM_SCHEMAS_PATH")
    if not env_path:
        logger.error(
            "CUSTOM_SCHEMAS_PATH environment variable not set. "
            "Please set it to the path of your custom schemas YAML file."
        )
        return custom_schemas
    
    schema_path = Path(env_path)
    
    # Check if file exists
    if not schema_path.exists():
        logger.error(f"Custom schemas file not found: {schema_path}")
        return custom_schemas
    
    if not schema_path.is_file():
        logger.error(f"CUSTOM_SCHEMAS_PATH must point to a file, not a directory: {schema_path}")
        return custom_schemas
    
    # Load and parse YAML file
    try:
        logger.info(f"Loading custom schemas from: {schema_path}")
        with open(schema_path, 'r', encoding='utf-8') as f:
            data = yaml.safe_load(f)
        
        if not isinstance(data, dict):
            logger.error(f"Invalid YAML format in {schema_path}: expected dictionary at root level")
            return custom_schemas
        
        # Validate and convert to RefinementDimension objects
        for schema_name, dimensions_data in data.items():
            if not isinstance(dimensions_data, list):
                logger.warning(f"Skipping schema '{schema_name}': expected list of dimensions")
                continue
            
            dimensions = []
            for dim_data in dimensions_data:
                try:
                    dimension = RefinementDimension.from_dict(dim_data)
                    dimensions.append(dimension)
                except (TypeError, ValueError) as e:
                    logger.warning(f"Skipping invalid dimension in schema '{schema_name}': {e}")
                    continue
            
            if dimensions:
                custom_schemas[schema_name] = dimensions
                logger.info(f"Loaded schema '{schema_name}' with {len(dimensions)} dimensions")
        
        if not custom_schemas:
            logger.warning(f"No valid schemas found in {schema_path}")
            
    except yaml.YAMLError as e:
        logger.error(f"Error parsing YAML from {schema_path}: {e}")
    except Exception as e:
        logger.error(f"Error loading custom schemas from {schema_path}: {e}")
    
    return custom_schemas


# ===============
# Schema Registry
# ===============

# Load custom schemas from CUSTOM_SCHEMAS_PATH
SCHEMA_REGISTRY: Dict[str, List[RefinementDimension]] = _load_custom_schemas()

def list_schemas() -> List[str]:
    """
    List all available custom schema names loaded from CUSTOM_SCHEMAS_PATH.

    Returns:
        List of schema names

    Example:
        >>> from query_refinement.schemas import list_schemas
        >>> list_schemas()
        ['my_schema', 'legal_research', 'medical_pico']
    """
    return list(SCHEMA_REGISTRY.keys())

def get_schema(schema_name: str) -> List[RefinementDimension]:
    """
    Retrieve a custom schema by name.

    Args:
        schema_name: Name of the schema as defined in your custom_schemas.yaml file

    Returns:
        List of RefinementDimension objects for the schema

    Raises:
        ValueError: If schema_name is not found in the loaded schemas

    Example:
        >>> from query_refinement.schemas import get_schema
        >>> my_schema = get_schema("my_custom_schema")
        >>> len(my_schema)
        3
    """
    if schema_name not in SCHEMA_REGISTRY:
        available = ", ".join(SCHEMA_REGISTRY.keys()) if SCHEMA_REGISTRY else "none"
        raise ValueError(
            f"Unknown schema '{schema_name}'. Available schemas: {available}. "
            f"Make sure CUSTOM_SCHEMAS_PATH is set and points to a valid YAML file."
        )
    return SCHEMA_REGISTRY[schema_name]

def describe_schema(schema_name: str) -> Dict[str, Any]:
    """
    Get detailed description of a schema including all dimensions.

    Args:
        schema_name: Name of the schema

    Returns:
        Dictionary with schema metadata and dimension details

    Example:
        >>> from query_refinement.schemas import describe_schema
        >>> info = describe_schema("my_custom_schema")
        >>> print(info['framework'])
        'Custom Framework'
        >>> print(len(info['dimensions']))
        3
    """
    schema = get_schema(schema_name)
    
    # Get framework from first dimension's metadata if available
    framework = schema[0].metadata.get("framework", schema_name) if schema else schema_name
    domain = schema[0].metadata.get("domain", "general") if schema else "general"

    return {
        "name": schema_name,
        "framework": framework,
        "domain": domain,
        "num_dimensions": len(schema),
        "dimensions": [
            {
                "id": dim.id,
                "name": dim.name,
                "description": dim.description,
                "priority": dim.metadata.get("priority", "medium"),
                "examples": dim.metadata.get("examples", []),
            }
            for dim in schema
        ],
    }
