"""
Rate limiting infrastructure for LLM API calls.

Provides in-memory RPM/TPM rate limiting with sliding window.

TokenBucketRateLimiter is thread-safe and supports context manager protocol.
"""

import asyncio
import logging
import random
import threading
import time
from dataclasses import dataclass
from contextlib import asynccontextmanager, contextmanager
from typing import Dict, List, Optional, Tuple

from .interfaces import RateLimitConfig, RateLimitExceeded

logger = logging.getLogger(__name__)


# Backoff Strategy
# ======================

@dataclass
class BackoffStrategy:
    """
    Exponential backoff strategy with randomized relay (jitter) for retry logic.
    
    Attributes:
        base_delay: Initial delay in seconds (e.g., 1.0).
        max_delay: Maximum delay cap in seconds (e.g., 60.0).
        multiplier: Exponential multiplier for each retry (e.g., 2.0).
        jitter: Add randomness to prevent many clients retrying at the same time (0.0-1.0).
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


class TokenBucketRateLimiter:
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



__all__ = [
    "TokenBucketRateLimiter",
]
