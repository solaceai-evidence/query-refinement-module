"""
Log formatters for structured logging.
"""

import json
import logging
import traceback
from datetime import datetime
from typing import Any, Dict


class JSONFormatter(logging.Formatter):
    """
    Format log records as JSON for production environments.
    
    Output includes:
    - timestamp (ISO 8601)
    - level
    - logger name
    - message
    - request_id, trace_id, span_id (if available)
    - user_id, session_id, query_id (if available)
    - exception info (if available)
    - extra context fields
    """
    
    def format(self, record: logging.LogRecord) -> str:
        """Format the log record as a JSON string."""
        log_data: Dict[str, Any] = {
            "timestamp": datetime.utcfromtimestamp(record.created).isoformat() + "Z",
            "level": record.levelname,
            "logger": record.name,
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno,
            "message": record.getMessage(),
        }
        
        # Add request/trace context if available
        if hasattr(record, "request_id"):
            log_data["request_id"] = record.request_id
        if hasattr(record, "trace_id"):
            log_data["trace_id"] = record.trace_id
        if hasattr(record, "span_id"):
            log_data["span_id"] = record.span_id
        if hasattr(record, "parent_span_id"):
            log_data["parent_span_id"] = record.parent_span_id
            
        # Add user/session context if available
        if hasattr(record, "user_id"):
            log_data["user_id"] = record.user_id
        if hasattr(record, "session_id"):
            log_data["session_id"] = record.session_id
        if hasattr(record, "query_id"):
            log_data["query_id"] = record.query_id
            
        # Add any extra context fields
        if hasattr(record, "context") and isinstance(record.context, dict):
            log_data["context"] = record.context
            
        # Add exception info if present
        if record.exc_info:
            log_data["exception"] = {
                "type": record.exc_info[0].__name__ if record.exc_info[0] else None,
                "message": str(record.exc_info[1]) if record.exc_info[1] else None,
                "traceback": self.formatException(record.exc_info),
            }
            
        # Add stack info if present
        if record.stack_info:
            log_data["stack_info"] = record.stack_info
            
        return json.dumps(log_data)


class StructuredTextFormatter(logging.Formatter):
    """
    Format log records as structured text for development environments.
    
    Format: timestamp | level | request_id | user_id | logger:function | message | context
    """
    
    def format(self, record: logging.LogRecord) -> str:
        """Format the log record as structured text."""
        # Build the structured parts
        parts = [
            datetime.utcfromtimestamp(record.created).strftime("%Y-%m-%d %H:%M:%S.%f")[:-3],
            f"{record.levelname:8s}",
        ]
        
        # Add request_id if available
        if hasattr(record, "request_id"):
            parts.append(f"req:{record.request_id}")
        else:
            parts.append("req:--------")
            
        # Add user_id if available
        if hasattr(record, "user_id"):
            parts.append(f"user:{record.user_id}")
            
        # Add logger and function
        parts.append(f"{record.name}:{record.funcName}")
        
        # Add the message
        parts.append(record.getMessage())
        
        # Add context if available
        if hasattr(record, "context") and isinstance(record.context, dict):
            parts.append(json.dumps(record.context))
            
        formatted = " | ".join(parts)
        
        # Add exception info if present
        if record.exc_info:
            formatted += "\n" + self.formatException(record.exc_info)
            
        return formatted
