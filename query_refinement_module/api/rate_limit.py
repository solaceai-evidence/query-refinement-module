"""
Simple rate limiting middleware for the API.
"""
import time
from collections import defaultdict
from typing import Callable
from fastapi import Request, HTTPException, status
from starlette.middleware.base import BaseHTTPMiddleware


class RateLimiter:
    """
    Simple in-memory rate limiter.
    
    Note: This is suitable for single-instance deployments.
    For production with multiple instances, use Redis or similar.
    """
    def __init__(self, requests_per_minute: int = 60):
        self.requests_per_minute = requests_per_minute
        self.requests: defaultdict[str, list[float]] = defaultdict(list)
    
    def is_allowed(self, identifier: str) -> tuple[bool, int]:
        """
        Check if request is allowed and return (allowed, retry_after_seconds).
        
        Args:
            identifier: Unique identifier for the client (e.g., IP address)
        
        Returns:
            Tuple of (is_allowed, retry_after_seconds)
        """
        now = time.time()
        minute_ago = now - 60
        
        # Clean old requests
        self.requests[identifier] = [
            req_time for req_time in self.requests[identifier]
            if req_time > minute_ago
        ]
        
        # Check if under limit
        if len(self.requests[identifier]) < self.requests_per_minute:
            self.requests[identifier].append(now)
            return True, 0
        
        # Calculate retry_after
        oldest_request = min(self.requests[identifier])
        retry_after = int(oldest_request + 60 - now) + 1
        
        return False, retry_after


class RateLimitMiddleware(BaseHTTPMiddleware):
    """
    Middleware to apply rate limiting to all requests.
    """
    def __init__(self, app, requests_per_minute: int = 60, exempt_paths: list[str] = None):
        super().__init__(app)
        self.rate_limiter = RateLimiter(requests_per_minute)
        self.exempt_paths = exempt_paths or ["/docs", "/redoc", "/openapi.json", "/health"]
    
    async def dispatch(self, request: Request, call_next: Callable):
        # Skip rate limiting for exempt paths
        if any(request.url.path.startswith(path) for path in self.exempt_paths):
            return await call_next(request)
        
        # Get client identifier (IP address)
        client_ip = request.client.host if request.client else "unknown"
        
        # Check if user is authenticated and use user ID if available
        # For now, we'll use IP. In production, combine IP + user_id
        identifier = client_ip
        
        # Check rate limit
        allowed, retry_after = self.rate_limiter.is_allowed(identifier)
        
        if not allowed:
            return HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=f"Rate limit exceeded. Try again in {retry_after} seconds.",
                headers={"Retry-After": str(retry_after)}
            )
        
        response = await call_next(request)
        
        # Add rate limit headers
        response.headers["X-RateLimit-Limit"] = str(self.rate_limiter.requests_per_minute)
        response.headers["X-RateLimit-Remaining"] = str(
            self.rate_limiter.requests_per_minute - len(self.rate_limiter.requests[identifier])
        )
        
        return response
