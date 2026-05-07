"""
Request tracing utilities for contextual logging throughout the API lifecycle.

This module provides tools for generating unique request IDs and maintaining
contextual logging state across asynchronous operations. This enables:
- Correlation of log messages across multiple function calls
- Request tracking in distributed systems
- Performance monitoring and debugging
- Audit trail creation
- Distributed tracing with trace_id and span_id

Usage:
    # In an API endpoint
    request_id = generate_request_id()
    set_request_id(request_id)
    logger = get_logger(__name__)
    logger.info("Starting refinement")
    
    # For distributed tracing
    trace_id = generate_trace_id()
    set_trace_id(trace_id)
"""
import uuid
import logging
from typing import Optional
from contextvars import ContextVar


# Context variables for distributed tracing
_request_id_ctx: ContextVar[Optional[str]] = ContextVar('request_id', default=None)
_trace_id_ctx: ContextVar[Optional[str]] = ContextVar('trace_id', default=None)
_span_id_ctx: ContextVar[Optional[str]] = ContextVar('span_id', default=None)
_parent_span_id_ctx: ContextVar[Optional[str]] = ContextVar('parent_span_id', default=None)


def generate_request_id() -> str:
    """
    Generate a unique request ID for tracing operations.
    
    Uses UUID4 for guaranteed uniqueness across distributed systems.
    Format: 8-character hex prefix for readability in logs.
    
    Returns:
        str: Unique request identifier (e.g., 'a1b2c3d4')
    """
    return uuid.uuid4().hex[:8]


def generate_trace_id() -> str:
    """
    Generate a unique trace ID for distributed tracing.
    
    Trace IDs are used to track requests across multiple services
    in a distributed system.
    
    Returns:
        str: Unique trace identifier (UUID format)
    """
    return str(uuid.uuid4())


def set_request_id(request_id: str) -> None:
    """
    Set the current request ID in the context.
    
    This makes the request ID available to all downstream operations
    without explicitly passing it as a parameter.
    
    Args:
        request_id: The request identifier to set
    """
    _request_id_ctx.set(request_id)


def get_request_id() -> Optional[str]:
    """
    Get the current request ID from the context.
    
    Returns:
        The current request ID if set, None otherwise
    """
    return _request_id_ctx.get()


def set_trace_id(trace_id: str) -> None:
    """
    Set the current trace ID in the context.
    
    Args:
        trace_id: The trace identifier to set
    """
    _trace_id_ctx.set(trace_id)


def get_trace_id() -> Optional[str]:
    """
    Get the current trace ID from the context.
    
    Returns:
        The current trace ID if set, None otherwise
    """
    return _trace_id_ctx.get()


def get_span_id() -> Optional[str]:
    """
    Get the current span ID from the context.
    
    Returns:
        The current span ID if set, None otherwise
    """
    return _span_id_ctx.get()


def clear_request_id() -> None:
    """
    Clear the request ID from the context.
    
    Useful for cleanup after request processing completes.
    """
    _request_id_ctx.set(None)


def clear_trace_context() -> None:
    """
    Clear all tracing context (request_id, trace_id, span_id, parent_span_id).
    
    Useful for cleanup after request processing completes.
    """
    _request_id_ctx.set(None)
    _trace_id_ctx.set(None)
    _span_id_ctx.set(None)
    _parent_span_id_ctx.set(None)


class RequestIdFilter(logging.Filter):
    """
    Logging filter that adds request_id to log records.
    
    This filter automatically includes the request ID in every log message,
    enabling correlation of logs across the request lifecycle.
    
    Usage:
        logger = logging.getLogger(__name__)
        logger.addFilter(RequestIdFilter())
    """
    
    def filter(self, record: logging.LogRecord) -> bool:
        """
        Add request_id attribute to the log record.
        
        Args:
            record: The log record to modify
            
        Returns:
            True to allow the record to be logged
        """
        # Get request ID from context, or use explicitly set request_id
        if not hasattr(record, 'request_id'):
            record.request_id = get_request_id() or '-'
        return True


def get_logger(
    name: str, 
    request_id: Optional[str] = None,
    level: Optional[int] = None
) -> logging.LoggerAdapter:
    """
    Get a logger with automatic request ID context.
    
    This returns a LoggerAdapter that automatically includes the request_id
    in all log messages, making it easy to track operations across the system.
    
    Args:
        name: Logger name (typically __name__)
        request_id: Optional request ID (uses context if not provided)
        level: Optional log level to set
        
    Returns:
        LoggerAdapter configured with request_id context
        
    Example:
        logger = get_logger(__name__, request_id="abc123")
        logger.info("Processing started")  # Includes request_id automatically
    """
    logger = logging.getLogger(name)
    
    # Set log level if provided
    if level is not None:
        logger.setLevel(level)
    
    # Add RequestIdFilter if not already present
    if not any(isinstance(f, RequestIdFilter) for f in logger.filters):
        logger.addFilter(RequestIdFilter())
    
    # Determine which request_id to use
    context_request_id = request_id or get_request_id() or '-'
    
    # Return adapter with extra context
    return logging.LoggerAdapter(logger, {'request_id': context_request_id})


def log_operation(
    logger: logging.LoggerAdapter,
    operation: str,
    **kwargs
) -> None:
    """
    Log an operation with structured metadata.
    
    Provides consistent formatting for operation logging across the codebase.
    
    Args:
        logger: Logger instance
        operation: Name of the operation (e.g., 'session_save', 'llm_call')
        **kwargs: Additional metadata to log
        
    Example:
        log_operation(
            logger, 
            'llm_call',
            provider='openai',
            model='gpt-4',
            tokens=150
        )
    """
    metadata_str = ', '.join(f"{k}={v}" for k, v in kwargs.items())
    logger.info(f"Operation: {operation} | {metadata_str}")


class OperationTimer:
    """
    Context manager for timing operations with automatic logging.
    
    Usage:
        with OperationTimer(logger, "llm_call") as timer:
            result = call_llm()
        # Automatically logs duration when context exits
    """
    
    def __init__(
        self, 
        logger: logging.LoggerAdapter, 
        operation_name: str,
        **metadata
    ):
        """
        Initialize timer.
        
        Args:
            logger: Logger instance for recording duration
            operation_name: Name of the operation being timed
            **metadata: Additional metadata to log
        """
        self.logger = logger
        self.operation_name = operation_name
        self.metadata = metadata
        self.start_time = None
        self.duration = None
        
    def __enter__(self):
        """Start timing."""
        import time
        self.start_time = time.time()
        self.logger.info(f"Starting: {self.operation_name}")
        return self
    
    def __exit__(self, exc_type, exc_val, _exc_tb):
        """
        Stop timing and log duration.
        
        Args:
            exc_type: Exception type if raised
            exc_val: Exception value if raised
            _exc_tb: Exception traceback if raised (unused)
        """
        import time
        self.duration = time.time() - self.start_time
        
        # Build metadata string
        metadata = {**self.metadata, 'duration_seconds': f"{self.duration:.3f}"}
        if exc_type:
            metadata['status'] = 'failed'
            metadata['error'] = str(exc_val)
        else:
            metadata['status'] = 'completed'
        
        metadata_str = ', '.join(f"{k}={v}" for k, v in metadata.items())
        log_level = logging.ERROR if exc_type else logging.INFO
        self.logger.log(
            log_level,
            f"Completed: {self.operation_name} | {metadata_str}"
        )
        
        # Don't suppress exceptions
        return False
