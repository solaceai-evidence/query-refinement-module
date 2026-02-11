"""
Circuit breaker pattern for LLM API calls.

Prevents cascading failures and wasted costs by temporarily stopping calls
to failing providers after a threshold of consecutive failures.

Features:
- Per-provider circuit breakers (OpenAI down ≠ Claude down)
- Automatic recovery with half-open state
- Configurable failure thresholds and recovery timeouts
- Thread-safe state management
- Detailed metrics for monitoring
"""
import asyncio
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Callable, Dict, Optional, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar('T')


class CircuitState(str, Enum):
    """Circuit breaker states following the standard circuit breaker pattern."""
    
    CLOSED = "closed"  # Normal operation, requests allowed
    OPEN = "open"  # Too many failures, requests blocked
    HALF_OPEN = "half_open"  # Testing if service recovered


@dataclass
class CircuitBreakerConfig:
    """Configuration for circuit breaker behavior."""
    
    # Failure threshold to open circuit
    failure_threshold: int = 5
    
    # How long to wait before attempting recovery (seconds)
    recovery_timeout: float = 60.0
    
    # Number of successful calls needed to close circuit from half-open
    success_threshold: int = 2
    
    # Window for counting failures (seconds) - prevents old failures from triggering
    failure_window: float = 300.0
    
    # Exceptions that should trigger circuit breaker
    # (e.g., provider errors but NOT user input validation errors)
    counted_exceptions: tuple = (Exception,)


