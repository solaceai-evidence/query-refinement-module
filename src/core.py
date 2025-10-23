"""
Interactive query refinement module - Domain-agnostic, schema-based architecture.

This module helps users improve their queries through iterative refinement,
working with ANY user-defined schema across ANY research domain.

Pipeline Flow:
=====
1. User provides initial query + schema (e.g., PICO_SCHEMA, CLIMATE_SCHEMA, custom)
2. Manager.initialize() uses query_analyzer to detect missing dimensions and generate questions using dimensions' analysis_prompt
3. For each needed dimension:
   a. Present question to user
   b. Receive and store user's response
   c. Check if follow-ups are needed; if so, repeat
4. Synthesize all refinements into improved query (natural language, structured, etc.)
5. Return refined query for processing
"""

import logging
from contextlib import contextmanager
from dataclasses import dataclass, field
from time import time
from typing import Any, Dict, List, Optional

from interfaces import LLMProviderInterface, TracingProviderInterface, QueryAnalyzerInterface
from schemas import RefinementDimension

logger = logging.getLogger(__name__)

# =======
# Data Classes
# =======

@dataclass
class RefinementStep:
    """
    Represents a single query refinement interaction in the dialogue.
    Stores a single RefinementDimension, the generated question (optional), user response (optional), and completion status, and context.
    Additionally, it supports multi-turn follow-up questions for deeper clarification.
    """

    dimension: RefinementDimension
    # Init question/response pair
    question_generated: Optional[str] = None
    user_response: Optional[str] = None

    # Follow-up tracking
    follow_up_count: int = 0
    follow_up_history: List[Dict[str, str]] = field(default_factory=list)
    # Each entry in follow_up_history is a dict with 'question' and 'response' keys

    is_complete: bool = False
    final_value: Optional[Any] = None # Final refined value after all Q&A

    # Additional context for prompt formatting
    context: Dict[str, Any] = field(default_factory=dict)

    def format_prompt(
            self,
            query: str,
            **kwargs,
    )-> str:
        """
        Format the analysis prompt for this dimension using the current query and any additional context (TODO).
        """
        prompt = self.dimension.get_full_prompt(
            query=query,
            **kwargs,
        )
        return prompt
    
    def can_ask_followup(self) -> bool:
        """
        Determines if a follow-up question can be asked based on the dimension's max_follow_ups.
        """
        return self.dimension.allow_follow_up and (self.follow_up_count < self.dimension.max_follow_ups)

    def add_follow_up(self, question: str, response: str):
        """
        Adds a follow-up question/response pair to the history and increments the follow-up count.
        """
        self.follow_up_history.append({
            "question": question,
            "answer": response
        })
        self.follow_up_count += 1
    
    def get_conversation_history_text(self) -> str:
        """
        Format follow-up history for use in prompts.
        """
        if not self.follow_up_history:
            return "no previous follow-up questions."
        
        history_lines = []
        for i, qa in enumerate(self.follow_up_history, start=0):
            history_lines.append(f"Follow-up {i+1}:") # i+1 to make it human-friendly
            history_lines.append(f" Q: {qa['question']}")
            history_lines.append(f" A: {qa['answer']}")
        return "\n".join(history_lines)
    
    def format_follow_up_prompt_template(
            self,
            original_query: str, 
            latest_answer: str,
    ) -> str:
        """
        Format the follow-up prompt for this dimension using the current query and latest answer.
        Uses UNIVERSAL_FOLLOWUP_ANALYSIS_PROMPT, and includes previous follow-up history.
        """
        from .followup_prompt import UNIVERSAL_FOLLOWUP_ANALYSIS_PROMPT

        conversation_history = self.get_conversation_history_text()

        prompt = UNIVERSAL_FOLLOWUP_ANALYSIS_PROMPT.format(
            original_query=original_query,
            dimension_name=self.dimension.name,
            dimension_description=self.dimension.description,
            conversation_history=conversation_history,
            latest_answer=latest_answer,
        )
        return prompt
    
    def complete_with_value(self, final_value: str):
        """Mark the step as complete with the final refined value."""
        self.is_complete = True
        self.final_value = final_value
    
