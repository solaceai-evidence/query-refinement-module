"""
Jinja2-based prompt builder for query refinement.

This module provides a clean interface for rendering prompts
using Jinja2 templates and Pydantic models.
"""

from typing import List, Dict, Any, Optional
from jinja2 import Environment, BaseLoader, select_autoescape
import logging

from .models import (
    RefinementDimension,
    CompletedDimension,
    ExamplesCollection,
)
from .templates import (
    GLOBAL_SYSTEM_PROMPT,
    SYNTHESIS_TEMPLATE,
    DIMENSION_REFINEMENT_TEMPLATE,
    DIMENSIONS_CLARIFIED_AND_DEPENDENCIES_TEMPLATE,
)


logger = logging.getLogger(__name__)

_previous_prompt_builder = globals().get("PromptBuilder")
_PromptBuilderBase = _previous_prompt_builder if isinstance(_previous_prompt_builder, type) else object

__all__ = [
    "PromptBuilder",
    "render_template",
    "get_prompt_builder",
    "build_refinement_messages",
]


# =============================================================================
# Jinja2 Environment Setup
# =============================================================================

def _create_jinja_env() -> Environment:
    """
    Create a Jinja2 environment with appropriate settings.
    
    CRITICAL: autoescape must be False (not select_autoescape) to prevent
    HTML entity encoding of quotes and other characters in LLM prompts.
    """
    env = Environment(
        loader=BaseLoader(),
        autoescape=False,  # Must be False to prevent HTML entity encoding
        trim_blocks=True,
        lstrip_blocks=True,
        keep_trailing_newline=True,
    )
    return env


_jinja_env = _create_jinja_env()


def render_template(template_string: str, **context) -> str:
    """
    Render a Jinja2 template string with the given context.
    
    Args:
        template_string: The Jinja2 template to render
        **context: Template variables
        
    Returns:
        Rendered template string
    """
    template = _jinja_env.from_string(template_string)
    return template.render(**context)


