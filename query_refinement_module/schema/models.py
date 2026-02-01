"""
Pydantic models for query refinement framework.

This module defines type-safe models for:
- UserContext: User adaptation profile from framework
- RefinementDimension: A dimension/aspect that can be refined
- CompletedDimension: A dimension that has been refined
- ExamplesCollection: Few-shot examples for LLM guidance
"""

from typing import List, Optional, Dict, Any, ClassVar
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
    complexity: str = Field(default="intermediate", description="Complexity level: novice, intermediate, advanced, expert")
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
    
    @classmethod
    def from_dimension(cls, dimension: "RefinementDimension", value: str) -> "CompletedDimension":
        """Create from a RefinementDimension with its assembled value."""
        return cls(
            id=dimension.id,
            name=dimension.aspect_name,
            description=dimension.aspect_description,
            assembled_value=value
        )


class RefinementDimension(BaseModel):
    """
    A dimension/aspect along which a query can be refined.
    
    Replaces the dataclass-based RefinementAspect with a Pydantic model
    for better validation, serialization, and type safety.
    
    Field aliases:
        - name → aspect_name (YAML uses 'name')
        - description → aspect_description (YAML uses 'description')
        - evaluator → evaluation_instructions (YAML uses 'evaluator')
        - criteria → evaluation_criteria (YAML uses 'criteria')
        - response_strategy → response_strategies (YAML uses singular)
    """
    model_config = ConfigDict(
        extra="allow",
        validate_assignment=True,
        populate_by_name=True,  # Allow both alias and field name
    )
    
    # Required fields
    id: str = Field(description="Unique identifier for this dimension")
    aspect_name: str = Field(
        description="Human-readable dimension name",
        validation_alias="name"
    )
    aspect_description: str = Field(
        description="Brief description of what this dimension refines",
        validation_alias="description"
    )
    
    # Evaluation content (accepts YAML field names as aliases)
    evaluation_instructions: str = Field(
        default="", 
        description="Instructions for evaluating this dimension",
        validation_alias="evaluator"
    )
    evaluation_criteria: str = Field(
        default="", 
        description="Criteria for evaluating this dimension",
        validation_alias="criteria"
    )
    response_strategies: Optional[str] = Field(
        default=None, 
        description="Strategies for responding",
        validation_alias="response_strategy"
    )
    
    # Examples for few-shot learning
    examples: Optional[ExamplesCollection] = Field(default=None, description="Few-shot examples")
    
    # Dependencies
    depends_on: List[str] = Field(default_factory=list, description="IDs of dimensions this depends on")
    
    # User context (attached by registry loader)
    user_context: Optional[UserContext] = Field(default=None, description="User adaptation profile")
    
    # Legacy/optional fields
    system_prompt: Optional[str] = Field(default=None, description="DEPRECATED: Use global system prompt")
    response_format: Optional[Dict[str, Any]] = Field(default=None, description="Response format config")
    allow_follow_up: bool = Field(default=True, description="Whether follow-ups are allowed")
    max_follow_ups: int = Field(default=50, description="Max follow-up limit")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Additional metadata")
    
    @field_validator('response_strategies', mode='before')
    @classmethod
    def parse_response_strategies(cls, v):
        """Convert list of dicts to formatted string, or pass through string."""
        if v is None:
            return None
        if isinstance(v, str):
            return v
        if isinstance(v, list):
            # Convert list of dicts like [{"If too broad": "guidance..."}] to string
            lines = []
            for item in v:
                if isinstance(item, dict):
                    for condition, guidance in item.items():
                        lines.append(f"- **{condition}:** {guidance}")
                elif isinstance(item, str):
                    lines.append(f"- {item}")
            return "\n".join(lines) if lines else None
        return str(v)
    
    def model_post_init(self, __context: Any) -> None:
        """Merge evaluation_criteria into evaluation_instructions after init."""
        # Merge evaluation_criteria into evaluation_instructions
        if self.evaluation_criteria and not self.evaluation_instructions:
            object.__setattr__(self, 'evaluation_instructions', self.evaluation_criteria)
        elif self.evaluation_criteria and self.evaluation_instructions:
            combined = f"{self.evaluation_instructions}\n\n{self.evaluation_criteria}"
            object.__setattr__(self, 'evaluation_instructions', combined)
        
        # Append response_strategies if present
        if self.response_strategies and self.evaluation_instructions:
            combined = f"{self.evaluation_instructions}\n\n## Response Strategies\n\n{self.response_strategies}"
            object.__setattr__(self, 'evaluation_instructions', combined)
    
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
    
    def get_evaluation_content(self) -> str:
        """Get the full evaluation content (criteria + strategies)."""
        return self.evaluation_instructions
    
    def has_examples(self) -> bool:
        """Check if this dimension has any examples."""
        return self.examples is not None and self.examples.has_examples()
    
    def get_dependencies(self) -> List[str]:
        """Get list of dependency IDs."""
        return self.depends_on

    # =========================================================================
    # Schema fields for response validation (matches DimensionEvaluationResponse)
    # =========================================================================
    
    BASE_SCHEMA_FIELDS: ClassVar[Dict[str, str]] = {
        "is_complete": "boolean",
        "reasoning": "string",
        "refinement_aspect_value": "string",
        "next_question": "string"
    }
    
    BASE_FIELD_DESCRIPTIONS: ClassVar[Dict[str, str]] = {
        "is_complete": "Whether the dimension has been sufficiently clarified",
        "reasoning": "Brief explanation of the assessment",
        "refinement_aspect_value": "The extracted/refined value when complete, null otherwise",
        "next_question": "Follow-up question when incomplete, null otherwise"
    }
    
    # =========================================================================
    # Prompt generation methods (backward compatible with old dataclass)
    # =========================================================================
    
    def get_system_role(self) -> str:
        """
        Get the system role prompt for this refinement aspect.
        
        DEPRECATED: Custom system prompts are no longer supported to enable LLM prompt caching.
        Always returns GLOBAL_SYSTEM_PROMPT regardless of aspect.system_prompt value.
        
        Returns:
            GLOBAL_SYSTEM_PROMPT (static across all dimensions for caching)
        """
        if self.system_prompt and self.system_prompt.strip():
            import warnings
            warnings.warn(
                f"system_prompt for aspect '{self.aspect_name}' is deprecated and ignored. "
                "Move dimension-specific content to evaluation_instructions and examples. "
                "System prompts must be static for LLM caching to work.",
                DeprecationWarning,
                stacklevel=2
            )
        return GLOBAL_SYSTEM_PROMPT
    
    def get_evaluation_instructions_prompt(self, statement: str) -> str:
        """
        Generate the developer prompt including examples and response format instructions.
        
        Args:
            statement: The user's statement to be analyzed and refined
        Returns:
            Complete developer prompt with statement inserted and response format appended
        """
        prompt_parts = []
        
        # Check if evaluation_instructions contains placeholders
        if "{input}" in self.evaluation_instructions or "{statement}" in self.evaluation_instructions or "{query}" in self.evaluation_instructions:
            prompt_parts.append(
                self.evaluation_instructions.format(query=statement, statement=statement, input=statement)
            )
        else:
            prompt_parts.append(f"** Research input:** {statement}.\n")
            prompt_parts.append(self.evaluation_instructions)
        
        # Inject examples if available
        if self.examples:
            examples_section = self._format_examples()
            if examples_section:
                prompt_parts.append(examples_section)
        
        # Always append response format
        prompt_parts.append(self._format_response_instructions())
        
        return "\n\n".join(prompt_parts)
    
    def get_prompts(self, query: str) -> tuple:
        """
        Get both system and developer prompts for this refinement aspect.
        
        Args:
            query: The user's query to analyze
            
        Returns:
            Tuple of (system_prompt, developer_prompt)
        """
        return self.get_system_role(), self.get_evaluation_instructions_prompt(query)
    
    def _format_examples(self) -> str:
        """
        Format examples into a readable section for prompt inclusion.
        
        Returns:
            Formatted examples section, or empty string if no examples
        """
        if not self.examples or not self.examples.has_examples():
            return ""
        
        sections = []
        
        category_config = [
            ("clear", "CLEAR SPECIFICATIONS:"),
            ("needs_refinement", "NEEDS CLARIFICATION:"),
            ("partial", "PARTIAL INFORMATION:"),
            ("vague_ambiguous", "VAGUE OR AMBIGUOUS:"),
            ("other", "ADDITIONAL GUIDANCE:"),
        ]
        
        def ensure_period(text: str) -> str:
            return text if text.rstrip().endswith(('.', '!', '?')) else text.rstrip() + '.'
        
        for category_key, header in category_config:
            examples_list = getattr(self.examples, category_key, [])
            if not examples_list:
                continue
                
            sections.append(header)
            
            for example in examples_list:
                # Support both statement and query
                statement = example.get_text()
                if not statement:
                    continue
                statement = ensure_period(statement)
                
                line_parts = [f'statement: "{statement}"']
                
                # Add explanatory fields
                if hasattr(example, 'rationale') and example.rationale:
                    line_parts.append(f"rationale: {ensure_period(example.rationale)}")
                elif hasattr(example, 'issue') and example.issue:
                    line_parts.append(f"Issue: {ensure_period(example.issue)}")
                elif hasattr(example, 'missing') and example.missing:
                    line_parts.append(f"Missing: {ensure_period(example.missing)}")
                
                if hasattr(example, 'has') and example.has:
                    line_parts.append(f"Has: {ensure_period(example.has)}")
                
                if hasattr(example, 'example_question') and example.example_question:
                    line_parts.append(f'Example Q: "{ensure_period(example.example_question)}"')
                
                if hasattr(example, 'note') and example.note:
                    line_parts.append(f"Note: {ensure_period(example.note)}")
                
                if hasattr(example, 'guidance') and example.guidance:
                    line_parts.append(f"Guidance: {ensure_period(example.guidance)}")
                
                sections.append("  - " + " ".join(line_parts))
            
            sections.append("")  # Blank line after category
        
        if not sections:
            return ""
        
        return "--- GUIDANCE EXAMPLES ---\n" + "\n".join(sections)
    
    def _format_response_instructions(self) -> str:
        """Format response_format into clear instructions."""
        instructions = ["Respond in the following JSON format:"]
        
        schema_example = {key: f"<{ftype}>" for key, ftype in self.BASE_SCHEMA_FIELDS.items()}
        instructions.append(f"\n```json\n{json.dumps(schema_example, indent=2)}\n```")
        
        instructions.append("\nField descriptions:")
        for field_name, ftype in self.BASE_SCHEMA_FIELDS.items():
            desc = self.BASE_FIELD_DESCRIPTIONS.get(field_name, f"Value of type {ftype}")
            instructions.append(f"- **{field_name}** ({ftype}): {desc}")
        
        instructions.append("\n**Rules:**")
        instructions.append("- `is_complete=true` → `refinement_aspect_value` must be non-null, `next_question` must be null")
        instructions.append("- `is_complete=false` → `next_question` must be non-null, `refinement_aspect_value` must be null")
        
        return "\n".join(instructions)
    
    # =========================================================================
    # Unified prompt building methods (backward compatible)
    # =========================================================================
    
    UNIFIED_ANALYSIS_PROMPT: ClassVar[str] = """You are analyzing the '{aspect_name}' dimension.

**Aspect Description:** {aspect_description}

**Original Research Input:** {original_input}

{conversation_section}
{dependency_section}
{evaluation_instructions}
{examples_section}
{output_format_section}"""
    
    def build_unified_prompt(
        self,
        original_input: str,
        follow_up_history: List[Dict[str, str]],
        dependency_context: Dict[str, Dict[str, Any]],
        mode: str = 'initial'
    ) -> str:
        """
        Build complete unified prompt for dimension evaluation.
        
        Args:
            original_input: The original user input
            follow_up_history: List of Q&A exchanges for this aspect
            dependency_context: Dict mapping aspect IDs to their completed values
            mode: 'initial' or 'followup'
        
        Returns:
            Complete formatted prompt ready for LLM
        """
        conversation_section = self._build_conversation_section(follow_up_history, mode)
        dependency_section = self._build_dependency_section(dependency_context)
        evaluation_instructions = self._build_evaluation_instructions_section(original_input)
        examples_section = self._build_examples_section_for_prompt()
        output_format_section = self._build_output_format_section()
        
        return self.UNIFIED_ANALYSIS_PROMPT.format(
            aspect_name=self.aspect_name,
            aspect_description=self.aspect_description,
            original_input=original_input,
            conversation_section=conversation_section,
            dependency_section=dependency_section,
            evaluation_instructions=evaluation_instructions,
            examples_section=examples_section,
            output_format_section=output_format_section
        )
    
    def _build_conversation_section(
        self,
        follow_up_history: List[Dict[str, str]],
        mode: str
    ) -> str:
        """Build conversation history section."""
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
        """Build dependency context showing completed/clarified dimensions."""
        if not dependency_context:
            return ""
        
        lines = ["**Completed Dimensions (for context):**\n"]
        has_dependencies = bool(self.depends_on)
        
        for dep_id, context in dependency_context.items():
            aspect_name = context.get('name', dep_id)
            aspect_desc = context.get('description', '')
            refined_value = context.get('value', '')
            
            dependency_marker = ""
            if has_dependencies and dep_id in self.depends_on:
                dependency_marker = " ⚠️ (the current dimension depends on this)"
            
            lines.append(f"**{aspect_name}**{dependency_marker}")
            if aspect_desc:
                lines.append(f"  Description: {aspect_desc}")
            lines.append(f"  Value: {refined_value}\n")
        
        if has_dependencies:
            lines.append("\n⚠️ = Consider these values when analyzing the current aspect\n")
        
        return "\n".join(lines)
    
    def _build_evaluation_instructions_section(self, original_input: str) -> str:
        """Build evaluation instructions section."""
        instructions = self.get_evaluation_instructions_prompt(statement=original_input)
        return f"# Evaluation Strategy:\n\n{instructions}\n"
    
    def _build_examples_section_for_prompt(self) -> str:
        """Build examples section from aspect schema for unified prompt."""
        if not self.examples or not self.examples.has_examples():
            return ""
        
        lines = ["**Examples:**\n"]
        
        category_map = {
            'clear': 'Clear Examples',
            'needs_refinement': 'Needs Refinement',
            'partial': 'Partial Examples',
            'vague_ambiguous': 'Vague/Ambiguous Examples',
            'other': 'Other Cases'
        }
        
        for category in ['clear', 'needs_refinement', 'partial', 'vague_ambiguous', 'other']:
            examples_list = getattr(self.examples, category, [])
            if not examples_list:
                continue
            
            category_title = category_map.get(category, category.replace('_', ' ').title())
            lines.append(f"\n{category_title}:")
            
            for ex in examples_list:
                statement = ex.get_text()
                if statement:
                    lines.append(f"- Example: {statement}.")
                
                for key in ['rationale', 'issue', 'missing', 'has', 'example_question', 'note', 'guidance']:
                    value = getattr(ex, key, None)
                    if value:
                        key_title = key.replace('_', ' ').title()
                        lines.append(f"  {key_title}: {value}")
        
        return "\n".join(lines)
    
    def _build_output_format_section(self) -> str:
        """Build the output format section."""
        lines = ["**OUTPUT (JSON):**", ""]
        
        for field_name, field_type in self.BASE_SCHEMA_FIELDS.items():
            if field_type == "boolean":
                example_value = "true/false"
            elif field_type == "float":
                example_value = "0.0-1.0"
            elif field_name == "reasoning":
                example_value = '"why complete/incomplete (1-2 sentences)"'
            elif field_name == "refinement_aspect_value":
                example_value = '"clear, specific value (if complete) OR null"'
            elif field_name == "next_question":
                example_value = '"focused question with inline examples (if incomplete) OR null"'
            else:
                example_value = f'"<{field_type}>"'
            
            lines.append(f'  "{field_name}": {example_value},')
        
        if lines[-1].endswith(','):
            lines[-1] = lines[-1][:-1]
        
        lines.append("}")
        lines.append("")
        lines.append("**Rules:**")
        lines.append("- `is_complete=true` → `refinement_aspect_value` must be non-null, `next_question` must be null")
        lines.append("- `is_complete=false` → `next_question` must be non-null, `refinement_aspect_value` must be null")
        
        return "\n".join(lines)
    
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
                # Some fields are conditionally required
                if field_name in ("refinement_aspect_value", "next_question"):
                    continue
                validation_errors.append(f"Missing required field: {field_name}")
                continue
            
            value = response[field_name]
            
            # Type validation
            if field_type == "boolean" and not isinstance(value, bool):
                validation_errors.append(f"Field '{field_name}' must be boolean")
            elif field_type == "float" and not isinstance(value, (int, float)):
                validation_errors.append(f"Field '{field_name}' must be float")
            elif field_type == "string" and value is not None and not isinstance(value, str):
                validation_errors.append(f"Field '{field_name}' must be string or null")
        
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
