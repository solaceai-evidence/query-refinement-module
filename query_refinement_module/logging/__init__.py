"""
Production-ready logging infrastructure for query refinement module.

This package provides:
- Structured logging (JSON/text formats)
- PII sanitization
- Request/trace context enrichment
- Production-ready handlers
"""

from query_refinement_module.logging.config import (
    configure_logging,
    get_logger,
)
from query_refinement_module.logging.formatters import (
    JSONFormatter,
    StructuredTextFormatter,
)
from query_refinement_module.logging.filters import (
    PIISanitizationFilter,
    RequestContextFilter,
)

__all__ = [
    "configure_logging",
    "get_logger",
    "JSONFormatter",
    "StructuredTextFormatter",
    "PIISanitizationFilter",
    "RequestContextFilter",
]
