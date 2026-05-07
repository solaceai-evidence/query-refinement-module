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
    UserContext,
    ExamplesCollection,
)
from .templates import (
    GLOBAL_SYSTEM_PROMPT,
    SYNTHESIS_TEMPLATE,
    DIMENSION_REFINEMENT_TEMPLATE,
    USER_CONTEXT_PROFILE_TEMPLATE,
    DIMENSIONS_CLARIFIED_AND_DEPENDENCIES_TEMPLATE,
)


logger = logging.getLogger(__name__)

__all__ = [
    "PromptBuilder",
    "render_template",
    "create_dimension_prompt",
    "create_synthesis_prompt",
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


class PromptBuilder:
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
        self._user_context_template = self._env.from_string(USER_CONTEXT_PROFILE_TEMPLATE)
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
    # User Context Section
    # =========================================================================
    
    def render_user_context(self, user_context: UserContext) -> str:
        """
        Render the user context adaptation profile.
        
        Args:
            user_context: The user context to render
            
        Returns:
            Rendered user context section
        """
        # Convert Pydantic model to dict for template
        if hasattr(user_context, 'model_dump'):
            ctx_dict = user_context.model_dump()
        elif hasattr(user_context, '__dict__'):
            ctx_dict = vars(user_context)
        else:
            ctx_dict = dict(user_context)
        return self._user_context_template.render(user_context=ctx_dict)
    
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
            has_examples = dimension.has_examples()
        
        return self._dimension_template.render(
            name=dimension.name,
            description=dimension.description,
            strictness=getattr(dimension, "strictness", None),
            specifications=dimension.specifications,
            examples=examples_dict,
            examples_section=has_examples
        )
    
    # =========================================================================
    # Synthesis Prompts
    # =========================================================================
    
    def get_synthesis_system_prompt(self) -> str:
        """
        Get the synthesis system prompt.
        
        Returns:
            The synthesis template string
        """
        return SYNTHESIS_TEMPLATE.strip()
    
    def render_synthesis_original_input(self, original_input: str) -> str:
        """
        Render the original input message for synthesis.
        
        Args:
            original_input: The user's original research query
            
        Returns:
            Just the original input text (template handles formatting)
        """
        return original_input
    
    def render_synthesis_dimensions(
        self,
        dimensions: Dict[str, str],
        dimension_list: List[RefinementDimension]
    ) -> str:
        """
        Render the clarified dimensions for synthesis.
        
        Args:
            dimensions: Dict mapping dimension ID to assembled value
            dimension_list: List of dimension definitions
            
        Returns:
            Formatted dimensions for synthesis
        """
        # Build ID -> dimension mapping
        dim_map = {d.id: d for d in dimension_list}
        
        lines = ["## Clarified Dimensions\n"]
        for dim_id, value in dimensions.items():
            dim = dim_map.get(dim_id)
            if dim:
                # [SKIPPED] if None or empty
                display_value = value if value else "[SKIPPED]"
                lines.append(f"**{dim.name}** ({dim.description}): {display_value}")
            else:
                display_value = value if value else "[SKIPPED]"
                lines.append(f"**{dim_id}**: {display_value}")
        
        return "\n".join(lines)
    
    # =========================================================================
    # Combined System Prompt Builder
    # =========================================================================
    
    def build_refinement_system_prompt(
        self,
        dimension: RefinementDimension,
        user_context: Optional[UserContext] = None,
        completed_dimensions: Optional[List[CompletedDimension]] = None,
        dependencies: Optional[List[RefinementDimension]] = None
    ) -> str:
        """
        Build the complete system prompt for dimension refinement.
        
        Combines:
        1. Global system prompt
        2. User context adaptation
        3. Completed dimensions & dependencies
        4. Dimension evaluation criteria
        
        Args:
            dimension: The dimension being refined
            user_context: User adaptation profile (uses dimension's if not provided)
            completed_dimensions: Already completed dimensions
            dependencies: Dimensions this one depends on
            
        Returns:
            Complete system prompt string
        """
        parts = []
        
        # 1. Global system prompt
        parts.append(self.get_global_system_prompt())
        
        # 2. User context (from dimension or provided)
        ctx = user_context or dimension.user_context
        if ctx:
            parts.append(self.render_user_context(ctx))
        
        # 3. Completed dimensions & dependencies
        if completed_dimensions or dependencies:
            parts.append(self.render_completed_dimensions(
                completed_dimensions or [],
                dependencies
            ))
        
        # 4. Dimension evaluation criteria
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
        2. System message: User context adaptation profile [CACHED]
        3. System message: Previously clarified dimensions (dependencies)
        4. System message: Current dimension specification
        5. User message: Original query to analyze
        6. Conversation history: Alternating assistant/user messages
        7. System message: Terminal reinforcement (turns ≥ threshold only)
        
        Terminal reinforcement repeats cached instructions at conversation end
        to combat recency bias in long conversations (research-backed approach).
        
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
        # Uses GLOBAL_SYSTEM_PROMPT from module-level imports (from .templates)
        messages.append({
            'role': 'system',
            'content': GLOBAL_SYSTEM_PROMPT,
            '_cache': True
        })
        
        # 2. System message: User context adaptation profile [CACHED]
        if dimension.user_context:
            messages.append({
                'role': 'system',
                'content': self.render_user_context(dimension.user_context),
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
                include_examples=True
            )
        })
        
        # 5. User message: Original query
        messages.append({
            'role': 'user',
            'content': query
        })
        
        # 6. Conversation history: Alternating assistant/user messages for THIS dimension
        for qa in conversation_history:
            messages.append({'role': 'assistant', 'content': qa['question']})
            messages.append({'role': 'user', 'content': qa['response']})

        # 6b. Style cue: re-append compact tone/complexity hint after conversation history
        # to counter recency bias at ALL turn counts (incl. turn 0 where terminal
        # reinforcement has not fired). The full user_context profile is cached early
        # in the message list but is dominated by the dimension spec + user query when
        # the model generates its response. This compact cue restores it at recency.
        if dimension.user_context:
            _ctx = dimension.user_context
            _tone_hints = {
                "educational": "warm, encouraging register — explain why each question matters",
                "professional": "direct, formal register — no small talk or warmth phrases",
                "pragmatic": "lead with the consequence of not knowing — brief and action-oriented",
            }
            _complexity_hints = {
                "intermediate": "standard clinical/domain terminology, no need to define basics",
                "advanced": "precise technical vocabulary, push back on vague or underspecified terms",
                "expert": "methodological vocabulary, full domain fluency assumed, debate detail if needed",
            }
            _tone_hint = _tone_hints.get(_ctx.tone, _ctx.tone)
            _complexity_hint = _complexity_hints.get(_ctx.complexity, _ctx.complexity)
            messages.append({
                'role': 'system',
                'content': (
                    f"**Style cue — apply when formulating your response:**\n"
                    f"Tone: {_tone_hint}\n"
                    f"Complexity: {_complexity_hint}"
                )
            })

        # 6c. Completed-context reminder: re-append after conversation history so the model
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
                    "dimension is present, set complete=true and question=\"\"."
                )
            })
        
        # 7. Terminal reinforcement: Repeat cached instructions at end for long conversations
        # Research-backed approach to combat recency bias and maintain instruction adherence
        if terminal_reinforcement_threshold > 0 and len(conversation_history) >= terminal_reinforcement_threshold:
            # Build reinforcement from cached components
            reinforcement_parts = [GLOBAL_SYSTEM_PROMPT]
            if dimension.user_context:
                reinforcement_parts.append(self.render_user_context(dimension.user_context))
            
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
    
    def build_synthesis_messages(
        self,
        original_input: str,
        dimensions: Dict[str, str],
        dimension_list: List[RefinementDimension]
    ) -> List[Dict[str, str]]:
        """
        Build the complete message list for synthesis.
        
        Returns a list of messages ready for LLM API:
        1. System prompt (synthesis template)
        2. Original input
        3. Clarified dimensions
        
        Args:
            original_input: The user's original research query
            dimensions: Dict mapping dimension ID to assembled value
            dimension_list: List of dimension definitions
            
        Returns:
            List of {role: str, content: str} message dicts
        """
        return [
            {"role": "system", "content": self.get_synthesis_system_prompt()},
            {"role": "user", "content": self.render_synthesis_original_input(original_input)},
            {"role": "user", "content": self.render_synthesis_dimensions(dimensions, dimension_list)},
        ]
    
    # =========================================================================
    # Legacy Methods (for backward compatibility)
    # =========================================================================
    
    def build_dimension_refinement_prompt(
        self,
        dimension: RefinementDimension,
        user_context: UserContext,
        original_input: str,
        completed_dimensions: List[CompletedDimension],
        dependency_values: Dict[str, str]
    ) -> str:
        """
        Build dimension refinement prompt (legacy method).
        
        Args:
            dimension: Dimension to refine
            user_context: User context for adaptation
            original_input: User's original research input
            completed_dimensions: Previously completed dimensions
            dependency_values: Dict mapping dimension IDs to assembled values
            
        Returns:
            Complete prompt string ready for LLM
        """
        # Find dependency dimensions
        dependencies = []
        if dimension.depends_on:
            for dep_id in dimension.depends_on:
                dep_dim = next(
                    (d for d in completed_dimensions if d.id == dep_id),
                    None
                )
                if dep_dim:
                    # Create a mock dimension for the template (uses 'name' to match template)
                    dependencies.append(type('Dep', (), {'name': dep_dim.name, 'id': dep_dim.id})())
        
        return self.build_refinement_system_prompt(
            dimension=dimension,
            user_context=user_context,
            completed_dimensions=completed_dimensions,
            dependencies=dependencies if dependencies else None
        )
    
    def build_synthesis_prompt(
        self,
        all_dimensions: List[CompletedDimension],
        original_input: str,
        user_context: UserContext,
        synthesis_purpose: str = "literature search and methodology design"
    ) -> str:
        """
        Build synthesis prompt (legacy method).
        
        Args:
            all_dimensions: All completed dimensions
            original_input: Original user input
            user_context: User context
            synthesis_purpose: What the output will be used for
            
        Returns:
            Complete synthesis prompt
        """
        # Convert completed dimensions to dict format
        dimensions = {d.id: d.assembled_value for d in all_dimensions}
        
        # Build messages and combine
        messages = self.build_synthesis_messages(
            original_input=original_input,
            dimensions=dimensions,
            dimension_list=[]  # Empty since we don't have full dimension definitions
        )
        
        return "\n\n".join(m["content"] for m in messages)


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


