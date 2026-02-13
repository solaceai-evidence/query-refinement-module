"""
Session state models for query refinement.

Contains the core data structures that track refinement session state:
- AspectRefinementState: Tracks refinement progress for a single aspect
- RefinementSession: Manages the overall refinement session

Extracted from core.py to improve modularity and reduce file complexity.
"""

import json
import logging
import textwrap
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Union

from .schema import RefinementAspect
from .schema.templates.global_system import GLOBAL_SYSTEM_PROMPT

logger = logging.getLogger(__name__)


@dataclass
class AspectRefinementState:
    """
    Represents the state of the evaluation for a single research dimension (aspect).
    
    Tracks the multi-turn conversation (initial question + follow-ups) until
    a final refined value for the aspect is obtained and accepted.

    Attributes:
        refinement_aspect: The RefinementAspect being refined   
        conversation_history: List of Q&A dicts for multi-turn refinement
        is_complete: Whether refinement is complete for this aspect
        needs_review: Whether the aspect needs review due to dependency changes
        was_skipped: Whether the user skipped this aspect entirely
        reasoning: Analysis result reasoning for refinement need/question
        follow_up_question: The clarification question for this aspect
        refinement_aspect_value: The extracted refined value in native type
    """

    refinement_aspect: RefinementAspect
    
    # Multi-turn conversation history (initial + all follow-ups)
    # Each entry: {'question': '...', 'response': '...'}
    conversation_history: List[Dict[str, str]] = field(default_factory=list)
    
    # Completion status - set when refinement is accepted/skipped or not needed as info is clear
    is_complete: bool = False
    
    # Review status - set when dependencies change, preserves history for review
    needs_review: bool = False

    # Whether the step was explicitly skipped by the user without supplying a value (or if supplied, value will be discarded)
    was_skipped: bool = False
    
    # Analysis result - stored from LLM's structured analysis output during initialize()
    # Contains: needs_refinement_rationale (why refinement needed/not), follow_up_question (what to ask)
    reasoning: Optional[str] = None
    follow_up_question: Optional[str] = None
    
    # Stores the aspect specification as refined by user interaction 
    normalized_value: Optional[str] = None
    
    @property
    def follow_up_count(self) -> int:
        """Number of follow-up rounds completed."""
        return len(self.conversation_history)
    
    @property
    def normalized_value_as_str(self) -> Optional[str]:
        """
        Get string representation of refinement aspect value for display/storage.
        
        Returns:
            String representation of normalized_value (JSON for complex types)
        """
        if self.normalized_value is not None:
            if isinstance(self.normalized_value, (dict, list)):
                return json.dumps(self.normalized_value, ensure_ascii=False)
            return str(self.normalized_value)
        return None
    
    def extract_and_store_value(self, response: str) -> None:
        """
        Extract value from dynamic field in response and store in normalized_value.
        
        Single extraction point - eliminates duplicate logic across codebase.
        Parses JSON response, extracts aspect.id field, stores with native type.
        If not JSON, stores the plain text response directly.
        
        Args:
            response: JSON response string from LLM, or plain text
        """
        if not response or not isinstance(response, str):
            return
            
        # Try to parse as JSON
        if response.strip().startswith("{"):
            try:
                parsed = json.loads(response)
                if isinstance(parsed, dict):
                    field_name = self.refinement_aspect.id
                    if field_name in parsed:
                        value = parsed[field_name]
                        # Store non-empty values (handle empty strings, lists, dicts)
                        if value or isinstance(value, (bool, int, float)):
                            self.normalized_value = value
                            return
            except (json.JSONDecodeError, TypeError):
                pass  # Not valid JSON, fall to plain text handling
        
        # For non-JSON responses, store the plain text directly
        # This preserves the behavior where any response contributes to the value
        if response.strip():
            self.normalized_value = response.strip()

    def get_global_system_role(self) -> str:
        """
        Get the global system role prompt for this refinement aspect.
        
        Returns:
            Global system prompt string
        """
        return self.refinement_aspect.get_system_role()
    
    def get_messages(
        self,
        query: str,
        dependency_context: Optional[Dict[str, Dict[str, str]]] = None,
        completed_context: Optional[List[Dict[str, Any]]] = None,
        terminal_reinforcement_threshold: Optional[int] = None,
        **kwargs
    ) -> List[Dict[str, str]]:
        """
        Build messages array for LLM API (multi-turn dialogue representation).
        
        Delegates to PromptBuilder for message construction - keeps session_models
        focused on state management, not prompt building logic.
        
        Args:
            query: The query to analyze
            dependency_context: Values from completed dependencies
            terminal_reinforcement_threshold: Add reinforcement after N turns (None=use default from settings)
            **kwargs: Additional context (unused, for backward compatibility)
            
        Returns:
            List of message dicts with 'role' and 'content' keys
        """
        from query_refinement_module.schema.prompt_builder import build_refinement_messages
        
        # Terminal reinforcement threshold: use provided value or default to 3 (hardcoded optimal)
        threshold = terminal_reinforcement_threshold if terminal_reinforcement_threshold is not None else 3
        
        return build_refinement_messages(
            dimension=self.refinement_aspect,
            query=query,
            conversation_history=self.conversation_history,
            dependency_context=dependency_context,
            completed_context=completed_context,
            terminal_reinforcement_threshold=threshold
        )
    
    def can_ask_followup(self) -> bool:
        """
        Check if follow-ups are allowed for this aspect.
        
        Note: This does NOT enforce max_follow_ups in web API (user controls pace).
        Only used by CLI batch mode to prevent infinite loops.
        """
        return self.refinement_aspect.allow_follow_up and (self.follow_up_count < self.refinement_aspect.max_follow_ups)

    def add_follow_up(self, question: str, response: str) -> None:
        """
        Adds a follow-up question/response pair to the history.
        
        Automatically extracts and stores the refined value from the response.
        """
        self.was_skipped = False
        self.conversation_history.append({
            "question": question,
            "response": response
        })
        # Extract and store value from response
        self.extract_and_store_value(response)


