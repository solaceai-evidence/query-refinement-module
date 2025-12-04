import json
import logging
import pickle
import threading
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
    "LiteLLMProvider",
]

try:  # pragma: no cover - optional dependency for LLM access
    import litellm  # type: ignore[import]
except ImportError:  # pragma: no cover - surfaced when provider is constructed
    litellm = None

try:  # pragma: no cover - validated at runtime when Redis storage is instantiated
    import redis  # type: ignore[import]
except ImportError:  # pragma: no cover - handled with explicit runtime error
    redis = None

from .interfaces import (
    LLMCompletionResult,
    LLMProviderInterface,
    SessionStorageInterface,
    TracingProviderInterface,
)

# ========
# Tracing Utilities
# ========
logger = logging.getLogger(__name__)


class TraceEventEmitter:
    """Helper that safely emits events through a tracing provider implementation."""

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

        metadata = {
            "provider": "litellm",
            "model": target_model,
            "usage": usage,
            "response_id": response.get("id"),
        }

        logger.info(
            "Completion received",
            extra={
                "llm_provider": "litellm",
                "model": target_model,
                "total_tokens": total_tokens,
            },
        )

        return LLMCompletionResult(
            context=message,
            model=target_model,
            total_tokens=total_tokens,
            metadata=metadata,
        )

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