def create_dimension_prompt(
    dimension: RefinementDimension,
    user_context: UserContext,
    original_input: str,
    completed_dimensions: List[CompletedDimension] = None,
    dependency_values: Dict[str, str] = None
) -> str:
    """
    Convenience function to create dimension refinement prompt.
    
    Args:
        dimension: Dimension to refine
        user_context: User context
        original_input: User's research input
        completed_dimensions: Previously completed dimensions
        dependency_values: Dependency values dict
        
    Returns:
        Formatted prompt string
    """
    return _default_builder.build_dimension_refinement_prompt(
        dimension=dimension,
        user_context=user_context,
        original_input=original_input,
        completed_dimensions=completed_dimensions or [],
        dependency_values=dependency_values or {}
    )


def create_synthesis_prompt(
    all_dimensions: List[CompletedDimension],
    original_input: str,
    user_context: UserContext,
    synthesis_purpose: str = "literature search and methodology design"
) -> str:
    """
    Convenience function to create synthesis prompt.
    
    Args:
        all_dimensions: All completed dimensions
        original_input: Original user input
        user_context: User context
        synthesis_purpose: Purpose of synthesis
        
    Returns:
        Formatted synthesis prompt
    """
    return _default_builder.build_synthesis_prompt(
        all_dimensions=all_dimensions,
        original_input=original_input,
        user_context=user_context,
        synthesis_purpose=synthesis_purpose
    )