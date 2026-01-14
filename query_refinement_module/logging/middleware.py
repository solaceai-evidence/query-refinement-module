"""
Request logging middleware for FastAPI.
"""

import logging
import time
from typing import Callable

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

from query_refinement_module.tracing import (
    generate_request_id,
    set_request_id,
    get_request_id,
    generate_trace_id,
    set_trace_id,
    get_trace_id,
)

logger = logging.getLogger(__name__)


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """
    Middleware to log all HTTP requests and responses.
    
    Features:
    - Generates or extracts request_id from X-Request-ID header
    - Generates trace_id for distributed tracing
    - Logs request start with method, path, query params (sanitized)
    - Times request execution
    - Logs response with status code, duration, size
    - Adds X-Request-ID and X-Trace-ID headers to response
    """
    
    def __init__(
        self,
        app,
        log_request_body: bool = False,
        log_response_body: bool = False,
    ):
        """
        Initialize the request logging middleware.
        
        Args:
            app: FastAPI application
            log_request_body: Whether to log request bodies (default: False for privacy)
            log_response_body: Whether to log response bodies (default: False for performance)
        """
        super().__init__(app)
        self.log_request_body = log_request_body
        self.log_response_body = log_response_body
    
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        """Process the request and add logging."""
        # Generate or extract request ID
        request_id = request.headers.get("X-Request-ID")
        if not request_id:
            request_id = generate_request_id()
        set_request_id(request_id)
        
        # Generate trace ID for distributed tracing
        trace_id = generate_trace_id()
        set_trace_id(trace_id)
        
        # Get user info if available (from auth)
        user_id = None
        if hasattr(request.state, "user"):
            user_id = getattr(request.state.user, "id", None)
        
        # Start timing
        start_time = time.time()
        
        # Log request start
        self._log_request_start(request, user_id)
        
        # Process request
        try:
            response = await call_next(request)
        except Exception as exc:
            # Log the exception
            duration_ms = (time.time() - start_time) * 1000
            logger.error(
                "Request failed with exception",
                exc_info=exc,
                extra={
                    "user_id": user_id,
                    "context": {
                        "method": request.method,
                        "path": request.url.path,
                        "duration_ms": round(duration_ms, 2),
                    }
                }
            )
            raise
        
        # Calculate duration
        duration_ms = (time.time() - start_time) * 1000
        
        # Add request/trace IDs to response headers
        response.headers["X-Request-ID"] = request_id
        response.headers["X-Trace-ID"] = trace_id
        
        # Log response
        self._log_request_end(request, response, duration_ms, user_id)
        
        return response
    
    def _log_request_start(self, request: Request, user_id: Optional[int]) -> None:
        """Log the start of a request."""
        # Sanitize query parameters (remove potential tokens/passwords)
        query_params = dict(request.query_params)
        sensitive_params = {"password", "token", "api_key", "secret", "authorization"}
        sanitized_params = {
            k: "[REDACTED]" if k.lower() in sensitive_params else v
            for k, v in query_params.items()
        }
        
        logger.info(
            f"Request started: {request.method} {request.url.path}",
            extra={
                "user_id": user_id,
                "context": {
                    "method": request.method,
                    "path": request.url.path,
                    "query_params": sanitized_params,
                    "client_ip": request.client.host if request.client else None,
                    "user_agent": request.headers.get("user-agent"),
                }
            }
        )
    
    def _log_request_end(
        self,
        request: Request,
        response: Response,
        duration_ms: float,
        user_id: Optional[int]
    ) -> None:
        """Log the end of a request."""
        # Determine log level based on status code
        if response.status_code >= 500:
            log_level = logging.ERROR
            message = f"Request failed: {request.method} {request.url.path}"
        elif response.status_code >= 400:
            log_level = logging.WARNING
            message = f"Request error: {request.method} {request.url.path}"
        else:
            log_level = logging.INFO
            message = f"Request completed: {request.method} {request.url.path}"
        
        # Get response size from Content-Length header
        response_size = response.headers.get("content-length")
        
        logger.log(
            log_level,
            message,
            extra={
                "user_id": user_id,
                "context": {
                    "method": request.method,
                    "path": request.url.path,
                    "status_code": response.status_code,
                    "duration_ms": round(duration_ms, 2),
                    "response_size_bytes": int(response_size) if response_size else None,
                }
            }
        )
        
        # Warn if request is slow (>5 seconds)
        if duration_ms > 5000:
            logger.warning(
                f"Slow request detected: {request.method} {request.url.path}",
                extra={
                    "user_id": user_id,
                    "context": {
                        "duration_ms": round(duration_ms, 2),
                        "threshold_ms": 5000,
                    }
                }
            )
