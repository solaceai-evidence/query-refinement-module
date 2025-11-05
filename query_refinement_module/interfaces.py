"""
Abstract interfaces for the query refinement module.

These interfaces define the contracts for external dependencies, enabling the module to remain independent while allowing flexible integration with different LLM providers, tracing systems, and query analysis approaches.
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Dict, Optional, List

if TYPE_CHECKING:
    from .schema import RefinementAspect

# ===========
# Analysis Result Types
# ===========
@dataclass
class AspectAnalysisResult:
    """
    Result of analyzing a single aspect.
    
    This matches the structured output from LLM analysis (BASE_SCHEMA_FIELDS in RefinementAspect):
    - needs_refinement: boolean
    - explanation: string (why refinement is/isn't needed)
    - suggested_question: string (the question to ask if refinement needed)
    
    Attributes:
        needs_refinement: Whether the aspect needs refinement.
        reason: Explanation of why refinement is or isn't needed.
        suggested_question: The question to ask the user (if needs_refinement=True).
    """
    needs_refinement: bool
    explanation: str
    suggested_question: Optional[str] = None

# ===========
# LLM Provider Interface
# ===========
@dataclass
class LLMCompletionResult:
    """
    Standard result object from LLM completion.

    Attributes:
        context: The generated text from the LLM.
        model: The model identifier used for the completion.
        total_tokens (int): Total number of tokens used in the completion (if available).
        cost: Estimated cost of the completion (if available).
        metadata (Dict[str, Any]): Additional provider-specific metadata about the completion.
    """
    context: str
    model: str
    total_tokens: Optional[int] = None
    cost: Optional[float] = None
    metadata: Optional[Dict[str, Any]] = None

    def __post_init__(self):
        if self.metadata is None:
            self.metadata = {}


class LLMProviderInterface(ABC):
    """
    Abstract interface for LLM providers.

    This interface defines the contract for any LLM provider integration,
    ensuring consistent interaction with different LLM services.
    """

    @abstractmethod
    def complete(
        self,
        user_prompt: str,
        system_prompt: Optional[str] = None,
        model: Optional[str] = None,
        temperature: float = 0.0,
        max_tokens: Optional[int] = None,
        **kwargs,
    ) -> LLMCompletionResult:
        """
        Generate a completion from the LLM based on the provided prompt.

        Args:
            user_prompt (str): The input prompt to send to the LLM.
            system_prompt (Optional[str]): An optional system prompt to guide the LLM.
            model (Optional[str]): The model identifier to use for the completion.
            temperature (float): Sampling temperature for the completion.
            max_tokens (Optional[int]): Maximum number of tokens to generate.
            **kwargs: Additional provider-specific parameters.

        Returns:
            LLMCompletionResult: The result of the LLM completion.
        
        Raises:
            NotImplementedError: If the method is not implemented by the subclass.
            Exception: For any errors during the completion process (implementation-specific).
        """
        pass
        raise NotImplementedError("LLMProviderInterface.complete() must be implemented by subclasses.")
    
    @abstractmethod
    def get_model_info(self, model: str) -> Dict[str, Any]:
        """
        Retrieve information about a specific LLM model.

        Args:
            model (str): The model identifier.

        Returns:
            Dict[str, Any]: A dictionary containing model information such as capabilities, token limits, etc.
        
        Raises:
            NotImplementedError: If the method is not implemented by the subclass.
            Exception: For any errors during the retrieval process (implementation-specific).
        """
        pass
        raise NotImplementedError("LLMProviderInterface.get_model_info() must be implemented by subclasses.")
    
# ========
# Query Analyzer Interface
# ========
class QueryAnalyzerInterface(ABC):
    """
    Abstract interface for query analyzers.

    Analyzes a query against a refinement framework to determine which aspects
    are already clear vs. which aspects need refinement through user interaction.

    Two analysis modes are supported:
    1. Sequential (dependency-aware): Analyze aspects one-by-one with dependency context
    2. Batch (fast): Analyze all aspects at once without dependency context

    Implementations should provide at least one mode via the abstract method.
    """

    @abstractmethod
    def analyze_aspect(
        self,
        query: str,
        aspect: "RefinementAspect",
        dependency_context: Optional[Dict[str, str]] = None,
        llm_provider: Optional["LLMProviderInterface"] = None,
    ) -> "AspectAnalysisResult":
        """
        Analyze a single aspect to determine if it needs refinement.

        This method enables dependency-aware sequential analysis during initialization.
        Each aspect is analyzed with context from previously analyzed dependencies.

        Args:
            query: The original query to analyze.
            aspect: The specific refinement aspect to evaluate.
            dependency_context: Values from dependency aspects (aspect_id -> value or query reference).
            llm_provider: Optional LLM provider for LLM-based analysis.

        Returns:
            AspectAnalysisResult with:
            - needs_refinement: bool indicating if refinement is needed
            - reason: explanation of why (required for needs_refinement=True, optional otherwise)
        """
        pass
    
    def supports_batch_analysis(self) -> bool:
        """
        Indicates whether the analyzer can perform batch analysis.
        
        Batch analysis is faster (single LLM call) but less accurate since it
        lacks dependency context. Useful for independent aspects or performance-critical scenarios.

        Returns:
            bool: True if batch analysis is available, False otherwise.
        """
        return False
    
    def batch_analyze(
        self,
        query: str,
        refinement_framework: List["RefinementAspect"],
        llm_provider: Optional["LLMProviderInterface"] = None,
    ) -> Dict[str, "AspectAnalysisResult"]:
        """
        Batch analyze all aspects at once (without dependency context).

        This is an optimization for analyzers that can evaluate multiple aspects
        in a single operation. It's faster but less accurate than sequential analysis.

        Default implementation falls back to sequential analysis.

        Args:
            query: The query to analyze.
            refinement_framework: All aspects to consider.
            llm_provider: Optional LLM provider for LLM-based analysis.

        Returns:
            Dictionary mapping aspect IDs to their analysis results.
        """
        # Default: fall back to sequential analysis without dependency context
        results = {}
        for aspect in refinement_framework:
            results[aspect.id] = self.analyze_aspect(
                query, aspect, dependency_context=None, llm_provider=llm_provider
            )
        return results
    

# ===========
# Tracing Interface
# ===========
class TracingProviderInterface(ABC):
    """
    Abstract interface for tracing systems.

    This interface defines the contract for any tracing system integration,
    enabling consistent logging and monitoring of query refinement operations.
    """

    @abstractmethod
    def trace_operation(
        self,
        name: str,
        operation_type: str = "function",
        metadata: Optional[Dict[str, Any]] = None,
        ):
        """
        Context manager for tracing an operation.

        Usage:
            with tracer.trace_operation("operation_name", metadata={"key": "value"}):
                # operation code here   

        Args:
            name (str): The name of the operation being traced.
            operation_type (str): The type of the operation (e.g., "function", "query").
            metadata (Optional[Dict[str, Any]]): Additional metadata to include in the trace.
        
        Returns:
            A context manager for the traced operation.

        Raises:
            NotImplementedError: If the method is not implemented by the subclass.
            Exception: For any errors during the tracing process (implementation-specific).
        """
        pass
        raise NotImplementedError("TracingProviderInterface.trace_operation() must be implemented by subclasses.")

    @abstractmethod
    def log_event(
        self, 
        event_name: str, 
        level: str = "info",
        metadata: Optional[Dict[str, Any]] = None
    ):
        """
        Log a discrete event with optional metadata.

        Args:
            event_name (str): The name of the event to log.
            level (str): The logging level (e.g., "debug", "info", "warning", "error").
            metadata (Optional[Dict[str, Any]]): Additional metadata associated with the event.

        Raises:
            NotImplementedError: If the method is not implemented by the subclass.
            Exception: For any errors during the logging process (implementation-specific).
        """
        pass
        raise NotImplementedError("TracingInterface.log_event() must be implemented by subclasses.")
    
    @abstractmethod
    def is_enabled(self) -> bool:
        """
        Check if tracing is enabled.

        Returns:
            bool: True if tracing is enabled, False otherwise.
        """
        pass
        raise NotImplementedError("TracingInterface.is_enabled() must be implemented by subclasses.")   


# ===========
# Session Storage Interface
# ===========
class SessionStorageInterface(ABC):
    """
    Abstract interface for session persistence.

    Enables stateless API design by providing save/load operations for sessions.
    Implementations can use various backends: Redis, PostgreSQL, File system, etc.
    """

    @abstractmethod
    def save_session(self, session_id: str, session: Any) -> None:
        """
        Persist a refinement session.

        Args:
            session_id: Unique identifier for the session.
            session: The QueryRefinementSession object to save.

        Raises:
            NotImplementedError: If not implemented by subclass.
            Exception: For storage-specific errors (implementation-specific).
        """
        pass

    @abstractmethod
    def load_session(self, session_id: str) -> Any:
        """
        Retrieve a persisted refinement session.

        Args:
            session_id: Unique identifier for the session.

        Returns:
            The QueryRefinementSession object.

        Raises:
            NotImplementedError: If not implemented by subclass.
            KeyError: If session_id doesn't exist.
            Exception: For storage-specific errors (implementation-specific).
        """
        pass

    @abstractmethod
    def delete_session(self, session_id: str) -> None:
        """
        Delete a persisted session.

        Args:
            session_id: Unique identifier for the session.

        Raises:
            NotImplementedError: If not implemented by subclass.
            Exception: For storage-specific errors (implementation-specific).
        """
        pass

    @abstractmethod
    def session_exists(self, session_id: str) -> bool:
        """
        Check if a session exists.

        Args:
            session_id: Unique identifier for the session.

        Returns:
            bool: True if session exists, False otherwise.
        """
        pass


__all__ = [
    # core interfaces
    "LLMProviderInterface",
    "QueryAnalyzerInterface",
    "TracingProviderInterface",
    "SessionStorageInterface",
    # result types
    "LLMCompletionResult",
    "AspectAnalysisResult",
]