class PromptBuilder(_PromptBuilderBase):
    """
    Builds prompts for the query refinement system using Jinja2 templates.
    
    Provides methods to generate:
    - System prompts (global + dimension-specific)
    - User context sections
    - Dimension evaluation prompts
    - Synthesis prompts
    - User input prompts (initial and follow-up)
    """
    
    def __init__(self):
        """Initialize the prompt builder with Jinja2 environment."""
        self._env = _jinja_env
        
        # Precompile templates for performance
        self._dimension_template = self._env.from_string(DIMENSION_REFINEMENT_TEMPLATE)
        self._synthesis_template = self._env.from_string(SYNTHESIS_TEMPLATE)
        self._dependencies_template = self._env.from_string(DIMENSIONS_CLARIFIED_AND_DEPENDENCIES_TEMPLATE)

    # =========================================================================
    # Global System Prompt
    # =========================================================================

    def get_global_system_prompt(self) -> str:
        """
        Get the global system prompt.

        Returns:
            The global system directive string
        """
        return GLOBAL_SYSTEM_PROMPT.strip()

    # =========================================================================
    # Completed Dimensions & Dependencies
    # =========================================================================
    
    def render_completed_dimensions(
        self,
        completed_dimensions: List[CompletedDimension],
        dependencies: Optional[List[RefinementDimension]] = None
    ) -> str:
        """
        Render the completed dimensions and dependencies section.
        
        Args:
            completed_dimensions: List of already-completed dimensions
            dependencies: List of dimensions this dimension depends on
            
        Returns:
            Rendered section showing clarified dimensions and dependencies
        """
        # Convert to dicts for template
        completed_dicts = []
        
        for dim in completed_dimensions:
            if hasattr(dim, 'model_dump'):
                dim_dict = dim.model_dump()
            elif hasattr(dim, '__dict__'):
                dim_dict = vars(dim)
            else:
                dim_dict = dict(dim)
            
            completed_dicts.append(dim_dict)
            
        # Preserve dependency list as provided by caller for ✓ marking
        dep_dicts = None
        if dependencies:
            dep_dicts = []
            for dep in dependencies:
                if isinstance(dep, dict):
                    dep_dicts.append({"name": dep.get("name", dep.get("id", "")), "id": dep.get("id", "")})
                else:
                    dep_dicts.append({"name": dep.name, "id": dep.id})
            if not dep_dicts:
                dep_dicts = None
        
        return self._dependencies_template.render(
            completed_dimensions=completed_dicts,
            dependencies=dep_dicts
        )
    
    # =========================================================================
    # Dimension Refinement Prompt
    # =========================================================================
    
    def render_dimension_prompt(
        self,
        dimension: RefinementDimension,
        query: Optional[str] = None,
        include_examples: bool = True
    ) -> str:
        """
        Render the dimension evaluation criteria prompt.
        
        Args:
            dimension: The dimension to render
            include_examples: Whether to include examples section
            
        Returns:
            Rendered dimension evaluation criteria
        """
        # Prepare examples if present and requested
        examples_dict = None
        has_examples = False
        if include_examples and dimension.examples:
            if hasattr(dimension.examples, 'model_dump'):
                examples_dict = dimension.examples.model_dump()
            elif hasattr(dimension.examples, '__dict__'):
                examples_dict = vars(dimension.examples)
            else:
                examples_dict = dict(dimension.examples)
            if examples_dict is not None:
                # Support both historical keys for ambiguous examples.
                ambiguous = list(examples_dict.get('ambiguous') or [])
                vague_ambiguous = list(examples_dict.get('vague_ambiguous') or [])
                if vague_ambiguous:
                    examples_dict['ambiguous'] = ambiguous + vague_ambiguous

                # Support both fields in `other` examples. The Jinja template renders
                # `guidance`, so promote `example_question` when guidance is absent.
                normalized_other = []
                for example in list(examples_dict.get('other') or []):
                    if isinstance(example, dict):
                        normalized = dict(example)
                        if not normalized.get('guidance') and normalized.get('example_question'):
                            normalized['guidance'] = normalized['example_question']
                        normalized_other.append(normalized)
                    else:
                        normalized_other.append(example)
                examples_dict['other'] = normalized_other
            has_examples = dimension.has_examples()
        
        specifications = dimension.specifications
        if query and any(token in specifications for token in ("{query}", "{statement}", "{input}")):
            # Preserve documented YAML placeholder support on the live runtime path.
            specifications = specifications.format(
                query=query,
                statement=query,
                input=query,
            )

        return self._dimension_template.render(
            name=dimension.name,
            description=dimension.description,
            specifications=specifications,
            examples=examples_dict,
            examples_section=has_examples
        )
    
    # =========================================================================
    # Synthesis Prompts
    # =========================================================================
    
    # =========================================================================
    # Combined System Prompt Builder
    # =========================================================================
    
    def build_refinement_system_prompt(
        self,
        dimension: RefinementDimension,
        completed_dimensions: Optional[List[CompletedDimension]] = None,
        dependencies: Optional[List[RefinementDimension]] = None
    ) -> str:
        """
        Build the complete system prompt for dimension refinement.

        Combines:
        1. Global system prompt
        2. Completed dimensions & dependencies
        3. Dimension evaluation criteria

        Args:
            dimension: The dimension being refined
            completed_dimensions: Already completed dimensions
            dependencies: Dimensions this one depends on

        Returns:
            Complete system prompt string
        """
        parts = []

        parts.append(self.get_global_system_prompt())

        if completed_dimensions or dependencies:
            parts.append(self.render_completed_dimensions(
                completed_dimensions or [],
                dependencies
            ))

        parts.append(self.render_dimension_prompt(dimension))

        return "\n\n".join(parts)
    
    def build_refinement_messages(
        self,
        dimension: RefinementDimension,
        query: str,
        conversation_history: List[Dict[str, str]],
        dependency_context: Optional[Dict[str, Dict[str, str]]] = None,
        completed_context: Optional[List[Dict[str, Any]]] = None,
        terminal_reinforcement_threshold: int = 3  # Default kept here as final safety net
    ) -> List[Dict[str, str]]:
        """
        Build messages array for dimension refinement with terminal reinforcement.

        Constructs structured messages with:
        1. System message: Global System Directive [CACHED]
        2. System message: Previously clarified dimensions (dependencies)
        3. System message: Current dimension specification
        4. User message: Original query to analyze
        5. Conversation history: Alternating assistant/user messages
        6. System message: Terminal reinforcement (turns ≥ threshold only)

        Terminal reinforcement repeats cached instructions at conversation end
        to combat recency bias in long conversations.

        Args:
            dimension: The dimension being refined
            query: The original query to analyze
            conversation_history: List of Q&A exchanges for THIS dimension only
            dependency_context: Values from completed dependencies
            terminal_reinforcement_threshold: Add reinforcement after N turns (0=disabled)

        Returns:
            List of message dicts with 'role' and 'content' keys
        """
        messages = []

        # 1. System message: Global System Directive [CACHED]
        messages.append({
            'role': 'system',
            'content': GLOBAL_SYSTEM_PROMPT,
            '_cache': True
        })
        
        # 3. System message: Previously clarified dimensions (all completed) + dependency markers
        completed_dims_for_context: List[CompletedDimension] = []

        if completed_context:
            for entry in completed_context:
                was_skipped = bool(entry.get("was_skipped", False))
                assembled_value = "[SKIPPED]" if was_skipped else str(entry.get("value", "") or "")
                completed_dims_for_context.append(
                    CompletedDimension(
                        id=entry.get("id", ""),
                        name=entry.get("name") or entry.get("id", ""),
                        description=entry.get("description", ""),
                        assembled_value=assembled_value,
                        was_skipped=was_skipped,
                    )
                )
        elif dependency_context and dimension.depends_on:
            for dep_id in dimension.depends_on:
                entry = dependency_context.get(dep_id)
                if entry and entry.get("value"):
                    completed_dims_for_context.append(
                        CompletedDimension(
                            id=dep_id,
                            name=entry.get("name") or dep_id.replace("_", " ").title(),
                            description=entry.get("description", ""),
                            assembled_value=entry["value"],
                            was_skipped=False,
                        )
                    )

        if completed_dims_for_context:
            dependency_defs = [
                {"id": dep_id, "name": dep_id.replace("_", " ").title()}
                for dep_id in (dimension.depends_on or [])
            ]
            messages.append({
                'role': 'system',
                'content': self.render_completed_dimensions(
                    completed_dimensions=completed_dims_for_context,
                    dependencies=dependency_defs,
                )
            })
        
        # 4. System message: Current dimension specification
        messages.append({
            'role': 'system',
            'content': self.render_dimension_prompt(
                dimension=dimension,
                query=query,
                include_examples=True
            )
        })
        
        # 5. User message: Original query
        messages.append({
            'role': 'user',
            'content': query
        })
        
        # 5. Conversation history: Alternating assistant/user messages for THIS dimension
        for qa in conversation_history:
            messages.append({'role': 'assistant', 'content': qa['question']})
            messages.append({'role': 'user', 'content': qa['response']})

        # 5c. Completed-context reminder: re-append after conversation history so the model
        # reads it in the most recent position. This combats recency bias in open-weight
        # models that deprioritise early system messages when a user message dominates.
        # Safe for all models — Claude ignores the redundancy; Qwen benefits from recency.
        if completed_dims_for_context:
            dependency_defs_reminder = [
                {"id": dep_id, "name": dep_id.replace("_", " ").title()}
                for dep_id in (dimension.depends_on or [])
            ]
            reminder_content = self.render_completed_dimensions(
                completed_dimensions=completed_dims_for_context,
                dependencies=dependency_defs_reminder,
            )
            messages.append({
                'role': 'system',
                'content': reminder_content + (
                    "\n\n**Reminder:** Extract from the completed dimensions above "
                    "before generating any question. If the value for the current "
                    "dimension is present, set complete=true and question=\"\". "
                    "If the dimension specification says an absent detail should be "
                    "omitted silently unless a trigger is met, do not ask unless that "
                    "trigger is explicit in the available context. Extract only the "
                    "fragment relevant to the current dimension; do not copy an entire "
                    "prior dimension value when only part of it applies."
                )
            })
        
        # 6. Terminal reinforcement: Repeat cached instructions at end for long conversations
        # Combats recency bias when conversation history dominates the context window.
        if terminal_reinforcement_threshold > 0 and len(conversation_history) >= terminal_reinforcement_threshold:
            reinforcement_parts = [GLOBAL_SYSTEM_PROMPT]
            reinforcement_parts.append(
                self.render_dimension_prompt(
                    dimension=dimension,
                    query=query,
                    include_examples=True,
                )
            )

            messages.append({
                'role': 'system',
                'content': '\n\n'.join(reinforcement_parts)
            })
            
            logger.info(
                f"Terminal reinforcement added for {dimension.name} (turn {len(conversation_history)})",
                extra={
                    "dimension": dimension.name,
                    "turn_count": len(conversation_history),
                    "threshold": terminal_reinforcement_threshold
                }
            )
        
        return messages
    
