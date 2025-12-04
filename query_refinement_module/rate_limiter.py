"""
Rate limiting infrastructure for LLM API calls.

Provides multiple rate limiter implementations for controlling API usage:
- TokenBucketRateLimiter: In-memory RPM/TPM limiting with sliding window
- SemaphoreRateLimiter: Max concurrent request limiting
- RedisRateLimiter: Distributed rate limiting using Redis
- CompositeRateLimiter: Combines multiple limiters (global + per-user)

All limiters are thread-safe and support context manager protocol.
"""

import asyncio
import logging
import random
import threading
import time
from abc import ABC, abstractmethod
from contextlib import asynccontextmanager, contextmanager
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from .interfaces import RateLimitConfig, RateLimitExceeded

logger = logging.getLogger(__name__)

# Check for optional Redis dependency
try:
    import redis
    REDIS_AVAILABLE = True
except ImportError:
    REDIS_AVAILABLE = False
    redis = None


# ======================
# Backoff Strategy
# ======================

@dataclass
class BackoffStrategy:
    """
    Exponential backoff strategy with jitter for retry logic.
    
    Attributes:
        base_delay: Initial delay in seconds (e.g., 1.0).
        max_delay: Maximum delay cap in seconds (e.g., 60.0).
        multiplier: Exponential multiplier for each retry (e.g., 2.0).
        jitter: Add randomness to avoid thundering herd (0.0-1.0).
    """
    base_delay: float = 1.0
    max_delay: float = 60.0
    multiplier: float = 2.0
    jitter: float = 0.1
    
    def calculate_delay(self, attempt: int) -> float:
        """
        Calculate delay for given retry attempt.
        
        Args:
            attempt: Retry attempt number (0-indexed).
        
        Returns:
            Delay in seconds with exponential backoff and jitter.
        """
        # Exponential: base * (multiplier ^ attempt)
        delay = min(self.base_delay * (self.multiplier ** attempt), self.max_delay)
        
        # Add jitter: random variation of ±jitter%
        if self.jitter > 0:
            jitter_amount = delay * self.jitter * (2 * random.random() - 1)
            delay = max(0.1, delay + jitter_amount)
        
        return delay


# ======================
# Rate Limiter Interface
# ======================

class RateLimiterInterface(ABC):
    """
    Abstract interface for rate limiters.
    
    All rate limiters must implement acquire/release pattern and support
    both sync and async contexts for API and CLI compatibility.
    """
    
    @abstractmethod
    async def acquire(self, user_id: Optional[str] = None, tokens: int = 1) -> bool:
        """
        Acquire permission to proceed (async version).
        
        Args:
            user_id: Optional user identifier for per-user limiting.
            tokens: Number of tokens to consume (for TPM limiting).
        
        Returns:
            True if allowed, False if rate limited.
        
        Raises:
            RateLimitExceeded: If rate limit is exceeded and should block.
        """
        pass
    
    def acquire_sync(self, user_id: Optional[str] = None, tokens: int = 1) -> bool:
        """
        Acquire permission to proceed (sync version for CLI).
        
        Default implementation runs async version in new event loop.
        Override for pure synchronous limiters.
        """
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                # Already in async context, create task
                return asyncio.create_task(self.acquire(user_id, tokens))
            else:
                return loop.run_until_complete(self.acquire(user_id, tokens))
        except RuntimeError:
            # No event loop, create one
            return asyncio.run(self.acquire(user_id, tokens))
    
    @abstractmethod
    async def release(self, user_id: Optional[str] = None, tokens: int = 1) -> None:
        """
        Release acquired resources (async version).
        
        Args:
            user_id: Optional user identifier for per-user limiting.
            tokens: Number of tokens to release.
        """
        pass
    
    def release_sync(self, user_id: Optional[str] = None, tokens: int = 1) -> None:
        """
        Release acquired resources (sync version for CLI).
        
        Default implementation runs async version in new event loop.
        """
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                asyncio.create_task(self.release(user_id, tokens))
            else:
                loop.run_until_complete(self.release(user_id, tokens))
        except RuntimeError:
            asyncio.run(self.release(user_id, tokens))
    
    @asynccontextmanager
    async def limit(self, user_id: Optional[str] = None, tokens: int = 1):
        """
        Context manager for automatic acquire/release (async).
        
        Usage:
            async with rate_limiter.limit(user_id="user_123"):
                # Make LLM API call
                result = await llm_provider.complete(...)
        """
        await self.acquire(user_id, tokens)
        try:
            yield
        finally:
            await self.release(user_id, tokens)
    
    @contextmanager
    def limit_sync(self, user_id: Optional[str] = None, tokens: int = 1):
        """
        Context manager for automatic acquire/release (sync).
        
        Usage:
            with rate_limiter.limit_sync(user_id="user_123"):
                # Make LLM API call
                result = llm_provider.complete(...)
        """
        self.acquire_sync(user_id, tokens)
        try:
            yield
        finally:
            self.release_sync(user_id, tokens)


