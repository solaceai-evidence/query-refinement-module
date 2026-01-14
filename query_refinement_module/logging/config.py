"""
Centralized logging configuration for the query refinement module.
"""

import logging
import sys
from pathlib import Path
from typing import Optional

from query_refinement_module.logging.formatters import (
    JSONFormatter,
    StructuredTextFormatter,
)
from query_refinement_module.logging.filters import (
    PIISanitizationFilter,
    RequestContextFilter,
)


def configure_logging(
    level: str = "INFO",
    log_format: str = "text",
    log_file: Optional[str] = None,
    sanitize_pii: bool = True,
    redact_ip: bool = False,
) -> None:
    """
    Configure application-wide logging.
    
    Args:
        level: Log level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        log_format: Output format ("json" or "text")
        log_file: Optional file path for log output
        sanitize_pii: Whether to sanitize PII from logs (default: True)
        redact_ip: Whether to redact IP addresses (default: False)
    """
    # Get root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, level.upper(), logging.INFO))
    
    # Clear existing handlers
    root_logger.handlers.clear()
    
    # Choose formatter based on format type
    if log_format == "json":
        formatter = JSONFormatter()
    else:
        formatter = StructuredTextFormatter()
    
    # Configure stdout handler
    stdout_handler = logging.StreamHandler(sys.stdout)
    stdout_handler.setLevel(logging.DEBUG)
    stdout_handler.setFormatter(formatter)
    
    # Add filters
    stdout_handler.addFilter(RequestContextFilter())
    if sanitize_pii:
        stdout_handler.addFilter(PIISanitizationFilter(redact_ip=redact_ip))
    
    root_logger.addHandler(stdout_handler)
    
    # Configure file handler if specified
    if log_file:
        log_path = Path(log_file)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        
        file_handler = logging.FileHandler(log_path, encoding="utf-8")
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(formatter)
        file_handler.addFilter(RequestContextFilter())
        if sanitize_pii:
            file_handler.addFilter(PIISanitizationFilter(redact_ip=redact_ip))
        
        root_logger.addHandler(file_handler)
    
    # Configure third-party loggers
    _configure_third_party_loggers()
    
    logging.info(
        "Logging configured",
        extra={
            "context": {
                "level": level,
                "format": log_format,
                "file": log_file,
                "sanitize_pii": sanitize_pii,
            }
        }
    )


def _configure_third_party_loggers() -> None:
    """Configure log levels for third-party libraries."""
    # Reduce noise from third-party libraries
    logging.getLogger("uvicorn").setLevel(logging.INFO)
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("uvicorn.error").setLevel(logging.INFO)
    logging.getLogger("fastapi").setLevel(logging.INFO)
    logging.getLogger("sqlalchemy").setLevel(logging.WARNING)
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
    logging.getLogger("redis").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("litellm").setLevel(logging.INFO)


def get_logger(name: str) -> logging.Logger:
    """
    Get a logger instance with the specified name.
    
    Args:
        name: Logger name (typically __name__ of the module)
    
    Returns:
        Configured logger instance
    """
    return logging.getLogger(name)