@dataclass
class RefinementSession:
    """
    Represents an entire query refinement session with conversation history.

    Accepts a list of RefinementDimension defining what aspects can be refined (domain-agnostic).

    Stores the original query, dimensions, current query state, conversation history, and all refinement steps taken, and metadata.
    """

    original_query: str
    dimensions: List[RefinementDimension]
    current_query: str = "" # Updated query as refinements are made
    conversation_history: List[Dict[str, str]] = field(default_factory=list)
    steps: List[RefinementStep] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        # Initialize current_query to original_query if not set
        if not self.current_query:
            self.current_query = self.original_query

    def add_step(
            self,
            dimension: RefinementDimension,
            context: Optional[Dict[str, Any]] = None,
        ) -> RefinementStep:
        """
        Adds a new refinement step to the session for a dimension.

        Args:
            dimension (RefinementDimension): The dimension being refined.
            context (Optional[Dict[str, Any]]): Additional context for prompt formatting.
        
        Returns:
            RefinementStep: The newly created refinement step.
        """
        step = RefinementStep(
            dimension=dimension,
            context=context or {},
        )
        self.steps.append(step)
        return step
    
    def get_active_step(self) -> Optional[RefinementStep]:
        """
        Returns the current active refinement step (the last one that is not complete).
        """
        for step in self.steps:
            if not step.is_complete:
                return step
        return None
    
    def add_to_history(
            self,
            role: str,
            content: str
    ):
        """
        Adds a message to the conversation history.
        """
        self.conversation_history.append({
            "role": role,
            "content": content
        })
    
    def is_complete(self) -> bool:
        """
        Checks if all refinement steps are complete.
        """
        return all(step.is_complete for step in self.steps)
    
    def get_total_follow_ups(self) -> int:
        """
        Get total number of follow-up questions across all steps.
        
        Returns:
            Total count of follow-up questions asked in this session.
        """
        return sum(step.follow_up_count for step in self.steps)
    
    def get_step_summary(self) -> Dict[str, Any]:
        """
        Get a summary of all steps with their follow-up status.
        
        Returns:
            Dictionary with step statistics and status.
        """
        completed = sum(1 for step in self.steps if step.is_complete)
        in_progress = sum(1 for step in self.steps if not step.is_complete)
        total_followups = self.get_total_follow_ups()
        
        return {
            "total_steps": len(self.steps),
            "completed": completed,
            "in_progress": in_progress,
            "total_follow_ups": total_followups,
            "steps": [
                {
                    "dimension": step.dimension.name,
                    "is_complete": step.is_complete,
                    "follow_up_count": step.follow_up_count,
                    "has_final_value": step.final_value is not None,
                }
                for step in self.steps
            ]
        }
    
    def add_interaction(
        self, 
        step: RefinementStep,
        question: str,
        answer: Optional[str] = None,
        is_follow_up: bool = False
    ):
        """
        Add an interaction to both the step and session-level conversation history.
        
        Args:
            step: The refinement step this interaction belongs to
            question: The question asked
            answer: The user's answer (None if not yet answered)
            is_follow_up: Whether this is a follow-up question
        """
        interaction_type = "follow_up" if is_follow_up else "initial"
        
        # Add to session-level history
        self.add_to_history(
            role="assistant",
            content=f"[{step.dimension.name}] [{interaction_type}] {question}"
        )
        
        if answer:
            self.add_to_history(
                role="user",
                content=f"[{step.dimension.name}] [{interaction_type}] {answer}"
            )
    
    def get_full_conversation(self) -> str:
        """
        Get the complete conversation as formatted text.
        
        Returns:
            Human-readable conversation history.
        """
        lines = [f"Original Query: {self.original_query}", ""]
        
        for msg in self.conversation_history:
            role_label = "Assistant" if msg["role"] == "assistant" else "User"
            lines.append(f"{role_label}: {msg['content']}")
        
        if self.current_query != self.original_query:
            lines.append("")
            lines.append(f"Refined Query: {self.current_query}")
        
        return "\n".join(lines)
    
    def to_dict(self) -> Dict[str, Any]:
        """
        Serializes the session to a dictionary, including all follow-up data.

        Returns:
            Dict[str, Any]: The serialized session.
        """
        return {
            "original_query": self.original_query,
            "dimensions": [dim.name for dim in self.dimensions],
            "current_query": self.current_query,
            "conversation_history": self.conversation_history,
            "steps": [
                {
                    "dimension_id": step.dimension.id,
                    "dimension_name": step.dimension.name,
                    "dimension_description": step.dimension.description,
                    # Initial question/response
                    "question_generated": step.question_generated,
                    "user_response": step.user_response,
                    # Follow-up tracking
                    "follow_up_count": step.follow_up_count,
                    "follow_up_history": step.follow_up_history,
                    # Completion
                    "is_complete": step.is_complete,
                    "final_value": step.final_value,
                    # Context
                    "context": step.context,
                }
                for step in self.steps
            ],
            "metadata": self.metadata,
        }