# ======================
# Token Bucket Rate Limiter (In-Memory)
# ======================

class TokenBucketRateLimiter(RateLimiterInterface):
    """
    Token bucket rate limiter with sliding window (in-memory).
    
    Enforces requests per minute (RPM) and optionally tokens per minute (TPM).
    Thread-safe for concurrent API requests.
    
    Features:
    - Sliding window for accurate rate tracking
    - Separate buckets for global and per-user limits
    - Adaptive rate limiting support
    """
    
    def __init__(
        self,
        config: RateLimitConfig,
        scope: str = "global",
        backoff_strategy: Optional[BackoffStrategy] = None
    ):
        """
        Initialize token bucket rate limiter.
        
        Args:
            config: Rate limit configuration.
            scope: "global" for shared limits or "user" for per-user limits.
            backoff_strategy: Optional backoff strategy for retries.
        """
        self.config = config
        self.scope = scope
        self.backoff_strategy = backoff_strategy or BackoffStrategy()
        
        # Request tracking: {user_id: [(timestamp, tokens), ...]}
        self._request_history: Dict[str, List[Tuple[float, int]]] = {}
        
        # Adaptive limits: {user_id: current_rpm}
        self._adaptive_limits: Dict[str, int] = {}
        self._last_increase: Dict[str, float] = {}
        
        # Thread safety
        self._lock = threading.RLock()
        
        logger.debug(
            "Initialized TokenBucketRateLimiter: scope=%s, rpm=%d, tpm=%s, adaptive=%s",
            scope, config.requests_per_minute, config.tokens_per_minute, config.adaptive_backoff
        )
    
    def _get_effective_limit(self, user_id: str) -> int:
        """Get current effective RPM limit (may be adapted)."""
        if not self.config.adaptive_backoff:
            return self.config.requests_per_minute
        
        # Return adaptive limit or default
        return self._adaptive_limits.get(user_id, self.config.requests_per_minute)
    
    def _clean_old_requests(self, user_id: str, now: float, window_seconds: int = 60) -> None:
        """Remove requests older than the sliding window."""
        cutoff = now - window_seconds
        if user_id in self._request_history:
            self._request_history[user_id] = [
                (ts, tokens) for ts, tokens in self._request_history[user_id]
                if ts > cutoff
            ]
    
    def _check_rate_limit(
        self,
        user_id: str,
        tokens: int,
        now: float
    ) -> Tuple[bool, Optional[int]]:
        """
        Check if request is within rate limits.
        
        Returns:
            Tuple of (allowed, retry_after_seconds)
        """
        # Clean old requests
        self._clean_old_requests(user_id, now)
        
        history = self._request_history.get(user_id, [])
        
        # Check RPM limit
        if self.config.requests_per_minute > 0:
            effective_rpm = self._get_effective_limit(user_id)
            request_count = len(history)
            
            if request_count >= effective_rpm:
                # Calculate retry_after from oldest request
                oldest_ts = history[0][0] if history else now
                retry_after = int(oldest_ts + 60 - now) + 1
                return False, retry_after
        
        # Check TPM limit
        if self.config.tokens_per_minute is not None and self.config.tokens_per_minute > 0:
            total_tokens = sum(t for _, t in history)
            
            if total_tokens + tokens > self.config.tokens_per_minute:
                # Calculate retry_after from oldest token usage
                oldest_ts = history[0][0] if history else now
                retry_after = int(oldest_ts + 60 - now) + 1
                return False, retry_after
        
        return True, None
    
    def _maybe_increase_limit(self, user_id: str, now: float) -> None:
        """Gradually increase adaptive limits during recovery."""
        if not self.config.adaptive_backoff:
            return
        
        last_increase = self._last_increase.get(user_id, 0)
        if now - last_increase < self.config.adaptive_increase_interval:
            return
        
        current_limit = self._adaptive_limits.get(user_id)
        if current_limit is None or current_limit >= self.config.requests_per_minute:
            return  # Already at max
        
        # Increase gradually
        new_limit = min(
            int(current_limit * self.config.adaptive_increase_factor),
            self.config.requests_per_minute
        )
        
        self._adaptive_limits[user_id] = new_limit
        self._last_increase[user_id] = now
        
        logger.info(
            "Adaptive rate limit increased: user_id=%s, %d → %d RPM",
            user_id, current_limit, new_limit
        )
    
    async def acquire(self, user_id: Optional[str] = None, tokens: int = 1) -> bool:
        """Acquire permission to proceed (async)."""
        # Use global bucket if no user_id
        effective_user_id = user_id or "_global"
        
        with self._lock:
            now = time.time()
            
            # Check if allowed
            allowed, retry_after = self._check_rate_limit(effective_user_id, tokens, now)
            
            if not allowed:
                # Decrease adaptive limit if enabled
                if self.config.adaptive_backoff:
                    current_limit = self._get_effective_limit(effective_user_id)
                    new_limit = max(1, int(current_limit * self.config.adaptive_decrease_factor))
                    self._adaptive_limits[effective_user_id] = new_limit
                    
                    logger.warning(
                        "Adaptive rate limit decreased: user_id=%s, %d → %d RPM",
                        effective_user_id, current_limit, new_limit
                    )
                
                raise RateLimitExceeded(
                    f"Rate limit exceeded: {self.config.requests_per_minute} RPM",
                    retry_after=retry_after,
                    limit_type="requests",
                    scope=self.scope,
                    user_id=user_id
                )
            
            # Record request
            if effective_user_id not in self._request_history:
                self._request_history[effective_user_id] = []
            
            self._request_history[effective_user_id].append((now, tokens))
            
            # Try to increase adaptive limit during recovery
            self._maybe_increase_limit(effective_user_id, now)
            
            return True
    
    async def release(self, user_id: Optional[str] = None, tokens: int = 1) -> None:
        """Release is no-op for token bucket (tokens expire naturally)."""
        pass