@dataclass
class CircuitBreakerMetrics:
    """Metrics for monitoring circuit breaker health."""
    
    state: CircuitState
    failure_count: int = 0
    success_count: int = 0
    last_failure_time: Optional[float] = None
    last_success_time: Optional[float] = None
    opened_at: Optional[float] = None
    half_opened_at: Optional[float] = None
    closed_at: Optional[float] = None
    total_calls: int = 0
    rejected_calls: int = 0
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert metrics to dictionary for JSON serialization."""
        return {
            "state": self.state.value,
            "failure_count": self.failure_count,
            "success_count": self.success_count,
            "last_failure_time": datetime.fromtimestamp(self.last_failure_time).isoformat() if self.last_failure_time else None,
            "last_success_time": datetime.fromtimestamp(self.last_success_time).isoformat() if self.last_success_time else None,
            "opened_at": datetime.fromtimestamp(self.opened_at).isoformat() if self.opened_at else None,
            "half_opened_at": datetime.fromtimestamp(self.half_opened_at).isoformat() if self.half_opened_at else None,
            "closed_at": datetime.fromtimestamp(self.closed_at).isoformat() if self.closed_at else None,
            "total_calls": self.total_calls,
            "rejected_calls": self.rejected_calls,
        }


class CircuitBreakerOpen(Exception):
    """Exception raised when circuit breaker is open and requests are rejected."""
    
    def __init__(self, provider: str, recovery_time: float):
        self.provider = provider
        self.recovery_time = recovery_time
        retry_in = int(recovery_time - time.time())
        super().__init__(
            f"Circuit breaker is OPEN for provider '{provider}'. "
            f"Service temporarily unavailable. Retry in ~{retry_in} seconds."
        )


class CircuitBreaker:
    """
    Circuit breaker implementation for protecting against cascading failures.
    
    State transitions:
    - CLOSED -> OPEN: After failure_threshold consecutive failures
    - OPEN -> HALF_OPEN: After recovery_timeout seconds
    - HALF_OPEN -> CLOSED: After success_threshold consecutive successes
    - HALF_OPEN -> OPEN: On any failure during half-open state
    
    Thread-safe for async operations.
    """
    
    def __init__(self, name: str, config: Optional[CircuitBreakerConfig] = None):
        """
        Initialize circuit breaker.
        
        Args:
            name: Identifier for this circuit (e.g., provider name)
            config: Configuration options, uses defaults if not provided
        """
        self.name = name
        self.config = config or CircuitBreakerConfig()
        
        self._state = CircuitState.CLOSED
        self._lock = asyncio.Lock()
        
        # Metrics tracking
        self._metrics = CircuitBreakerMetrics(state=CircuitState.CLOSED)
        
        # Failure tracking with timestamps for windowing
        self._failure_timestamps: list[float] = []
        
    @property
    def state(self) -> CircuitState:
        """Get current circuit state."""
        return self._state
    
    @property
    def metrics(self) -> CircuitBreakerMetrics:
        """Get current metrics snapshot."""
        # Update state in metrics before returning
        self._metrics.state = self._state
        return self._metrics
    
    def _clean_old_failures(self):
        """Remove failures outside the failure window."""
        cutoff = time.time() - self.config.failure_window
        self._failure_timestamps = [
            ts for ts in self._failure_timestamps if ts > cutoff
        ]
    
    async def _transition_to_open(self):
        """Transition circuit to OPEN state."""
        self._state = CircuitState.OPEN
        self._metrics.opened_at = time.time()
        self._metrics.success_count = 0
        
        logger.warning(
            f"Circuit breaker OPENED for {self.name}",
            extra={
                "circuit": self.name,
                "failure_count": len(self._failure_timestamps),
                "recovery_timeout": self.config.recovery_timeout,
            }
        )
    
    async def _transition_to_half_open(self):
        """Transition circuit to HALF_OPEN state."""
        self._state = CircuitState.HALF_OPEN
        self._metrics.half_opened_at = time.time()
        self._metrics.success_count = 0
        
        logger.info(
            f"Circuit breaker HALF-OPEN for {self.name} (testing recovery)",
            extra={"circuit": self.name}
        )
    
    async def _transition_to_closed(self):
        """Transition circuit to CLOSED state."""
        self._state = CircuitState.CLOSED
        self._metrics.closed_at = time.time()
        self._metrics.failure_count = 0
        self._metrics.success_count = 0
        self._failure_timestamps.clear()
        
        logger.info(
            f"Circuit breaker CLOSED for {self.name} (service recovered)",
            extra={"circuit": self.name}
        )
    
    async def _check_and_update_state(self):
        """Check if state transition is needed based on current conditions."""
        async with self._lock:
            current_time = time.time()
            
            # Clean old failures
            self._clean_old_failures()
            
            if self._state == CircuitState.OPEN:
                # Check if enough time has passed to try recovery
                if self._metrics.opened_at and (current_time - self._metrics.opened_at) >= self.config.recovery_timeout:
                    await self._transition_to_half_open()
            
            elif self._state == CircuitState.CLOSED:
                # Check if we've hit failure threshold
                if len(self._failure_timestamps) >= self.config.failure_threshold:
                    await self._transition_to_open()
            
            elif self._state == CircuitState.HALF_OPEN:
                # Check if we've had enough successes to close
                if self._metrics.success_count >= self.config.success_threshold:
                    await self._transition_to_closed()
    
    async def call(self, func: Callable[..., T], *args: Any, **kwargs: Any) -> T:
        """
        Execute a function with circuit breaker protection.
        
        Args:
            func: Async function to execute
            *args: Positional arguments for func
            **kwargs: Keyword arguments for func
            
        Returns:
            Result from func
            
        Raises:
            CircuitBreakerOpen: If circuit is open and blocking requests
            Exception: Any exception raised by func (and tracked by circuit)
        """
        await self._check_and_update_state()
        
        self._metrics.total_calls += 1
        
        # Block if circuit is open
        if self._state == CircuitState.OPEN:
            self._metrics.rejected_calls += 1
            recovery_time = self._metrics.opened_at + self.config.recovery_timeout
            raise CircuitBreakerOpen(self.name, recovery_time)
        
        # Allow only one request through in half-open state
        if self._state == CircuitState.HALF_OPEN:
            async with self._lock:
                # If another request is already testing, reject this one
                if self._metrics.success_count > 0 and self._metrics.success_count < self.config.success_threshold:
                    self._metrics.rejected_calls += 1
                    recovery_time = time.time() + self.config.recovery_timeout
                    raise CircuitBreakerOpen(self.name, recovery_time)
        
        # Execute function with error tracking
        try:
            result = await func(*args, **kwargs)
            await self._on_success()
            return result
        except Exception as e:
            # Check if this exception type should be counted
            if isinstance(e, self.config.counted_exceptions):
                await self._on_failure(e)
            raise
    
    async def _on_success(self):
        """Record successful call."""
        async with self._lock:
            self._metrics.success_count += 1
            self._metrics.last_success_time = time.time()
            
            if self._state == CircuitState.HALF_OPEN:
                # Check if we can close the circuit
                await self._check_and_update_state()
            
            logger.debug(
                f"Circuit breaker success for {self.name}",
                extra={
                    "circuit": self.name,
                    "state": self._state.value,
                    "success_count": self._metrics.success_count,
                }
            )
    
    async def _on_failure(self, exception: Exception):
        """Record failed call."""
        async with self._lock:
            current_time = time.time()
            self._failure_timestamps.append(current_time)
            self._metrics.failure_count += 1
            self._metrics.last_failure_time = current_time
            
            logger.warning(
                f"Circuit breaker failure for {self.name}",
                extra={
                    "circuit": self.name,
                    "state": self._state.value,
                    "failure_count": len(self._failure_timestamps),
                    "error": str(exception),
                }
            )
            
            # If in half-open state, any failure immediately opens circuit
            if self._state == CircuitState.HALF_OPEN:
                await self._transition_to_open()
            else:
                # Check if we need to open circuit
                await self._check_and_update_state()


class CircuitBreakerRegistry:
    """
    Registry for managing multiple circuit breakers.
    
    Allows per-provider circuit breakers while sharing configuration.
    """
    
    def __init__(self, default_config: Optional[CircuitBreakerConfig] = None):
        """
        Initialize registry.
        
        Args:
            default_config: Default config for all circuit breakers
        """
        self.default_config = default_config or CircuitBreakerConfig()
        self._breakers: Dict[str, CircuitBreaker] = {}
        self._lock = asyncio.Lock()
    
    async def get_breaker(self, name: str) -> CircuitBreaker:
        """
        Get or create a circuit breaker for the given name.
        
        Args:
            name: Circuit breaker identifier (e.g., provider name)
            
        Returns:
            CircuitBreaker instance
        """
        if name not in self._breakers:
            async with self._lock:
                # Double-check after acquiring lock
                if name not in self._breakers:
                    self._breakers[name] = CircuitBreaker(name, self.default_config)
                    logger.info(
                        f"Created circuit breaker for {name}",
                        extra={"circuit": name, "config": self.default_config.__dict__}
                    )
        
        return self._breakers[name]
    
    def get_all_metrics(self) -> Dict[str, Dict[str, Any]]:
        """
        Get metrics for all circuit breakers.
        
        Returns:
            Dict mapping circuit name to metrics dict
        """
        return {
            name: breaker.metrics.to_dict()
            for name, breaker in self._breakers.items()
        }
    
    def reset_all(self):
        """Reset all circuit breakers to CLOSED state (for testing/admin)."""
        for breaker in self._breakers.values():
            breaker._state = CircuitState.CLOSED
            breaker._metrics = CircuitBreakerMetrics(state=CircuitState.CLOSED)
            breaker._failure_timestamps.clear()
        
        logger.info("All circuit breakers reset to CLOSED state")
