"""
Environment-specific logging configuration.

Supports different logging formats and levels based on environment:
- Development: Text format with DEBUG level
- Staging: Text format with INFO level
- Production: JSON format with INFO level (for log aggregation)

Usage:
    from query_refinement_module.api.logging_config import setup_logging
    setup_logging()
"""
import logging
import sys
from typing import Optional
from pythonjsonlogger import jsonlogger

from query_refinement_module.api.config import get_settings


class CustomJsonFormatter(jsonlogger.JsonFormatter):
    """
    Custom JSON formatter that adds standard fields to all log records.
    
    Includes:
    - timestamp: ISO 8601 formatted timestamp
    - level: Log level (INFO, ERROR, etc.)
    - logger: Logger name
    - message: Log message
    - request_id: Request ID (if available from context)
    - Additional fields from extra parameter
    """
    
    def add_fields(self, log_record, record, message_dict):
        """Add custom fields to the log record."""
        super().add_fields(log_record, record, message_dict)
        
        # Add standard fields
        log_record['timestamp'] = record.created
        log_record['level'] = record.levelname
        log_record['logger'] = record.name
        log_record['module'] = record.module
        log_record['function'] = record.funcName
        log_record['line'] = record.lineno
        
        # Add request_id if available
        if hasattr(record, 'request_id'):
            log_record['request_id'] = record.request_id
        
        # Move message to standard field
        if 'message' not in log_record:
            log_record['message'] = record.getMessage()


def setup_logging(
    environment: Optional[str] = None,
    log_level: Optional[str] = None,
    log_format: Optional[str] = None,
    log_file: Optional[str] = None
) -> None:
    """
    Configure application logging based on environment.
    
    Args:
        environment: Environment name (development, staging, production).
                    If None, uses settings.environment
        log_level: Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL).
                  If None, uses settings.log_level
        log_format: Log format (text or json). If None, uses settings.log_format
        log_file: Path to log file. If None, logs to stdout only
    
    Example:
        # Use environment settings
        setup_logging()
        
        # Override for testing
        setup_logging(environment="development", log_level="DEBUG", log_format="text")
    """
    settings = get_settings()
    
    # Use provided values or fall back to settings
    environment = environment or settings.environment
    log_level = log_level or settings.log_level
    log_format = log_format or settings.log_format
    log_file = log_file or settings.log_file
    
    # Convert log level string to logging constant
    numeric_level = getattr(logging, log_level.upper(), logging.INFO)
    
    # Create formatters
    if log_format.lower() == "json":
        # JSON formatter for production (structured logging)
        formatter = CustomJsonFormatter(
            '%(timestamp)s %(level)s %(name)s %(message)s',
            timestamp=True
        )
    else:
        # Text formatter for development (human-readable)
        formatter = logging.Formatter(
            fmt='%(asctime)s | %(levelname)-8s | %(name)-30s | %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
    
    # Configure root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(numeric_level)
    
    # Remove existing handlers
    root_logger.handlers = []
    
    # Add stdout handler
    stdout_handler = logging.StreamHandler(sys.stdout)
    stdout_handler.setLevel(numeric_level)
    stdout_handler.setFormatter(formatter)
    root_logger.addHandler(stdout_handler)
    
    # Add file handler if specified
    if log_file:
        try:
            file_handler = logging.FileHandler(log_file, encoding='utf-8')
            file_handler.setLevel(numeric_level)
            file_handler.setFormatter(formatter)
            root_logger.addHandler(file_handler)
            root_logger.info(f"Logging to file: {log_file}")
        except Exception as e:
            root_logger.error(f"Failed to create log file handler: {e}")
    
    # Set levels for specific loggers (reduce noise from dependencies)
    logging.getLogger("uvicorn").setLevel(logging.INFO)
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)  # Reduce access log noise
    logging.getLogger("fastapi").setLevel(logging.INFO)
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING if environment == "production" else logging.INFO)
    logging.getLogger("redis").setLevel(logging.WARNING)
    logging.getLogger("litellm").setLevel(logging.INFO)
    
    # Log configuration
    root_logger.info(
        f"Logging configured | environment={environment}, level={log_level}, "
        f"format={log_format}, file={log_file or 'stdout'}"
    )


def get_logger(name: str, request_id: Optional[str] = None) -> logging.LoggerAdapter:
    """
    Get a logger with optional request ID context.
    
    This is a convenience wrapper around the tracing module's get_logger
    that provides consistent logging throughout the application.
    
    Args:
        name: Logger name (typically __name__)
        request_id: Optional request ID for correlation
        
    Returns:
        LoggerAdapter with request_id context
    """
    from query_refinement_module.tracing import get_logger as tracing_get_logger
    return tracing_get_logger(name, request_id=request_id)