# ======================
# Semaphore Rate Limiter (Concurrent Requests)
# ======================

class SemaphoreRateLimiter(RateLimiterInterface):
    """
    Semaphore-based rate limiter for max concurrent requests.
    
    Enforces maximum concurrent LLM API calls.
    Uses asyncio.Semaphore for async and threading.Semaphore for sync.
    """
    
    def __init__(
        self,
        max_concurrent: int,
        scope: str = "global"
    ):
        """
        Initialize semaphore rate limiter.
        
        Args:
            max_concurrent: Maximum concurrent requests (0 = unlimited).
            scope: "global" or "user" for limiting scope.
        """
        self.max_concurrent = max_concurrent
        self.scope = scope
        
        if max_concurrent <= 0:
            # Unlimited - no semaphore needed
            self._semaphore = None
            self._user_semaphores: Dict[str, asyncio.Semaphore] = {}
        else:
            # Global semaphore for shared limiting
            self._semaphore = asyncio.Semaphore(max_concurrent)
            # Per-user semaphores for user limiting
            self._user_semaphores: Dict[str, asyncio.Semaphore] = {}
        
        self._lock = threading.Lock()
        
        logger.debug(
            "Initialized SemaphoreRateLimiter: scope=%s, max_concurrent=%d",
            scope, max_concurrent
        )
    
    def _get_semaphore(self, user_id: Optional[str]) -> Optional[asyncio.Semaphore]:
        """Get appropriate semaphore for user or global."""
        if self.max_concurrent <= 0:
            return None
        
        if self.scope == "global" or user_id is None:
            return self._semaphore
        
        # Per-user semaphore
        if user_id not in self._user_semaphores:
            with self._lock:
                if user_id not in self._user_semaphores:
                    self._user_semaphores[user_id] = asyncio.Semaphore(self.max_concurrent)
        
        return self._user_semaphores[user_id]
    
    async def acquire(self, user_id: Optional[str] = None, tokens: int = 1) -> bool:
        """Acquire semaphore slot."""
        semaphore = self._get_semaphore(user_id)
        
        if semaphore is None:
            return True  # Unlimited
        
        # Try to acquire without blocking
        acquired = semaphore.locked() is False
        
        if not acquired and semaphore.locked():
            raise RateLimitExceeded(
                f"Max concurrent requests reached: {self.max_concurrent}",
                retry_after=1,  # Retry soon
                limit_type="concurrent",
                scope=self.scope,
                user_id=user_id
            )
        
        await semaphore.acquire()
        return True
    
    async def release(self, user_id: Optional[str] = None, tokens: int = 1) -> None:
        """Release semaphore slot."""
        semaphore = self._get_semaphore(user_id)
        
        if semaphore is not None:
            semaphore.release()


# ======================
# Redis Rate Limiter (Distributed)
# ======================

