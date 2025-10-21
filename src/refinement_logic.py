"""
Interactive query refinement module - Domain-agnostic, schema-based architecture.

This module helps users improve their queries through iterative refinement,
working with ANY user-defined schema across ANY research domain.

Architecture Overview:
================================================

┌─────────────────────────────────────────────────────────────────┐
│                  QueryRefinementManager                          │
│  (Main orchestrator with dependency injection)                   │
│  - llm_provider: LLMProvider                                     │
│  - query_analyzer: QueryAnalyzer                                │
│  - tracing: TracingProvider                                      │
└───────────────────────────┬─────────────────────────────────────┘
                            │
                            ├──> RefinementSession
                            │    ├── original_query
                            │    ├── schema: List[RefinementDimension]
                            │    ├── current_query
                            │    ├── conversation_history
                            │    └── steps: List[RefinementStep]
                            │
                            └──> RefinementStep
                                 ├── dimension: RefinementDimension
                                 ├── question_generated
                                 ├── user_response
                                 └── is_complete

Key Design Principles:
======================
1. **Domain-Agnostic**: No hard-coded refinement types or domain knowledge
2. **Schema-Based**: Works with any user-defined List[RefinementDimension]
3. **Dependency Injection**: LLM, analyzer, tracing injected via constructor
4. **Zero Hard-Coded Dependencies**: All logic driven by schema definitions
5. **Stateless Methods**: Session passed as parameter for flexible storage

Flow:
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
    """

    dimension: RefinementDimension
    question_generated: Optional[str] = None
    user_response: Optional[str] = None
    is_complete: bool = False
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
    
@dataclass
class RefinementSession:
    """
    Represents an entire query refinement session with conversation history.

    Accepts a list of RefinementDimension defining what aspects can be refined (domain-agnostic).

    Stores the original query, schema, current query state, conversation history, and all refinement steps taken, and metadata.
    """

    original_query: str
    schema: List[RefinementDimension]
    current_query: str = ""
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
    
    def to_dict(self) -> Dict[str, Any]:
        """
        Serializes the session to a dictionary.

        Returns:
            Dict[str, Any]: The serialized session.
        """
        return {
            "original_query": self.original_query,
            "schema": [dim.name for dim in self.schema],
            "current_query": self.current_query,
            "conversation_history": self.conversation_history,
            "steps": [
                {
                    "dimension_id": step.dimension.name,
                    "question_generated": step.question_generated,
                    "user_response": step.user_response,
                    "is_complete": step.is_complete,
                    "context": step.context,
                }
                for step in self.steps
            ],
            "metadata": self.metadata,
        }
