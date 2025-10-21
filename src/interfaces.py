"""
Abstract interfaces for the query refinement module.

These interfaces define the contracts for external dependencies, enabling the module to remain independent while allowing flexible integration with different LLM providers, tracing systems, and query analysis approaches.
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Dict, Optional, List

if TYPE_CHECKING:
    from schemas import RefinementDimension

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
    metadata: Dict[str, Any] = None

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

    This interface defines the contract for any query analysis implementation,
    allowing different strategies for analyzing and refining user queries.
    For instance:
    - LLM-based analysis
    - Rule-based analysis
    - Hybrid approaches
    """

    @abstractmethod
    def analyze_query_completeness(
        self,
        query: str,
        schema: List["RefinementDimension"],
        llm_provider: Optional[LLMProviderInterface] = None,
    ) -> List["RefinementDimension"]:
        """
        Analyze the user query in the context of the provided schema to determine which dimensions need refinement.

        Args:
            query (str): The user query to analyze.
            schema (List[RefinementDimension]): List of refinement dimensions to consider.
            llm_provider (Optional[LLMProviderInterface]): An optional LLM provider for analysis.
        
        Returns:
            List[RefinementDimension]: A list of dimensions that require refinement.
            Empty list means no refinement needed.
        
        Raises:
            NotImplementedError: If the method is not implemented by the subclass.
            Exception: For any errors during the analysis process (implementation-specific).
        """
        pass
        raise NotImplementedError("QueryAnalyzerInterface.analyze_query_completeness() must be implemented by subclasses.") 
    
    def supports_llm_analysis(self) -> bool:
        """
        Indicates whether the analyzer supports LLM-based analysis.

        Returns:
            bool: True if LLM-based analysis is supported, False otherwise.
        """
        return False
    

# ===========
# Tracing Interface
# ===========
class TracingInterface(ABC):
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
        raise NotImplementedError("TracingInterface.start_trace() must be implemented by subclasses.")

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


#TODO: Session storage interface

__all__ = [
    # core interfaces
    "LLMProviderInterface",
    "QueryAnalyzerInterface",
    "TracingInterface",
    # result type
    "LLMCompletionResult",
]