class RedisRateLimiter(RateLimiterInterface):
    """
    Redis-based distributed rate limiter using sliding window.
    
    Uses Redis sorted sets for accurate sliding window tracking.
    Supports multi-instance deployments with shared rate limits.
    """
    
    def __init__(
        self,
        redis_client,
        config: RateLimitConfig,
        key_prefix: str = "qr:ratelimit",
        scope: str = "global"
    ):
        """
        Initialize Redis rate limiter.
        
        Args:
            redis_client: Redis client instance.
            config: Rate limit configuration.
            key_prefix: Redis key prefix for namespacing.
            scope: "global" or "user" for limiting scope.
        """
        if not REDIS_AVAILABLE:
            raise RuntimeError("redis package is required for RedisRateLimiter")
        
        self.redis = redis_client
        self.config = config
        self.key_prefix = key_prefix
        self.scope = scope
        
        logger.debug(
            "Initialized RedisRateLimiter: scope=%s, rpm=%d, prefix=%s",
            scope, config.requests_per_minute, key_prefix
        )
    
    def _get_key(self, user_id: Optional[str], limit_type: str) -> str:
        """Generate Redis key for rate limit tracking."""
        if self.scope == "global" or user_id is None:
            return f"{self.key_prefix}:{limit_type}:global"
        return f"{self.key_prefix}:{limit_type}:user:{user_id}"
    
    async def acquire(self, user_id: Optional[str] = None, tokens: int = 1) -> bool:
        """Acquire using Redis sliding window."""
        now = time.time()
        window_start = now - 60  # 1 minute window
        
        # RPM check
        if self.config.requests_per_minute > 0:
            key = self._get_key(user_id, "rpm")
            
            # Remove old entries and count current
            pipe = self.redis.pipeline()
            pipe.zremrangebyscore(key, '-inf', window_start)
            pipe.zcard(key)
            pipe.zadd(key, {f"{now}:{random.random()}": now})
            pipe.expire(key, 60)
            results = pipe.execute()
            
            current_count = results[1]
            
            if current_count >= self.config.requests_per_minute:
                # Get oldest request for retry_after
                oldest = self.redis.zrange(key, 0, 0, withscores=True)
                retry_after = int(oldest[0][1] + 60 - now) + 1 if oldest else 1
                
                # Remove the request we just added
                self.redis.zrem(key, f"{now}:{random.random()}")
                
                raise RateLimitExceeded(
                    f"Rate limit exceeded: {self.config.requests_per_minute} RPM",
                    retry_after=retry_after,
                    limit_type="requests",
                    scope=self.scope,
                    user_id=user_id
                )
        
        # TPM check
        if self.config.tokens_per_minute is not None and self.config.tokens_per_minute > 0:
            key = self._get_key(user_id, "tpm")
            
            pipe = self.redis.pipeline()
            pipe.zremrangebyscore(key, '-inf', window_start)
            pipe.zrange(key, 0, -1, withscores=True)
            results = pipe.execute()
            
            # Sum tokens in window
            current_tokens = sum(int(score) for _, score in results[1])
            
            if current_tokens + tokens > self.config.tokens_per_minute:
                oldest = results[1][0] if results[1] else (None, now)
                retry_after = int(oldest[1] + 60 - now) + 1
                
                raise RateLimitExceeded(
                    f"Token limit exceeded: {self.config.tokens_per_minute} TPM",
                    retry_after=retry_after,
                    limit_type="tokens",
                    scope=self.scope,
                    user_id=user_id
                )
            
            # Add tokens
            self.redis.zadd(key, {f"{now}:{random.random()}": tokens})
            self.redis.expire(key, 60)
        
        return True
    
    async def release(self, user_id: Optional[str] = None, tokens: int = 1) -> None:
        """Release is no-op for Redis (entries expire naturally)."""
        pass


# ======================
# Composite Rate Limiter (Multiple Limits)
# ======================

class CompositeRateLimiter(RateLimiterInterface):
    """
    Composite rate limiter that enforces multiple limits simultaneously.
    
    Useful for combining:
    - Global + per-user limits (hybrid approach)
    - RPM + concurrent limits
    - Multiple backend strategies
    
    All limiters must pass for request to be allowed.
    """
    
    def __init__(self, limiters: List[RateLimiterInterface]):
        """
        Initialize composite rate limiter.
        
        Args:
            limiters: List of rate limiters to enforce (all must pass).
        """
        self.limiters = limiters
        logger.debug("Initialized CompositeRateLimiter with %d limiters", len(limiters))
    
    async def acquire(self, user_id: Optional[str] = None, tokens: int = 1) -> bool:
        """Acquire from all limiters (all must succeed)."""
        acquired = []
        
        try:
            for limiter in self.limiters:
                await limiter.acquire(user_id, tokens)
                acquired.append(limiter)
            return True
        except RateLimitExceeded:
            # Rollback acquired limiters
            for limiter in acquired:
                await limiter.release(user_id, tokens)
            raise
    
    async def release(self, user_id: Optional[str] = None, tokens: int = 1) -> None:
        """Release all limiters."""
        for limiter in self.limiters:
            await limiter.release(user_id, tokens)


__all__ = [
    "BackoffStrategy",
    "RateLimiterInterface",
    "TokenBucketRateLimiter",
    "SemaphoreRateLimiter",
    "RedisRateLimiter",
    "CompositeRateLimiter",
]
