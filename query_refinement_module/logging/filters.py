"""
Log filters for context enrichment and PII sanitization.
"""

import logging
import re
from typing import Pattern, Dict

from query_refinement_module.tracing import get_request_id, get_trace_id, get_span_id


class RequestContextFilter(logging.Filter):
    """
    Add request/trace context to all log records.
    
    Automatically adds:
    - request_id (from contextvars)
    - trace_id (from contextvars)
    - span_id (from contextvars)
    """
    
    def filter(self, record: logging.LogRecord) -> bool:
        """Add context to the log record."""
        # Add request/trace IDs from context
        record.request_id = get_request_id() or "--------"
        record.trace_id = get_trace_id()
        record.span_id = get_span_id()
        
        return True


class PIISanitizationFilter(logging.Filter):
    """
    Sanitize Personally Identifiable Information (PII) from log messages.
    
    Redacts:
    - Email addresses
    - Phone numbers
    - Social Security Numbers (SSN)
    - Credit card numbers
    - IP addresses (optional)
    - Authentication tokens
    """
    
    # Compiled regex patterns for PII detection
    PII_PATTERNS: Dict[str, Pattern] = {
        "email": re.compile(
            r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b",
            re.IGNORECASE
        ),
        "ssn": re.compile(
            r"\b\d{3}[-\s]?\d{2}[-\s]?\d{4}\b"
        ),
        "credit_card": re.compile(
            r"\b\d{4}[\s-]?\d{4}[\s-]?\d{4}[\s-]?\d{4}\b"
        ),
        "phone": re.compile(
            r"\b(?:\+?1[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b"
        ),
        "ip_address": re.compile(
            r"\b(?:\d{1,3}\.){3}\d{1,3}\b"
        ),
        "bearer_token": re.compile(
            r"\bBearer\s+[A-Za-z0-9\-._~+/]+=*",
            re.IGNORECASE
        ),
        "api_key": re.compile(
            r"\b(?:api[_-]?key|apikey|access[_-]?token)[\s:=]+['\"]?([A-Za-z0-9\-._~+/]{20,})['\"]?",
            re.IGNORECASE
        ),
    }
    
    def __init__(self, redact_ip: bool = False):
        """
        Initialize the PII sanitization filter.
        
        Args:
            redact_ip: Whether to redact IP addresses (default: False)
        """
        super().__init__()
        self.redact_ip = redact_ip
    
    def filter(self, record: logging.LogRecord) -> bool:
        """Sanitize PII from the log record."""
        # Sanitize the message
        if isinstance(record.msg, str):
            record.msg = self._sanitize_text(record.msg)
        
        # Sanitize args if present
        if record.args:
            if isinstance(record.args, dict):
                record.args = self._sanitize_dict(record.args)
            elif isinstance(record.args, (list, tuple)):
                record.args = tuple(
                    self._sanitize_text(str(arg)) if isinstance(arg, str) else arg
                    for arg in record.args
                )
        
        # Sanitize context if present
        if hasattr(record, "context") and isinstance(record.context, dict):
            record.context = self._sanitize_dict(record.context)
        
        return True
    
    def _sanitize_text(self, text: str) -> str:
        """Sanitize PII from a text string."""
        sanitized = text
        
        for pii_type, pattern in self.PII_PATTERNS.items():
            # Skip IP sanitization if not enabled
            if pii_type == "ip_address" and not self.redact_ip:
                continue
            
            # Special handling for api_key pattern (has capture group)
            if pii_type == "api_key":
                sanitized = pattern.sub(
                    lambda m: m.group(0).replace(m.group(1), "[API_KEY_REDACTED]"),
                    sanitized
                )
            else:
                sanitized = pattern.sub(f"[{pii_type.upper()}_REDACTED]", sanitized)
        
        return sanitized
    
    def _sanitize_dict(self, data: dict) -> dict:
        """Recursively sanitize PII from dictionary values."""
        sanitized = {}
        
        for key, value in data.items():
            if isinstance(value, str):
                sanitized[key] = self._sanitize_text(value)
            elif isinstance(value, dict):
                sanitized[key] = self._sanitize_dict(value)
            elif isinstance(value, (list, tuple)):
                sanitized[key] = [
                    self._sanitize_text(v) if isinstance(v, str) else v
                    for v in value
                ]
            else:
                sanitized[key] = value
        
        return sanitized
