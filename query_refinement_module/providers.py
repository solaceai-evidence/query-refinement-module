import asyncio
import json
import logging
import pickle
import threading
import time
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Dict, Optional

__all__ = [
    "NoOpTracingProvider",
    "ConsoleTracing",
    "FileTracingProvider",
    "TraceEventEmitter",
    "InMemorySessionStorage",
    "RedisSessionStorage",
    "ConcurrentSessionStorage",
    "LiteLLMProvider",
]

try:  # optional dependency for LLM access
    import litellm  # type: ignore[import]
except ImportError:  # surfaced when provider is constructed
    litellm = None

try:  # validated at runtime when Redis storage is instantiated
    import redis  # type: ignore[import]
except ImportError:  # handled with explicit runtime error
    redis = None

from .interfaces import (
    LLMCompletionResult,
    LLMProviderInterface,
    SessionStorageInterface,
    TracingProviderInterface,
    RateLimitExceeded,
)

# ========
# Tracing Utilities
# ========
logger = logging.getLogger(__name__)


class TraceEventEmitter:
    """Helper that safely emits events and metrics through a tracing provider implementation."""

    def __init__(self, tracing_provider: Optional[TracingProviderInterface]) -> None:
        self._provider = tracing_provider

    def emit(
        self,
        event_name: str,
        level: str = "info",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        provider = self._provider

        if not provider:
            return

        if not hasattr(provider, "log_event") or not hasattr(provider, "is_enabled"):
            logger.debug(
                "Tracing provider %s does not support event logging",
                type(provider).__name__,
            )
            return

        try:
            if provider.is_enabled():
                provider.log_event(event_name, level=level, metadata=metadata)
        except Exception:  # pragma: no cover - tracing must not break core logic
            logger.debug(
                "Tracing provider %s failed to log event '%s'",
                type(provider).__name__,
                event_name,
                exc_info=True,
            )
    
    def metric(
        self,
        metric_name: str,
        value: float,
        unit: str = "",
        metadata: Optional[Dict[str, Any]] = None
    ) -> None:
        """Emit a metric through the tracing provider."""
        provider = self._provider
        
        if not provider:
            return
        
        if not hasattr(provider, "log_metric") or not hasattr(provider, "is_enabled"):
            return  # Provider doesn't support metrics, silently skip
        
        try:
            if provider.is_enabled():
                provider.log_metric(metric_name, value, unit=unit, metadata=metadata)
        except Exception:  # pragma: no cover - metrics must not break core logic
            logger.debug(
                "Tracing provider %s failed to log metric '%s'",
                type(provider).__name__,
                metric_name,
                exc_info=True,
            )


# ========
# Tracing Providers
# ========
class NoOpTracingProvider(TracingProviderInterface):
    """Simple no-op tracing provider for when tracing is disabled."""
    
    @contextmanager
    def trace_operation(self, name, operation_type = "function", metadata = None):
        yield
    
    def log_event(self, event_name, level = "info", metadata = None):
        pass
    
    def log_metric(self, metric_name: str, value: float, unit: str = "", metadata: Optional[Dict[str, Any]] = None):
        pass  # No-op: metrics are not logged when tracing is disabled

    def is_enabled(self) -> bool:
        return False

class ConsoleTracing(TracingProviderInterface):
    """A simple tracing provider that logs tracing information to the console."""
    
    @contextmanager
    def trace_operation(self, name: str, operation_type: str = "function", metadata: Optional[Dict[str, Any]] = None):
        print(f"[TRACE START] {operation_type.upper()}: {name} | Metadata: {metadata}")
        try:
            yield
            print(f"[TRACE END] {operation_type.upper()}: {name} - SUCCESS")
        except Exception as e:
            print(f"[TRACE END] {operation_type.upper()}: {name} - ERROR: {e}")
            raise
    
    def log_event(self, event_name: str, level: str = "info", metadata: Optional[Dict[str, Any]] = None):
        print(f"[EVENT] Level: {level.upper()} | Event: {event_name} | Metadata: {metadata}")
    
    def log_metric(self, metric_name: str, value: float, unit: str = "", metadata: Optional[Dict[str, Any]] = None):
        unit_str = f" {unit}" if unit else ""
        metadata_str = f" | Metadata: {metadata}" if metadata else ""
        print(f"[METRIC] {metric_name}: {value}{unit_str}{metadata_str}")

    def is_enabled(self) -> bool:
        return True


class FileTracingProvider(TracingProviderInterface):
    """Persist tracing operations and events to JSONL files on disk."""

    def __init__(
        self,
        log_dir: str,
        *,
        operations_filename: str = "trace_operations.log",
        events_filename: str = "trace_events.log",
    ) -> None:
        self._log_dir = Path(log_dir)
        self._log_dir.mkdir(parents=True, exist_ok=True)
        self._operations_file = self._log_dir / operations_filename
        self._events_file = self._log_dir / events_filename
        self._lock = threading.RLock()
        self._enabled = True

    @contextmanager
    def trace_operation(
        self,
        name: str,
        operation_type: str = "function",
        metadata: Optional[Dict[str, Any]] = None,
    ):
        start_payload = {
            "timestamp": self._timestamp(),
            "name": name,
            "operation_type": operation_type,
            "metadata": metadata or {},
            "event": "start",
        }
        self._write_json_line(self._operations_file, start_payload)
        try:
            yield
        except Exception as exc:
            failure_payload = {
                "timestamp": self._timestamp(),
                "name": name,
                "operation_type": operation_type,
                "metadata": metadata or {},
                "event": "end",
                "status": "error",
                "error": str(exc),
            }
            self._write_json_line(self._operations_file, failure_payload)
            raise
        else:
            success_payload = {
                "timestamp": self._timestamp(),
                "name": name,
                "operation_type": operation_type,
                "metadata": metadata or {},
                "event": "end",
                "status": "success",
            }
            self._write_json_line(self._operations_file, success_payload)

    def log_event(
        self,
        event_name: str,
        level: str = "info",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        payload = {
            "timestamp": self._timestamp(),
            "event": event_name,
            "level": level,
            "metadata": metadata or {},
        }
        self._write_json_line(self._events_file, payload)
    
    def log_metric(
        self,
        metric_name: str,
        value: float,
        unit: str = "",
        metadata: Optional[Dict[str, Any]] = None
    ) -> None:
        """Log a metric to the metrics file (separate from events)."""
        metrics_file = self._log_dir / "trace_metrics.log"
        payload = {
            "timestamp": self._timestamp(),
            "metric": metric_name,
            "value": value,
            "unit": unit,
            "metadata": metadata or {},
        }
        self._write_json_line(metrics_file, payload)

    def is_enabled(self) -> bool:
        return self._enabled

    def _write_json_line(self, file_path: Path, payload: Dict[str, Any]) -> None:
        with self._lock:
            with file_path.open("a", encoding="utf-8") as fh:
                json.dump(payload, fh, ensure_ascii=True)
                fh.write("\n")

    @staticmethod
    def _timestamp() -> str:
        return datetime.now(UTC).isoformat().replace("+00:00", "Z")


# ========
# Session Storage Implementations
# ========


class InMemorySessionStorage(SessionStorageInterface):
    """Thread-safe in-memory session storage.

    Suitable for tests and single-process deployments.
    """

    def __init__(self) -> None:
        self._sessions: Dict[str, Any] = {}
        self._lock = threading.RLock()

    def save_session(self, session_id: str, session: Any) -> None:
        with self._lock:
            self._sessions[session_id] = session

    def load_session(self, session_id: str) -> Any:
        with self._lock:
            if session_id not in self._sessions:
                raise KeyError(session_id)
            return self._sessions[session_id]

    def delete_session(self, session_id: str) -> None:
        with self._lock:
            self._sessions.pop(session_id, None)

    def session_exists(self, session_id: str) -> bool:
        with self._lock:
            return session_id in self._sessions


class RedisSessionStorage(SessionStorageInterface):
    """Redis-backed session persistence using pickle serialization."""

    def __init__(self, client: Any, namespace: str = "refinement:sessions") -> None:
        if redis is None:
            raise RuntimeError("redis package is required for RedisSessionStorage")
        self._client = client
        self._namespace = namespace.rstrip(":")

    def _key(self, session_id: str) -> str:
        return f"{self._namespace}:{session_id}"

    def save_session(self, session_id: str, session: Any) -> None:
        payload = pickle.dumps(session, protocol=pickle.HIGHEST_PROTOCOL)
        self._client.set(self._key(session_id), payload)

    def load_session(self, session_id: str) -> Any:
        raw = self._client.get(self._key(session_id))
        if raw is None:
            raise KeyError(session_id)
        return pickle.loads(raw)

    def delete_session(self, session_id: str) -> None:
        self._client.delete(self._key(session_id))

    def session_exists(self, session_id: str) -> bool:
        return bool(self._client.exists(self._key(session_id)))


class ConcurrentSessionStorage(SessionStorageInterface):
    """
    Wrapper that adds per-session async locking to any SessionStorageInterface.
    
    Ensures that concurrent async operations on the same session are serialized,
    preventing race conditions during parallel query refinement.
    
    Thread-safe: Uses asyncio.Lock per session_id for async coordination.
    Automatically cleans up locks for deleted sessions.
    """

    def __init__(self, backend: SessionStorageInterface) -> None:
        """
        Initialize concurrent session storage.
        
        Args:
            backend: Underlying storage implementation to wrap.
        """
        self._backend = backend
        self._locks: Dict[str, asyncio.Lock] = {}
        self._locks_lock = threading.Lock()  # Protects the _locks dict itself

    def _get_lock(self, session_id: str) -> asyncio.Lock:
        """Get or create an asyncio.Lock for a specific session."""
        with self._locks_lock:
            if session_id not in self._locks:
                self._locks[session_id] = asyncio.Lock()
            return self._locks[session_id]

    def _cleanup_lock(self, session_id: str) -> None:
        """Remove the lock for a deleted session to prevent memory leaks."""
        with self._locks_lock:
            self._locks.pop(session_id, None)

    async def save_session_async(self, session_id: str, session: Any) -> None:
        """Async-safe session save with per-session locking."""
        lock = self._get_lock(session_id)
        async with lock:
            # Run the synchronous storage operation in a thread pool
            await asyncio.to_thread(self._backend.save_session, session_id, session)

    async def load_session_async(self, session_id: str) -> Any:
        """Async-safe session load with per-session locking."""
        lock = self._get_lock(session_id)
        async with lock:
            # Run the synchronous storage operation in a thread pool
            return await asyncio.to_thread(self._backend.load_session, session_id)

    async def delete_session_async(self, session_id: str) -> None:
        """Async-safe session delete with per-session locking and cleanup."""
        lock = self._get_lock(session_id)
        async with lock:
            # Run the synchronous storage operation in a thread pool
            await asyncio.to_thread(self._backend.delete_session, session_id)
        # Clean up the lock after deletion
        self._cleanup_lock(session_id)

    async def session_exists_async(self, session_id: str) -> bool:
        """Async-safe session existence check."""
        # No locking needed for existence checks (read-only, idempotent)
        return await asyncio.to_thread(self._backend.session_exists, session_id)

    # Synchronous interface methods (for backward compatibility)
    def save_session(self, session_id: str, session: Any) -> None:
        """Synchronous save - delegates to backend directly."""
        self._backend.save_session(session_id, session)

    def load_session(self, session_id: str) -> Any:
        """Synchronous load - delegates to backend directly."""
        return self._backend.load_session(session_id)

    def delete_session(self, session_id: str) -> None:
        """Synchronous delete - delegates to backend directly."""
        self._backend.delete_session(session_id)
        self._cleanup_lock(session_id)

    def session_exists(self, session_id: str) -> bool:
        """Synchronous existence check - delegates to backend directly."""
        return self._backend.session_exists(session_id)


class LiteLLMProvider(LLMProviderInterface):
    """Generic LLM provider backed by `litellm` for multi-vendor support."""

    def __init__(
        self,
        default_model: str,
        *,
        api_key: Optional[str] = None,
        api_base: Optional[str] = None,
        default_completion_kwargs: Optional[Dict[str, Any]] = None,
    ) -> None:
        if litellm is None:
            raise RuntimeError(
                "litellm package is required for LiteLLMProvider. Install with 'pip install litellm'."
            )

        if not default_model:
            raise ValueError("default_model must be provided for LiteLLMProvider")

        self._default_model = default_model
        self._api_key = api_key
        self._api_base = api_base
        self._default_completion_kwargs = default_completion_kwargs or {}

    def complete(
        self,
        user_prompt: str,
        system_prompt: Optional[str] = None,
        model: Optional[str] = None,
        temperature: float = 0.0,
        max_tokens: Optional[int] = None,
        **kwargs: Any,
    ) -> LLMCompletionResult:
        """Complete a prompt with automatic retry on rate limit errors."""
        if litellm is None:
            raise RuntimeError(
                "litellm package is required for LiteLLMProvider. Install with 'pip install litellm'."
            )

        target_model = model or self._default_model
        if not target_model:
            raise ValueError("Model must be supplied either at initialization or call time")

        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": user_prompt})

        completion_kwargs: Dict[str, Any] = {**self._default_completion_kwargs, **kwargs}
        completion_kwargs.setdefault("temperature", temperature)
        if max_tokens is not None and "max_tokens" not in completion_kwargs:
            completion_kwargs["max_tokens"] = max_tokens

        logger.info(
            "Dispatching completion",
            extra={
                "llm_provider": "litellm",
                "model": target_model,
                "temperature": completion_kwargs.get("temperature"),
                "max_tokens": completion_kwargs.get("max_tokens"),
            },
        )

        # Retry logic with exponential backoff
        max_retries = 3
        base_delay = 1.0
        
        for attempt in range(max_retries + 1):
            try:
                response = litellm.completion(
                    model=target_model,
                    messages=messages,
                    api_key=self._api_key,
                    api_base=self._api_base,
                    **completion_kwargs,
                )

                message = response["choices"][0]["message"].get("content", "")
                usage = response.get("usage", {})
                total_tokens = usage.get("total_tokens")
                
                # Parse rate limit headers if available
                response_headers = getattr(response, "_hidden_params", {}).get("response_headers", {})
                rate_limit_info = self._parse_rate_limit_headers(response_headers)

                metadata = {
                    "provider": "litellm",
                    "model": target_model,
                    "usage": usage,
                    "response_id": response.get("id"),
                    "prompt_tokens": usage.get("prompt_tokens"),
                    "completion_tokens": usage.get("completion_tokens"),
                }
                
                if rate_limit_info:
                    metadata["rate_limit_info"] = rate_limit_info

                logger.info(
                    "Completion received",
                    extra={
                        "llm_provider": "litellm",
                        "model": target_model,
                        "total_tokens": total_tokens,
                        "attempt": attempt + 1,
                    },
                )

                return LLMCompletionResult(
                    context=message,
                    model=target_model,
                    total_tokens=total_tokens,
                    metadata=metadata,
                )
                
            except Exception as e:
                # Check if this is a rate limit error
                is_rate_limit_error = self._is_rate_limit_error(e)
                
                if is_rate_limit_error and attempt < max_retries:
                    # Extract retry_after from error or use exponential backoff
                    retry_after = self._extract_retry_after(e)
                    if retry_after is None:
                        retry_after = base_delay * (2 ** attempt)
                    
                    logger.warning(
                        "Rate limit hit, retrying after %s seconds (attempt %d/%d)",
                        retry_after,
                        attempt + 1,
                        max_retries,
                        exc_info=False,
                    )
                    
                    time.sleep(retry_after)
                    continue
                
                # For rate limit errors on final attempt, raise RateLimitExceeded
                if is_rate_limit_error:
                    retry_after = self._extract_retry_after(e) or 60.0
                    raise RateLimitExceeded(
                        message=f"Rate limit exceeded for model {target_model}: {str(e)}",
                        retry_after=retry_after,
                        limit_type="provider",
                        scope="global",
                    )
                
                # Non-rate-limit errors are raised immediately
                raise

    def get_model_info(self, model: str) -> Dict[str, Any]:
        if litellm is None:
            raise RuntimeError(
                "litellm package is required for LiteLLMProvider. Install with 'pip install litellm'."
            )

        info: Dict[str, Any] = {"model": model, "provider": "litellm"}

        if hasattr(litellm, "get_model_cost"):
            try:  # pragma: no cover - optional helper for supported metadata
                cost = litellm.get_model_cost(model=model)
                if cost:
                    info["pricing"] = cost
            except Exception:
                pass

        return info
    
    def get_rate_limits(self, model: Optional[str] = None) -> "RateLimitConfig":
        """
        Get rate limits for the provider/model.
        
        Returns provider-specific rate limits based on the model prefix.
        Falls back to conservative defaults for unknown providers.
        """
        from .interfaces import RateLimitConfig
        
        target_model = model or self._default_model
        
        # Provider-specific rate limits based on model prefix
        # These are conservative estimates - users should configure actual limits in .env
        
        if target_model.startswith("gpt-"):
            # OpenAI GPT models
            if "gpt-4" in target_model:
                return RateLimitConfig(
                    requests_per_minute=500,
                    tokens_per_minute=30000,
                    max_concurrent=10,
                )
            else:  # GPT-3.5 and others
                return RateLimitConfig(
                    requests_per_minute=3500,
                    tokens_per_minute=90000,
                    max_concurrent=10,
                )
        
        elif target_model.startswith("claude-"):
            # Anthropic Claude models
            return RateLimitConfig(
                requests_per_minute=50,
                tokens_per_minute=40000,
                max_concurrent=5,
            )
        
        elif target_model.startswith("gemini-"):
            # Google Gemini models
            return RateLimitConfig(
                requests_per_minute=60,
                tokens_per_minute=32000,
                max_concurrent=5,
            )
        
        elif "ollama" in target_model or "llama" in target_model.lower():
            # Local models (Ollama, Llama)
            return RateLimitConfig.unlimited()
        
        else:
            # Unknown provider - use conservative defaults
            return RateLimitConfig(
                requests_per_minute=60,
                tokens_per_minute=10000,
                max_concurrent=5,
            )
    
    def _is_rate_limit_error(self, error: Exception) -> bool:
        """Check if an exception is a rate limit error."""
        error_str = str(error).lower()
        error_type = type(error).__name__.lower()
        
        # Check for common rate limit indicators
        rate_limit_indicators = [
            "rate limit",
            "ratelimit",
            "429",
            "quota exceeded",
            "too many requests",
            "503",  # Service unavailable (often temporary)
        ]
        
        return any(indicator in error_str or indicator in error_type for indicator in rate_limit_indicators)
    
    def _extract_retry_after(self, error: Exception) -> Optional[float]:
        """Extract retry_after duration from error message or headers."""
        error_str = str(error)
        
        # Try to find "retry after X seconds" pattern
        import re
        patterns = [
            r"retry after ([0-9.]+) seconds?",
            r"retry_after[:\s]+([0-9.]+)",
            r"wait ([0-9.]+) seconds?",
        ]
        
        for pattern in patterns:
            match = re.search(pattern, error_str, re.IGNORECASE)
            if match:
                try:
                    return float(match.group(1))
                except (ValueError, IndexError):
                    pass
        
        return None
    
    def _parse_rate_limit_headers(self, headers: Dict[str, Any]) -> Dict[str, Any]:
        """Parse rate limit information from response headers."""
        if not headers:
            return {}
        
        rate_limit_info = {}
        
        # Normalize header keys to lowercase for case-insensitive lookup
        normalized_headers = {k.lower(): v for k, v in headers.items()}
        
        # Common rate limit headers
        if "x-ratelimit-remaining" in normalized_headers:
            try:
                rate_limit_info["requests_remaining"] = int(normalized_headers["x-ratelimit-remaining"])
            except (ValueError, TypeError):
                pass
        
        if "x-ratelimit-limit" in normalized_headers:
            try:
                rate_limit_info["requests_limit"] = int(normalized_headers["x-ratelimit-limit"])
            except (ValueError, TypeError):
                pass
        
        if "x-ratelimit-reset" in normalized_headers:
            # Reset time can be Unix timestamp or duration
            try:
                rate_limit_info["reset_time"] = float(normalized_headers["x-ratelimit-reset"])
            except (ValueError, TypeError):
                pass
        
        if "retry-after" in normalized_headers:
            try:
                rate_limit_info["retry_after"] = float(normalized_headers["retry-after"])
            except (ValueError, TypeError):
                pass
        
        return rate_limit_info





