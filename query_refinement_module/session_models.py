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
from .prompt.system_role import GLOBAL_SYSTEM_PROMPT

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
    normalized_value: Optional[Union[str, Dict, List, bool, int, float]] = None
    
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
    
    def get_prompts(self, query: str, dependency_context: Optional[Dict[str, Dict[str, str]]] = None, **kwargs) -> tuple[str, str]:
        """
        Get both system and user prompts for this refinement aspect with dependency context.
        
        Args:
            query: The query to analyze
            dependency_context: Mapping of dependency IDs to dictionaries containing
                human-readable names, descriptions, and values used for prompt context
            **kwargs: Additional context for prompt formatting
            
        Returns:
            Tuple of (system_prompt, analysis_prompt)
        """
        system_prompt = self.refinement_aspect.get_system_role()

        context_lines: List[str] = []
        missing_deps: List[str] = []

        if dependency_context and self.refinement_aspect.depends_on:
            for dep_id in self.refinement_aspect.depends_on:
                entry = dependency_context.get(dep_id)
                if entry and entry.get("value"):
                    dep_name = entry.get("name") or dep_id.replace("_", " ").title()
                    dep_desc = entry.get("description", "")
                    dep_value = entry["value"]
                    
                    # Format: **Name** (Description): Value
                    if dep_desc:
                        context_lines.append(f"- **{dep_name}** ({dep_desc}): {dep_value}")
                    else:
                        context_lines.append(f"- **{dep_name}**: {dep_value}")
                else:
                    missing_deps.append(dep_id)

            if missing_deps:
                logger.warning(
                    "refinement aspect '%s' depends on %s but they have no values. Continuing without that context.",
                    self.refinement_aspect.id,
                    missing_deps,
                )

        refinement_instructions_prompt_sections = [
            self.refinement_aspect.get_evaluation_instructions_prompt(statement=query, **kwargs)
        ]

        if context_lines:
            refinement_instructions_prompt_sections.extend(
                [
                    "",
                    "### Previous refinements (authoritative context)\n"
                    "Use the following confirmed refinements as fixed constraints when evaluating the user-submitted input, "
                    "according to the definition of this refinement aspect:",
                    *context_lines,
                ]
            )
        
        # Include conversation history for multi-turn refinement
        if self.conversation_history:
            conversation_lines = [
                "",
                "### Conversation history for this aspect\n"
                "The following is the conversation history so far for this specific refinement aspect. "
                "Use it as context when determining if further follow-up is needed:",
                ""
            ]
            
            for idx, exchange in enumerate(self.conversation_history, 1):
                question = exchange.get('question', '')
                response = exchange.get('response', '')
                conversation_lines.append(f"**Turn {idx}:**")
                conversation_lines.append(f"Question: {question}")
                conversation_lines.append(f"Answer: {response}")
                conversation_lines.append("")
            
            refinement_instructions_prompt_sections.extend(conversation_lines)

        return system_prompt, "\n".join(refinement_instructions_prompt_sections)
    
    def get_messages(
        self,
        query: str,
        dependency_context: Optional[Dict[str, Dict[str, str]]] = None,
        **kwargs
    ) -> List[Dict[str, str]]:
        """
        Build messages array for LLM API (multi-turn dialogue representation).
        
        Constructs structured messages with:
        1. System message: Global platform instructions
        2. System message: Current dimension name, description, evaluation criteria
        3. System message: Previously completed dimensions (for context)
        4. System message: Dependency specifications (dimensions this one depends on)
        5. User message: Original query to analyze
        6. Conversation history: Alternating assistant/user messages
        
        Args:
            query: The query to analyze
            dependency_context: Values from completed dependencies
            **kwargs: Additional context for prompt formatting
            
        Returns:
            List of message dicts with 'role' and 'content' keys
        """
        messages = []
        
        # 1. System message: Global platform instructions
        messages.append({
            'role': 'system',
            'content': GLOBAL_SYSTEM_PROMPT
        })
        
        # 2. System message: Current dimension specification
        dimension_spec = "\n".join([
            f"# Current Dimension: {self.refinement_aspect.aspect_name}",
            f"\n**Description:** {self.refinement_aspect.aspect_description}",
            f"\n## Evaluation Criteria\n",
            self.refinement_aspect.evaluation_instructions
        ])
        messages.append({
            'role': 'system',
            'content': dimension_spec
        })
        
        # 3. System message: Previously completed dimensions (for context)
        if dependency_context:
            completed_dims = []
            for dep_id, entry in dependency_context.items():
                if entry and entry.get("value"):
                    dep_name = entry.get("name") or dep_id.replace("_", " ").title()
                    dep_desc = entry.get("description", "")
                    dep_value = entry["value"]
                    
                    if dep_desc:
                        completed_dims.append(f"**{dep_name}** ({dep_desc}): {dep_value}")
                    else:
                        completed_dims.append(f"**{dep_name}**: {dep_value}")
            
            if completed_dims:
                context_message = "\n".join([
                    "# Previously Completed Dimensions",
                    "\nThe following dimensions have been refined and clarified:",
                    "",
                    *completed_dims
                ])
                messages.append({
                    'role': 'system',
                    'content': context_message
                })
        
        # 4. System message: Dependency specifications (what this dimension must consider)
        if self.refinement_aspect.depends_on and dependency_context:
            dependency_specs = []
            for dep_id in self.refinement_aspect.depends_on:
                entry = dependency_context.get(dep_id)
                if entry and entry.get("value"):
                    dep_name = entry.get("name") or dep_id.replace("_", " ").title()
                    dep_desc = entry.get("description", "")
                    dep_value = entry["value"]
                    
                    if dep_desc:
                        dependency_specs.append(f"**{dep_name}** ({dep_desc}): {dep_value}")
                    else:
                        dependency_specs.append(f"**{dep_name}**: {dep_value}")
            
            if dependency_specs:
                depends_message = "\n".join([
                    "# Dimensions This Evaluation Must Consider",
                    "\nWhen evaluating the current dimension, you MUST take into account:",
                    "",
                    *dependency_specs,
                    "",
                    "Use these as authoritative constraints when analyzing the user's input."
                ])
                messages.append({
                    'role': 'system',
                    'content': depends_message
                })
        
        # 5. User message: Original query to analyze
        user_message = f"**Original Research Input:**\n{query}"
        messages.append({
            'role': 'user',
            'content': user_message
        })
        
        # 6. Conversation history: Alternating assistant/user messages
        for qa in self.conversation_history:
            # Assistant asks the question
            messages.append({
                'role': 'assistant',
                'content': qa['question']
            })
            # User provides the response
            messages.append({
                'role': 'user',
                'content': qa['response']
            })
        
        return messages
    
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
    
    def get_conversation_history_text(self) -> str:
        """
        Format follow-up history for use in prompts.
        """
        if not self.conversation_history:
            return "no previous follow-up questions."
        
        history_lines = []
        for i, qa in enumerate(self.conversation_history, start=0):
            history_lines.append(f"Follow-up {i+1}:") # i+1 to make it human-friendly
            history_lines.append(f" Q: {qa.get('question', '')}")
            history_lines.append(f" A: {qa.get('response', '')}")
        return "\n".join(history_lines)
    
    def format_follow_up_prompt_template(
        self,
        original_query: str,
    ) -> str:
        """Build a follow-up analysis prompt with explicit context history guidance.

        The follow-up flow reuses the refinement aspect's schema while adding
        instructions that clarify this is a subsequent turn. The conversation
        history for the aspect is appended so the LLM can avoid repetition and
        focus on unresolved details.

        Args:
            original_query: The initial user query for the session.

        Returns:
            Formatted prompt string ready for an LLM follow-up call.
        """

        history_text = self.get_conversation_history_text()
        latest_answer = self.normalized_value_as_str or ""
        
        # Get current refinement aspect value for display
        current_value = self.normalized_value
        value_display = ""
        if current_value is not None:
            field_name = self.refinement_aspect.id
            if isinstance(current_value, (dict, list)):
                value_json = json.dumps(current_value, indent=2, ensure_ascii=False)
                value_display = f"\n\nCURRENT VALUE FOR '{field_name}':\n{value_json}"
            else:
                value_display = f"\n\nCURRENT VALUE FOR '{field_name}': {current_value}"

        follow_up_preamble = textwrap.dedent(
            f"""
            FOLLOW-UP CONTEXT:
            For aspect "{self.refinement_aspect.aspect_name}", review the conversation history below.
            Only ask for information that is still missing or unclear.{value_display}
            
            At each response, you MUST update the '{self.refinement_aspect.id}' field with the CUMULATIVE SYNTHESIZED value.
            This means each response should build upon previous answers, progressively refining the value.
            
            If complete, set ``needs_refinement`` to ``false`` and provide:
            1. A brief explanation of why no further follow-up is needed (explanation field)
            2. In the ``{self.refinement_aspect.id}`` field, provide the FINAL SYNTHESIZED value that:
               - Combines ALL user responses from the entire conversation history
               - Forms ONE coherent, complete statement (or structured object/array)
               - Removes conversational language ("I think", "maybe", "probably", "I guess", "kind of")
               - Removes filler words and unnecessary elaboration ("well", "you know", "obviously", "definitely")
               - Removes meta-commentary ("I want to study", "I'm interested in", "This research focuses on")
               - Includes all key factual details from ALL answers
               - Is written as a clear, declarative statement (not as an answer to a question)
               - Focuses on essential information only
            
            Example conversation:
              Q1: What age group?
              A1: Well, I'm thinking probably adults, you know, not kids
              Q2: Specific ages?
              A2: Maybe like 18 to 65 or so
              Q3: Any conditions?
              A3: Yeah definitely Type 2 diabetes, but not the gestational kind obviously
            
            GOOD {self.refinement_aspect.id}: "Adults aged 18-65 with Type 2 diabetes (excluding gestational diabetes)"
            (Synthesizes all 3 answers, removes conversational fluff, forms coherent statement)
            
            BAD {self.refinement_aspect.id}: "Yeah definitely Type 2 diabetes, but not the gestational kind obviously"
            (Only last answer - missing age information! Keeps conversational language!)
            
            BAD {self.refinement_aspect.id}: "The user wants to study adults probably 18-65 with Type 2 diabetes"
            (Keeps meta-commentary and uncertain language like "wants to study", "probably")
            """
        ).strip()

        history_section_lines = ["Conversation history for this aspect:", history_text]
        if latest_answer:
            history_section_lines.extend(
                [
                    "",
                    "Most recent user answer:",
                    latest_answer,
                ]
            )
        history_section = "\n".join(history_section_lines)

        base_prompt = self.refinement_aspect.get_evaluation_instructions_prompt(
            statement=original_query
        )

        sections = [follow_up_preamble, history_section, base_prompt]
        return "\n\n".join(section for section in sections if section)
    

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
    
    @property
    def refinement_framework(self) -> List[RefinementAspect]:
        """Get the refinement framework from the steps."""
        return [step.refinement_aspect for step in self.steps]
    
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
                raw_value = f"[{aspect.aspect_name} is clear in original query: \"{self.original_query}\"]"
            
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
                    "name": aspect.aspect_name,
                    "description": aspect.aspect_description,
                    "value": formatted_value,
                    "type": value_type,
                }

        return context
    
    def is_complete(self) -> bool:
        """
        Checks if all refinement steps are complete.
        """
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
                    "refinement_aspect": step.refinement_aspect.aspect_name,
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
                
            lines.append(f"[{step.refinement_aspect.aspect_name}]")
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
                invalidated.append(step.refinement_aspect.aspect_name)
                
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
            "refinement_aspects": [aspect.aspect_name for aspect in self.refinement_framework],
            "steps": [
                {
                    "refinement_aspect_id": step.refinement_aspect.id,
                    "refinement_aspect_name": step.refinement_aspect.aspect_name,
                    "refinement_aspect_description": step.refinement_aspect.aspect_description,
                    # Multi-turn conversation
                    "follow_up_history": step.conversation_history,
                    # Completion status
                    "is_complete": step.is_complete,
                    "refinement_aspect_value": step.normalized_value_as_str,
                }
                for step in self.steps
            ],
        }
