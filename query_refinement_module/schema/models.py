"""
Pydantic models for query refinement framework.

This module defines type-safe models for:
- UserContext: User adaptation profile from framework
- RefinementDimension: A dimension/aspect that can be refined
- CompletedDimension: A dimension that has been refined
- ExamplesCollection: Few-shot examples for LLM guidance
"""

from typing import List, Optional, Dict, Any, ClassVar, Literal
import json
import logging
from pydantic import BaseModel, Field, ConfigDict, field_validator

from .templates.global_system import GLOBAL_SYSTEM_PROMPT

logger = logging.getLogger(__name__)


__all__ = [
    "UserContext",
    "RefinementDimension",
    "CompletedDimension",
    "ExamplesCollection",
    "ClearExample",
    "NeedsRefinementExample",
    "PartialExample",
    "AmbiguousExample",
    "OtherExample",
]


# =============================================================================
# Example Models
# =============================================================================

class ClearExample(BaseModel):
    """Example demonstrating clear, complete specification."""
    model_config = ConfigDict(extra="allow")
    
    statement: Optional[str] = Field(default=None, description="The example statement")
    query: Optional[str] = Field(default=None, description="Legacy field for statement")
    rationale: Optional[str] = Field(default=None, description="Why this is clear")
    
    @field_validator('statement', 'query', mode='before')
    @classmethod
    def ensure_has_content(cls, v, info):
        return v
    
    def get_text(self) -> str:
        """Get the example text (statement or query)."""
        return self.statement or self.query or ""


class NeedsRefinementExample(BaseModel):
    """Example demonstrating statements that need clarification."""
    model_config = ConfigDict(extra="allow")
    
    statement: Optional[str] = None
    query: Optional[str] = None
    issue: Optional[str] = Field(default=None, description="What makes this unclear")
    missing: Optional[str] = Field(default=None, description="What details are absent")
    example_question: Optional[str] = Field(default=None, description="Question to clarify")
    
    def get_text(self) -> str:
        return self.statement or self.query or ""


class PartialExample(BaseModel):
    """Example demonstrating partially specified information."""
    model_config = ConfigDict(extra="allow")
    
    statement: Optional[str] = None
    query: Optional[str] = None
    has: Optional[str] = Field(default=None, description="What information is present")
    missing: Optional[str] = Field(default=None, description="What is still needed")
    example_question: Optional[str] = None
    
    def get_text(self) -> str:
        return self.statement or self.query or ""


class AmbiguousExample(BaseModel):
    """Example demonstrating vague or unclear specification."""
    model_config = ConfigDict(extra="allow")
    
    statement: Optional[str] = None
    query: Optional[str] = None
    issue: Optional[str] = None
    example_question: Optional[str] = None
    guidance: Optional[str] = Field(default=None, description="How to handle similar cases")
    
    def get_text(self) -> str:
        return self.statement or self.query or ""


class OtherExample(BaseModel):
    """Example capturing edge cases."""
    model_config = ConfigDict(extra="allow")
    
    statement: Optional[str] = None
    query: Optional[str] = None
    issue: Optional[str] = None
    note: Optional[str] = None
    guidance: Optional[str] = None
    example_question: Optional[str] = None
    
    def get_text(self) -> str:
        return self.statement or self.query or ""


class ExamplesCollection(BaseModel):
    """Collection of examples for few-shot learning."""
    model_config = ConfigDict(extra="allow")
    
    clear: List[ClearExample] = Field(default_factory=list)
    needs_refinement: List[NeedsRefinementExample] = Field(default_factory=list)
    partial: List[PartialExample] = Field(default_factory=list)
    ambiguous: List[AmbiguousExample] = Field(default_factory=list)
    vague_ambiguous: List[AmbiguousExample] = Field(default_factory=list)  # Alias
    other: List[OtherExample] = Field(default_factory=list)
    
    def has_examples(self) -> bool:
        """Check if any examples exist."""
        return bool(
            self.clear or self.needs_refinement or self.partial or 
            self.ambiguous or self.vague_ambiguous or self.other
        )


# =============================================================================
# User Context Model
# =============================================================================

class UserContext(BaseModel):
    """
    User adaptation profile from framework.
    
    Controls how the LLM adapts its responses based on user type,
    expertise level, domain, and constraints.
    """
    model_config = ConfigDict(extra="allow")
    
    user_type: str = Field(description="Type of user (e.g., 'MPH student', 'researcher')")
    context: str = Field(description="Description of user's situation/needs")
    tone: str = Field(default="professional", description="Response tone: educational, professional, pragmatic")
    complexity: str = Field(default="intermediate", description="Complexity level: intermediate, advanced, expert")
    examples_from: str = Field(default="general", description="Domain for examples")
    constraints: List[str] = Field(default_factory=list, description="User constraints (timeline, resources, etc.)")
    pitfalls: List[str] = Field(default_factory=list, description="Common pitfalls to watch for")


# =============================================================================
# Dimension Models
# =============================================================================

class CompletedDimension(BaseModel):
    """A dimension that has been refined/completed."""
    model_config = ConfigDict(extra="allow")
    
    id: str = Field(description="Dimension identifier")
    name: str = Field(description="Human-readable name")
    description: str = Field(description="What this dimension represents")
    assembled_value: str = Field(description="The refined value using user's words")
    was_skipped: bool = Field(default=False, description="Whether this dimension was skipped")
    
    @classmethod
    def from_dimension(
        cls, 
        dimension: "RefinementDimension", 
        value: str,
        was_skipped: bool = False
    ) -> "CompletedDimension":
        """Create from a RefinementDimension with its assembled value."""
        return cls(
            id=dimension.id,
            name=dimension.name,
            description=dimension.description,
            assembled_value=value,
            was_skipped=was_skipped
        )


