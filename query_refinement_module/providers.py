import logging
import pickle
import threading
from contextlib import contextmanager
from typing import Any, Dict, Optional

__all__ = [
    "NoOpTracingProvider",
    "ConsoleTracing",
    "TraceEventEmitter",
    "InMemorySessionStorage",
    "RedisSessionStorage",
]

try:  # pragma: no cover - validated at runtime when Redis storage is instantiated
    import redis  # type: ignore[import]
except ImportError:  # pragma: no cover - handled with explicit runtime error
    redis = None

from .interfaces import SessionStorageInterface, TracingProviderInterface

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
    


