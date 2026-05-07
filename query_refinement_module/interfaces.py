"""
Abstract interfaces for the query refinement module.

These interfaces define the contracts for external dependencies, enabling the module to remain independent while allowing flexible integration with different LLM providers, tracing systems, and query analysis approaches.
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Dict, Optional, List, Union, Type

if TYPE_CHECKING:
    from .schema import RefinementAspect
    from pydantic import BaseModel

# ========
# Rate Limiting Types
# ========
@dataclass
class RateLimitConfig:
    """
    Configuration for LLM provider rate limits

    Defines the rate limits for a specific LLM provider or model integration.
    Used by rate limiters to enforce appropriate usage policies.

    Attributes:
        requests_per_minute: Maximum number of requests allowed per minute (0 = unlimited).
        tokens_per_minute: Maximum number of tokens allowed per minute (None = unlimited,  not enforced).
        max_concurrent_requests: Maximum number of concurrent requests allowed (0 = unlimited).
        adaptive_backoff: Whether to use adaptive backoff on rate limit errors based on 429 responses.
        adaptive_decrease_factor: Factor to decrease limits on rate limit errors (e.g., 0.8 = reduce by 20%).
        adaptive_increase_factor: Factor to gradually increase limits during recovery (e.g., 1.05 = increase by 5%).
        adaptive_increase_interval: Time interval (seconds) to increase limits during recovery.
    """
    requests_per_minute: int = 0
    tokens_per_minute: Optional[int] = None
    max_concurrent_requests: int = 0
    adaptive_backoff: bool = False
    adaptive_decrease_factor: float = 0.8
    adaptive_increase_factor: float = 1.05
    adaptive_increase_interval: int = 60 # Recover adjustment every 60 seconds

    def __post_init__(self):
        """Validate rate limit configuration values."""
        if self.requests_per_minute < 0:
            raise ValueError("requests_per_minute must be >= 0")
        if self.tokens_per_minute is not None and self.tokens_per_minute < 0:
            raise ValueError("tokens_per_minute must be >= 0 or None")
        if self.max_concurrent_requests < 0:
            raise ValueError("max_concurrent_requests must be >= 0")
        if not (0.0 < self.adaptive_decrease_factor < 1.0):
            raise ValueError("adaptive_decrease_factor must be between 0.0 and 1.0")
        if self.adaptive_increase_factor <= 1.0:
            raise ValueError("adaptive_increase_factor must be greater than 1.0")
        if self.adaptive_increase_interval <= 0:
            raise ValueError("adaptive_increase_interval must be greater than 0 seconds")
        
    @classmethod
    def unlimited(cls) -> "RateLimitConfig":
        """Create a RateLimitConfig with no limits for local models."""
        return cls(
            requests_per_minute=0,
            tokens_per_minute=None,
            max_concurrent_requests=0,
            adaptive_backoff=False,
        )
    
class RateLimitExceeded(Exception):
    """
    Exception raised when rate limit is exceeded.
    
    Attributes:
        retry_after: Seconds to wait before retrying (from Retry-After header or calculated).
        limit_type: Type of limit exceeded - "requests", "tokens", or "concurrent".
        scope: Scope of the limit - "global" or "user".
        user_id: User identifier if per-user limit was exceeded.
        metadata: Additional provider-specific information.
    """
    
    def __init__(
        self,
        message: str,
        retry_after: Optional[int] = None,
        limit_type: str = "requests",
        scope: str = "global",
        user_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None
    ):
        super().__init__(message)
        self.retry_after = retry_after
        self.limit_type = limit_type
        self.scope = scope
        self.user_id = user_id
        self.metadata = metadata or {}
    
    def __str__(self) -> str:
        base_msg = super().__str__()
        details = []
        if self.retry_after:
            details.append(f"retry_after={self.retry_after}s")
        if self.scope:
            details.append(f"scope={self.scope}")
        if self.user_id:
            details.append(f"user_id={self.user_id}")
        
        if details:
            return f"{base_msg} ({', '.join(details)})"
        return base_msg

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
        user_prompt: str = "",
        system_prompt: Optional[str] = None,
        model: Optional[str] = None,
        temperature: float = 0.0,
        max_tokens: Optional[int] = None,
        messages: Optional[List[Dict[str, str]]] = None,
        response_format: Optional[Union[Dict[str, Any], Type["BaseModel"]]] = None,
        **kwargs,
    ) -> LLMCompletionResult:
        """
        Generate a completion from the LLM based on the provided prompt.

        Args:
            user_prompt (str): The input prompt to send to the LLM (used if messages not provided).
            system_prompt (Optional[str]): An optional system prompt to guide the LLM.
            model (Optional[str]): The model identifier to use for the completion.
            temperature (float): Sampling temperature for the completion.
            max_tokens (Optional[int]): Maximum number of tokens to generate.
            messages (Optional[List[Dict[str, str]]]): Full conversation history with roles.
                If provided, takes precedence over user_prompt/system_prompt.
                Format: [{"role": "system"|"user"|"assistant", "content": str}, ...]
            response_format (Optional[Union[Dict, Type[BaseModel]]]): Structured output format.
                Can be:
                - {"type": "json_object"} for generic JSON
                - {"type": "json_schema", "json_schema": {...}} for strict schema (OpenAI)
                - Pydantic BaseModel class (auto-converted to provider-specific format)
            **kwargs: Additional provider-specific parameters.

        Returns:
            LLMCompletionResult: The result of the LLM completion.
                If response_format is a Pydantic model and provider supports structured outputs,
                result.context may contain the parsed object instead of raw text.
        
        Raises:
            NotImplementedError: If the method is not implemented by the subclass.
            RateLimitExceeded: If the request exceeds rate limits (provider should raise this).
            Exception: For any errors during the completion process (implementation-specific).
        """
        raise NotImplementedError("LLMProviderInterface.complete() must be implemented by subclasses.")
    
    async def complete_async(
        self,
        user_prompt: str = "",
        system_prompt: Optional[str] = None,
        model: Optional[str] = None,
        temperature: float = 0.0,
        max_tokens: Optional[int] = None,
        messages: Optional[List[Dict[str, str]]] = None,
        response_format: Optional[Union[Dict[str, Any], Type["BaseModel"]]] = None,
        **kwargs,
    ) -> LLMCompletionResult:
        """
        Generate a completion from the LLM asynchronously.
        
        Default implementation raises NotImplementedError. Providers should
        override this for native async support.

        Args:
            user_prompt (str): The input prompt to send to the LLM (used if messages not provided).
            system_prompt (Optional[str]): An optional system prompt to guide the LLM.
            model (Optional[str]): The model identifier to use for the completion.
            temperature (float): Sampling temperature for the completion.
            max_tokens (Optional[int]): Maximum number of tokens to generate.
            messages (Optional[List[Dict[str, str]]]): Full conversation history with roles.
                If provided, takes precedence over user_prompt/system_prompt.
                Format: [{"role": "system"|"user"|"assistant", "content": str}, ...]
            response_format (Optional[Union[Dict, Type[BaseModel]]]): Structured output format.
                Can be:
                - {"type": "json_object"} for generic JSON
                - {"type": "json_schema", "json_schema": {...}} for strict schema (OpenAI)
                - Pydantic BaseModel class (auto-converted to provider-specific format)
            **kwargs: Additional provider-specific parameters.

        Returns:
            LLMCompletionResult: The result of the LLM completion.
                If response_format is a Pydantic model and provider supports structured outputs,
                result.context may contain the parsed object instead of raw text.
        
        Raises:
            NotImplementedError: If the provider doesn't support async operations.
            RateLimitExceeded: If the request exceeds rate limits.
            Exception: For any errors during the completion process.
        """
        raise NotImplementedError(
            f"{self.__class__.__name__} does not implement complete_async(). "
            "Use complete() or implement async support."
        )
    
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
    
    def get_rate_limits(self, model: Optional[str] = None) -> RateLimitConfig:
        """
        Retrieve the rate limit configuration for the provider or specific model.

        Implementations should return provider/model-specific rate limits.

        Args:
            model (Optional[str]): The model identifier to get limits for (None for provider-wide limits).
        
        Returns:
            RateLimitConfig with provider/model rate limits.
            Default implementation returns unlimited (suitable for local models)
        """
        return RateLimitConfig.unlimited()
    

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

    def log_metric(
    self,
    metric_name: str,
    value: float,
    unit: str = "",
    metadata: Optional[Dict[str, Any]] = None
    ):
        """
        Log a numeric metric for monitoring and observability.
        
        Used for tracking parallel execution performance, rate limiting, cache hits, etc.
        
        Args:
            metric_name: Name of the metric (e.g., "parallel.latency_reduction").
            value: Numeric value of the metric.
            unit: Unit of measurement (e.g., "seconds", "percent", "count").
            metadata: Additional context about the metric.
        
        Default implementation does nothing (optional feature).
        Implementations can override to send metrics to monitoring systems.
        """
        pass  # Optional: default no-op allows backward compatibility

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
    "TracingProviderInterface",
    "SessionStorageInterface",
    # result types
    "LLMCompletionResult",
    # rate limiting
    "RateLimitConfig", 
    "RateLimitExceeded",
]