class RefinementDimension(BaseModel):
    """
    A dimension/aspect along which a query can be refined.
    
    Replaces the dataclass-based RefinementAspect with a Pydantic model
    for better validation, serialization, and type safety.
    
    This model directly matches the YAML structure where dimensions use:
    - 'name': dimension name
    - 'description': dimension description  
    - 'specifications': evaluation instructions
    """
    model_config = ConfigDict(
        extra="allow",
        validate_assignment=True,
        populate_by_name=True,
    )
    
    # Required fields (match YAML structure)
    id: str = Field(description="Unique identifier for this dimension")
    name: str = Field(description="Human-readable dimension name")
    description: str = Field(description="Brief description of what this dimension refines")
    
    # Evaluation content
    specifications: str = Field(
        default="", 
        description="Instructions for evaluating this dimension"
    )
    
    # Examples for few-shot learning
    examples: Optional[ExamplesCollection] = Field(default=None, description="Few-shot examples")
    
    # Dependencies
    depends_on: List[str] = Field(default_factory=list, description="IDs of dimensions this depends on")
    
    # User context (attached by registry loader)
    user_context: Optional[UserContext] = Field(default=None, description="User adaptation profile")
    
    # Optional fields
    response_format: Optional[Dict[str, Any]] = Field(default=None, description="Response format config")
    allow_follow_up: bool = Field(default=True, description="Whether follow-ups are allowed")
    max_follow_ups: int = Field(default=50, description="Max follow-up limit")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Additional metadata")
    
    @field_validator('examples', mode='before')
    @classmethod
    def parse_examples(cls, v):
        """Parse examples dict into ExamplesCollection."""
        if v is None:
            return None
        if isinstance(v, ExamplesCollection):
            return v
        if isinstance(v, dict):
            return ExamplesCollection(**v)
        # Handle empty list (backward compatibility)
        if isinstance(v, list) and len(v) == 0:
            return None
        return v
    
    @field_validator('user_context', mode='before')
    @classmethod
    def parse_user_context(cls, v):
        """Parse user_context dict into UserContext model."""
        if v is None:
            return None
        if isinstance(v, UserContext):
            return v
        if isinstance(v, dict):
            return UserContext(**v)
        return v
    
    def has_examples(self) -> bool:
        """Check if this dimension has any examples."""
        return self.examples is not None and self.examples.has_examples()

    # =========================================================================
    # Schema fields for response validation (matches DimensionEvaluationResponse)
    # =========================================================================
    
    BASE_SCHEMA_FIELDS: ClassVar[Dict[str, str]] = {
        "complete": "boolean",
        "current": "string",
        "question": "string",
        "examples": "array",
    }

    BASE_FIELD_DESCRIPTIONS: ClassVar[Dict[str, str]] = {
        "complete": "Whether the dimension has been sufficiently clarified",
        "current": "The accumulated value of this dimension assembled from all sources (original query, completed dimensions, conversation history) using the user's exact words. Non-empty whenever any value has been extracted, regardless of whether the dimension is complete. Empty string only when no information for this dimension exists across all sources.",
        "question": "Follow-up question when incomplete, empty string otherwise",
        "examples": "Array of 2–4 short standalone quick-reply options when complete=false; empty array when complete=true. Do NOT embed these in the question field.",
    }
    
    # =========================================================================
    # Response validation methods
    # =========================================================================
    
    def validate_response(self, response: Dict[str, Any]) -> tuple:
        """
        Validate an LLM response against schema requirements.
        
        Args:
            response: The response dictionary to validate
            
        Returns:
            Tuple of (is_valid, error_message)
        """
        if not isinstance(response, dict):
            return False, "Response must be a dictionary"
        
        validation_errors = []
        
        # Check required fields
        for field_name, field_type in self.BASE_SCHEMA_FIELDS.items():
            if field_name not in response:
                # Some fields are conditionally required or optional
                if field_name in ("current", "question", "examples"):
                    continue
                validation_errors.append(f"Missing required field: {field_name}")
                continue

            value = response[field_name]

            # Type validation
            if field_type == "boolean" and not isinstance(value, bool):
                validation_errors.append(f"Field '{field_name}' must be boolean")
            elif field_type == "float" and not isinstance(value, (int, float)):
                validation_errors.append(f"Field '{field_name}' must be float")
            elif field_type == "string" and not isinstance(value, str):
                validation_errors.append(f"Field '{field_name}' must be string")
            elif field_type == "array" and not isinstance(value, list):
                validation_errors.append(f"Field '{field_name}' must be array")
        
        # Validate conditional fields based on complete
        complete = response.get("complete", False)
        if complete:
            current = response.get("current", "")
            if not current or not isinstance(current, str):
                validation_errors.append("'current' required as non-empty string when complete=true")
        else:
            question = response.get("question", "")
            if not question or not isinstance(question, str):
                validation_errors.append("'question' required as non-empty string when complete=false")
            examples = response.get("examples")
            if examples is None:
                validation_errors.append("'examples' required as array when complete=false")
            elif not isinstance(examples, list):
                validation_errors.append("'examples' must be array when complete=false")
        
        if validation_errors:
            return False, "; ".join(validation_errors)
        
        return True, None

    def validate_response_strict(self, response: Dict[str, Any]) -> tuple:
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


# Backward compatibility alias
RefinementAspect = RefinementDimension
