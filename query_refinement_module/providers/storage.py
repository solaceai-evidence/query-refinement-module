"""
Session storage provider implementations.

Extracted from providers.py as part of v2.0.0 Phase 4 refactoring.
"""
import asyncio
import logging
import pickle
import threading
from typing import Any, Dict

from ..interfaces import SessionStorageInterface

# Optional dependency for Redis storage
try:
    import redis
except ImportError:
    redis = None

logger = logging.getLogger(__name__)


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
        import time
        from query_refinement_module.tracing import get_request_id, get_trace_id
        
        request_id = get_request_id() or "-"
        trace_id = get_trace_id() or "-"
        start_time = time.time()
        
        logger.info(
            "Saving session to storage",
            extra={
                "request_id": request_id,
                "trace_id": trace_id,
                "session_id": session_id,
                "backend": self._backend.__class__.__name__,
            },
        )
        
        lock = self._get_lock(session_id)
        async with lock:
            # Run the synchronous storage operation in a thread pool
            await asyncio.to_thread(self._backend.save_session, session_id, session)
        
        duration_ms = (time.time() - start_time) * 1000
        logger.info(
            "Session saved to storage",
            extra={
                "request_id": request_id,
                "trace_id": trace_id,
                "session_id": session_id,
                "duration_ms": round(duration_ms, 2),
            },
        )

    async def load_session_async(self, session_id: str) -> Any:
        """Async-safe session load with per-session locking."""
        import time
        from query_refinement_module.tracing import get_request_id, get_trace_id
        
        request_id = get_request_id() or "-"
        trace_id = get_trace_id() or "-"
        start_time = time.time()
        
        logger.info(
            "Loading session from storage",
            extra={
                "request_id": request_id,
                "trace_id": trace_id,
                "session_id": session_id,
                "backend": self._backend.__class__.__name__,
            },
        )
        
        lock = self._get_lock(session_id)
        async with lock:
            # Run the synchronous storage operation in a thread pool
            result = await asyncio.to_thread(self._backend.load_session, session_id)
        
        duration_ms = (time.time() - start_time) * 1000
        logger.info(
            "Session loaded from storage",
            extra={
                "request_id": request_id,
                "trace_id": trace_id,
                "session_id": session_id,
                "found": result is not None,
                "duration_ms": round(duration_ms, 2),
            },
        )
        
        return result

    async def delete_session_async(self, session_id: str) -> None:
        """Async-safe session delete with per-session locking and cleanup."""
        import time
        from query_refinement_module.tracing import get_request_id, get_trace_id
        
        request_id = get_request_id() or "-"
        trace_id = get_trace_id() or "-"
        start_time = time.time()
        
        logger.info(
            "Deleting session from storage",
            extra={
                "request_id": request_id,
                "trace_id": trace_id,
                "session_id": session_id,
                "backend": self._backend.__class__.__name__,
            },
        )
        
        lock = self._get_lock(session_id)
        async with lock:
            # Run the synchronous storage operation in a thread pool
            await asyncio.to_thread(self._backend.delete_session, session_id)
        # Clean up the lock after deletion
        self._cleanup_lock(session_id)
        
        duration_ms = (time.time() - start_time) * 1000
        logger.info(
            "Session deleted from storage",
            extra={
                "request_id": request_id,
                "trace_id": trace_id,
                "session_id": session_id,
                "duration_ms": round(duration_ms, 2),
            },
        )

    async def session_exists_async(self, session_id: str) -> bool:
        """Async-safe session existence check."""
        from query_refinement_module.tracing import get_request_id, get_trace_id
        
        request_id = get_request_id() or "-"
        trace_id = get_trace_id() or "-"
        
        # No locking needed for existence checks (read-only, idempotent)
        exists = await asyncio.to_thread(self._backend.session_exists, session_id)
        
        logger.debug(
            "Session existence check",
            extra={
                "request_id": request_id,
                "trace_id": trace_id,
                "session_id": session_id,
                "exists": exists,
            },
        )
        
        return exists

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