# =============================================================================
# Default Instance & Convenience Functions
# =============================================================================

# Create a default instance for convenience
_default_builder = PromptBuilder()


def get_prompt_builder() -> PromptBuilder:
    """Get the default prompt builder instance."""
    return _default_builder


def build_refinement_messages(
    dimension: RefinementDimension,
    query: str,
    conversation_history: List[Dict[str, str]],
    dependency_context: Optional[Dict[str, Dict[str, str]]] = None,
    completed_context: Optional[List[Dict[str, Any]]] = None,
    terminal_reinforcement_threshold: int = 3  # Delegates to method, inherits same default
) -> List[Dict[str, str]]:
    """
    Convenience function to build refinement messages.
    
    Args:
        dimension: The dimension being refined
        query: The original query
        conversation_history: Q&A history for THIS dimension
        dependency_context: Completed dependency values
        completed_context: All completed prior dimensions with values/skip status
        terminal_reinforcement_threshold: Add reinforcement after N turns (default: 3 from LLMSettings)
        
    Returns:
        List of messages for LLM API
    """
    return _default_builder.build_refinement_messages(
        dimension=dimension,
        query=query,
        conversation_history=conversation_history,
        dependency_context=dependency_context,
        completed_context=completed_context,
        terminal_reinforcement_threshold=terminal_reinforcement_threshold
    )