@dataclass
class RefinementSession:
    """
    Represents an entire query refinement session.
    
    Tracks the original query and the multi-step refinement process through
    a list of QueryAspectRefiner objects, one per refinement aspect regardless of whether it needs refinement.
    """

    original_query: str
    steps: List[AspectRefinementState] = field(default_factory=list)
    synthesis_requested: bool = False
    _complete_framework: List[RefinementAspect] = field(default_factory=list)
    
    @property
    def refinement_framework(self) -> List[RefinementAspect]:
        """Get the refinement framework from the steps."""
        return [step.refinement_aspect for step in self.steps]
    
    @property
    def complete_framework(self) -> List[RefinementAspect]:
        """Get the complete original framework (all dimensions)."""
        return self._complete_framework
    
    def add_step(
        self,
        refinement_aspect: RefinementAspect,
    ) -> AspectRefinementState:
        """
        Adds a new refinement step to the session for a refinement aspect.

        Args:
            refinement_aspect (RefinementAspect): The refinement aspect being refined.
        
        Returns:
            QueryAspectRefiner: The newly created query aspectrefiner.
        """
        step = AspectRefinementState(
            refinement_aspect=refinement_aspect,
            is_complete=False,
        )
        self.steps.append(step)
        return step
    
    def get_active_step(self) -> Optional[AspectRefinementState]:
        """Return the first step that still requires user attention."""

        for step in self.steps:
            if not step.is_complete or step.needs_review:
                return step

        return None
    
    def get_next_unrefined_aspect(self) -> Optional[AspectRefinementState]:
        """
        Get the next aspect that needs refinement in dependency order.
        
        Returns the first aspect where:
        - Not yet complete
        - All dependencies are complete
        
        This enables sequential on-demand refinement without upfront analysis.
        
        Returns:
            QueryAspectRefiner if there's a ready aspect, None if all done or blocked
        """
        for step in self.steps:
            # Skip completed or skipped steps
            if step.is_complete:
                continue
            
            # Check if all dependencies are satisfied
            dependencies = step.refinement_aspect.depends_on or []
            if not dependencies:
                # No dependencies, ready to refine
                return step
            
            # Check all dependencies are complete
            all_deps_complete = True
            for dep_id in dependencies:
                dep_step = next((s for s in self.steps if s.refinement_aspect.id == dep_id), None)
                if not dep_step or not dep_step.is_complete:
                    all_deps_complete = False
                    break
            
            if all_deps_complete:
                return step
        
        return None
    
    def get_step_by_aspect_id(self, aspect_id: str) -> Optional[AspectRefinementState]:
        """
        Find a step by its refinement aspect ID.
        
        Args:
            aspect_id: The ID of the refinement aspect
            
        Returns:
            QueryAspectRefiner if found, None otherwise
        """
        for step in self.steps:
            if step.refinement_aspect.id == aspect_id:
                return step
        return None
    
    def get_dependency_context(self, target_refinement_aspect_id: str) -> Dict[str, Dict[str, Any]]:
        """
        Build dependency context for a specific refinement aspect.
        
        Only includes dependencies declared by the target refinement aspect.
        Values come from either:
        - Refined values (for aspects that were refined through interaction)
        - Original query reference (for aspects that were already clear)
        
        Args:
            target_refinement_aspect_id: The refinement aspect ID that needs dependency context
            
        Returns:
            Dictionary mapping dependency IDs to metadata containing:
            - name: The aspect name
            - description: The aspect description
            - value: The actual value (formatted for complex types)
            - type: The value type (string, object, array, etc.)
        """
        step_index = {step.refinement_aspect.id: step for step in self.steps}
        target_step = step_index.get(target_refinement_aspect_id)
        if not target_step:
            # This is expected during initialization before steps are populated
            logger.debug(
                "Dependency context requested for aspect '%s' before session populated",
                target_refinement_aspect_id,
            )
            return {}

        dependencies = target_step.refinement_aspect.depends_on or []
        if not dependencies:
            return {}

        context: Dict[str, Dict[str, Any]] = {}
        for dep_id in dependencies:
            dep_step = step_index.get(dep_id)
            if not dep_step:
                logger.debug(
                    "Dependency '%s' not yet available for aspect '%s'",
                    dep_id,
                    target_refinement_aspect_id,
                )
                continue

            aspect = dep_step.refinement_aspect
            value_type = "string"
            
            # Get the refinement aspect value directly (single source of truth)
            raw_value = None
            
            # Skip entirely if aspect was skipped - no context provided
            if dep_step.was_skipped:
                logger.debug(
                    "Dependency '%s' was skipped - excluding from context for '%s'",
                    dep_id,
                    target_refinement_aspect_id,
                )
                continue
            
            if dep_step.normalized_value is not None:
                raw_value = dep_step.normalized_value
            elif dep_step.is_complete:
                # Aspect was clear in original query
                raw_value = f"[{aspect.name} is clear in original query: \"{self.original_query}\"]"
            
            # Format value based on type
            formatted_value = raw_value
            if raw_value and value_type in ("object", "array"):
                # Pretty-print JSON for complex types
                if isinstance(raw_value, (dict, list)):
                    formatted_value = json.dumps(raw_value, indent=2, ensure_ascii=False)
                elif isinstance(raw_value, str) and raw_value.strip().startswith(('{', '[')):
                    try:
                        parsed = json.loads(raw_value)
                        formatted_value = json.dumps(parsed, indent=2, ensure_ascii=False)
                    except (json.JSONDecodeError, TypeError):
                        formatted_value = raw_value
            elif raw_value and not isinstance(raw_value, str):
                # Convert non-string simple types to string
                formatted_value = str(raw_value)
            
            if raw_value is not None:
                context[dep_id] = {
                    "name": aspect.name,
                    "description": aspect.description,
                    "value": formatted_value,
                    "type": value_type,
                }

        return context

    def get_completed_context(self, target_refinement_aspect_id: str) -> List[Dict[str, Any]]:
        """
        Build completed-dimensions context (all prior completed dimensions) for a target aspect.

        Includes skipped dimensions as value '[SKIPPED]' so downstream prompt logic
        can explicitly reflect intentional omission.
        """
        step_index = {step.refinement_aspect.id: idx for idx, step in enumerate(self.steps)}
        target_idx = step_index.get(target_refinement_aspect_id)
        if target_idx is None:
            return []

        context: List[Dict[str, Any]] = []
        for idx, step in enumerate(self.steps):
            if idx >= target_idx:
                break
            if not step.is_complete:
                continue

            aspect = step.refinement_aspect
            if step.was_skipped:
                value = "[SKIPPED]"
            elif step.normalized_value is not None:
                value = step.normalized_value_as_str or ""
            else:
                value = f"[{aspect.name} is clear in original query: \"{self.original_query}\"]"

            context.append(
                {
                    "id": aspect.id,
                    "name": aspect.name,
                    "description": aspect.description,
                    "value": value,
                    "was_skipped": step.was_skipped,
                }
            )

        return context
    
    def is_complete(self) -> bool:
        """
        Checks if all refinement steps are complete.
        
        For sequential refinement, this means:
        1. All aspects in the framework have been processed (added to steps)
        2. All processed steps are marked complete
        """
        # Check if all framework aspects have been processed
        if len(self.steps) < len(self.refinement_framework):
            return False
        
        # Check if all processed steps are complete
        return all(step.is_complete for step in self.steps)
    
    def get_step_summary(self) -> Dict[str, Any]:
        """
        Get a summary of all steps with their follow-up status.
        
        Returns:
            Dictionary with step statistics and status.
        """
        completed = needs_review = in_progress = 0
        total_followups = 0
        step_summaries = []

        for step in self.steps:
            total_followups += step.follow_up_count
            if step.is_complete and not step.needs_review:
                completed += 1
            elif step.needs_review:
                needs_review += 1
            else:
                in_progress += 1

            step_summaries.append(
                {
                    "refinement_aspect": step.refinement_aspect.name,
                    "is_complete": step.is_complete,
                    "needs_review": step.needs_review,
                    "follow_up_count": step.follow_up_count,
                    "has_refinement_aspect_value": step.normalized_value_as_str is not None,
                }
            )

        return {
            "total_steps": len(self.steps),
            "completed": completed,
            "needs_review": needs_review,
            "in_progress": in_progress,
            "total_follow_ups": total_followups,
            "steps": step_summaries,
        }
    
    def get_full_conversation(self) -> str:
        """
        Get the complete conversation as formatted text.
        
        Reconstructs the conversation from the step-by-step refinement history.
        
        Returns:
            Human-readable conversation history.
        """
        lines = ["CONVERSATION HISTORY", "="*80]
        lines.append(f"Original Query: {self.original_query}")
        lines.append("="*80)
        lines.append("")
        
        for step in self.steps:
            if not step.conversation_history:
                continue
                
            lines.append(f"[{step.refinement_aspect.name}]")
            lines.append("")
            
            for i, qa in enumerate(step.conversation_history, 1):
                interaction_type = "initial" if i == 1 else f"follow-up {i-1}"
                lines.append(f"  [{interaction_type}]")
                lines.append(f"  Q: {qa.get('question', '')}")
                if qa.get('response'):
                    lines.append(f"  A: {qa['response']}")
                lines.append("")  # Blank line
            
            if step.normalized_value_as_str:
                lines.append(f"  ✓ Final value: {step.normalized_value_as_str}")
                lines.append("")
        
        return "\n".join(lines)
    
    def handle_command(self, cmd_result):
        """
        Execute a user command and return the result.
        
        Args:
            cmd_result: Parsed command result from parse_user_command()
            
        Returns:
            Dict with 'success', 'message', and optional command-specific data
        """
        # Import locally to avoid circular dependency
        from .session_commands import SessionCommands
        
        if not cmd_result.is_valid:
            return {
                "success": False,
                "message": cmd_result.error_message or "Invalid command",
            }
        
        # Delegate to SessionCommands helper
        commands = SessionCommands(self)
        return commands.execute(cmd_result.command)
    
    def _invalidate_dependents(self, changed_refinement_aspect_id: str) -> List[str]:
        """
        Soft-invalidate all refinement aspects that depend on the changed refinement aspect.
        
        Preserves conversation history but marks steps for review.
        
        Args:
            changed_refinement_aspect_id: The refinement aspect ID that was changed
            
        Returns:
            List of invalidated refinement aspect names
        """
        invalidated = []
        
        for step in self.steps:
            if changed_refinement_aspect_id in step.refinement_aspect.depends_on:
                # Soft invalidate: preserve history but mark for review
                step.is_complete = False
                step.needs_review = True  # Flag for review, DON'T clear history
                step.was_skipped = False
                invalidated.append(step.refinement_aspect.name)
                
                # Recursively invalidate dependents of this step
                sub_invalidated = self._invalidate_dependents(step.refinement_aspect.id)
                invalidated.extend(sub_invalidated)
        
        return invalidated
    
    def to_dict(self) -> Dict[str, Any]:
        """
        Serializes the session to a dictionary.

        Returns:
            Dict[str, Any]: The serialized session.
        """
        return {
            "original_query": self.original_query,
            "refinement_aspects": [aspect.name for aspect in self.refinement_framework],
            "steps": [
                {
                    "refinement_aspect_id": step.refinement_aspect.id,
                    "refinement_aspect_name": step.refinement_aspect.name,
                    "refinement_aspect_description": step.refinement_aspect.description,
                    # Multi-turn conversation
                    "follow_up_history": step.conversation_history,
                    # Completion status
                    "is_complete": step.is_complete,
                    "refinement_aspect_value": step.normalized_value_as_str,
                }
                for step in self.steps
            ],
        }
