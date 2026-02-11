"""
Rate limiting middleware for the API.
"""
import time
from collections import defaultdict
from typing import Callable, Optional

try:
    import redis
    REDIS_AVAILABLE = True
except ImportError:  # pragma: no cover - optional dependency
    redis = None
    REDIS_AVAILABLE = False
try:
    from jose import JWTError, jwt
    JOSE_AVAILABLE = True
except ImportError:  # pragma: no cover - optional dependency
    JWTError = Exception  # type: ignore
    jwt = None  # type: ignore
    JOSE_AVAILABLE = False

from fastapi import Request, status
from fastapi.responses import JSONResponse
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
    
    def is_allowed(self, identifier: str) -> tuple[bool, int, int]:
        """
        Check if request is allowed and return (allowed, retry_after_seconds, remaining).
        
        Args:
            identifier: Unique identifier for the client (e.g., IP address)
        
        Returns:
            Tuple of (is_allowed, retry_after_seconds, remaining)
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
            remaining = self.requests_per_minute - len(self.requests[identifier])
            return True, 0, remaining
        
        # Calculate retry_after
        oldest_request = min(self.requests[identifier])
        retry_after = int(oldest_request + 60 - now) + 1
        
        return False, retry_after, 0


class RedisRateLimiter:
    """
    Redis-backed rate limiter for multi-instance deployments.
    Uses a fixed 60-second window per client identifier.
    """

    def __init__(self, requests_per_minute: int, redis_url: str, key_prefix: str = "qr:ratelimit"):
        if not REDIS_AVAILABLE:
            raise RuntimeError("redis package is required for RedisRateLimiter")
        self.requests_per_minute = requests_per_minute
        self.redis = redis.Redis.from_url(redis_url)
        self.key_prefix = key_prefix

    def _key(self, identifier: str, window: int) -> str:
        return f"{self.key_prefix}:api:{identifier}:{window}"

    def is_allowed(self, identifier: str) -> tuple[bool, int, int]:
        now = time.time()
        window = int(now // 60)
        key = self._key(identifier, window)

        count = self.redis.incr(key)
        if count == 1:
            self.redis.expire(key, 120)

        if count > self.requests_per_minute:
            retry_after = 60 - int(now % 60)
            return False, max(retry_after, 1), 0

        remaining = max(self.requests_per_minute - int(count), 0)
        return True, 0, remaining


class RateLimitMiddleware(BaseHTTPMiddleware):
    """
    Middleware to apply rate limiting to all requests.
    """
    def __init__(
        self,
        app,
        requests_per_minute: int = 60,
        per_user_requests_per_minute: int = 0,
        exempt_paths: Optional[list[str]] = None,
        backend: str = "memory",
        redis_url: Optional[str] = None,
        redis_key_prefix: str = "qr:ratelimit",
        use_user_identifier: bool = True,
        secret_key: Optional[str] = None,
        algorithm: Optional[str] = None,
    ):
        super().__init__(app)
        self.requests_per_minute = requests_per_minute
        self.per_user_requests_per_minute = per_user_requests_per_minute
        self.backend = backend
        self.rate_limiter = self._build_limiter(
            requests_per_minute,
            backend,
            redis_url,
            redis_key_prefix,
        )
        self.user_rate_limiter = None
        if per_user_requests_per_minute > 0:
            self.user_rate_limiter = self._build_limiter(
                per_user_requests_per_minute,
                backend,
                redis_url,
                f"{redis_key_prefix}:user",
            )
        self.exempt_paths = exempt_paths or ["/docs", "/redoc", "/openapi.json", "/health"]
        self.use_user_identifier = use_user_identifier
        self.secret_key = secret_key
        self.algorithm = algorithm

    def _build_limiter(
        self,
        requests_per_minute: int,
        backend: str,
        redis_url: Optional[str],
        redis_key_prefix: str,
    ):
        if backend == "redis" and redis_url:
            try:
                return RedisRateLimiter(requests_per_minute, redis_url, redis_key_prefix)
            except Exception:
                return RateLimiter(requests_per_minute)
        return RateLimiter(requests_per_minute)

    def _get_client_identifier(self, request: Request) -> str:
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            return forwarded.split(",")[0].strip()
        real_ip = request.headers.get("x-real-ip")
        if real_ip:
            return real_ip.strip()
        return request.client.host if request.client else "unknown"

    def _get_user_identifier(self, request: Request) -> Optional[str]:
        if not self.use_user_identifier:
            return None
        if not JOSE_AVAILABLE or not self.secret_key or not self.algorithm:
            return None
        auth_header = request.headers.get("authorization", "")
        if not auth_header.lower().startswith("bearer "):
            return None
        token = auth_header.split(" ", 1)[1].strip()
        if not token:
            return None
        try:
            payload = jwt.decode(token, self.secret_key, algorithms=[self.algorithm])
        except JWTError:
            return None
        subject = payload.get("sub")
        if not subject:
            return None
        return f"user:{subject}"
    
    async def dispatch(self, request: Request, call_next: Callable):
        # Skip rate limiting for exempt paths
        if any(request.url.path.startswith(path) for path in self.exempt_paths):
            return await call_next(request)
        
        identifier = self._get_client_identifier(request)
        user_identifier = self._get_user_identifier(request) or identifier
        
        # Check global rate limit
        allowed, retry_after, remaining = self.rate_limiter.is_allowed("global")
        
        if not allowed:
            return JSONResponse(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                content={"detail": f"Rate limit exceeded. Try again in {retry_after} seconds."},
                headers={"Retry-After": str(retry_after)}
            )

        user_remaining = None
        if self.user_rate_limiter:
            allowed, retry_after, user_remaining = self.user_rate_limiter.is_allowed(user_identifier)
            if not allowed:
                return JSONResponse(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    content={"detail": f"Rate limit exceeded. Try again in {retry_after} seconds."},
                    headers={"Retry-After": str(retry_after)}
                )
        
        response = await call_next(request)
        
        # Add rate limit headers
        response.headers["X-RateLimit-Global-Limit"] = str(self.requests_per_minute)
        response.headers["X-RateLimit-Global-Remaining"] = str(remaining)
        if self.user_rate_limiter and user_remaining is not None:
            response.headers["X-RateLimit-User-Limit"] = str(self.per_user_requests_per_minute)
            response.headers["X-RateLimit-User-Remaining"] = str(user_remaining)
        
        return response
