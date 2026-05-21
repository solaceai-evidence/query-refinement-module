"""
Session storage provider implementations.

Extracted from providers.py as part of v2.0.0 Phase 4 refactoring.
"""
import asyncio
import json
import logging
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
    """Redis-backed session persistence using JSON serialization.

    Stored values must be JSON-serializable.  ``RefinementSession`` objects
    are automatically encoded/decoded via ``_encode_session``/``_decode_session``.
    """

    # Marker key that identifies a serialised RefinementSession envelope.
    _SESSION_MARKER = "_qrm_session_v1"

    def __init__(self, client: Any, namespace: str = "refinement:sessions") -> None:
        if redis is None:
            raise RuntimeError("redis package is required for RedisSessionStorage")
        self._client = client
        self._namespace = namespace.rstrip(":")

    def _key(self, session_id: str) -> str:
        return f"{self._namespace}:{session_id}"

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def save_session(self, session_id: str, session: Any) -> None:
        """Persist *session* to Redis as a JSON string.

        ``RefinementSession`` instances are encoded via ``_encode_session``.
        All other values must already be JSON-serializable.
        """
        from query_refinement_module.session_models import RefinementSession  # local import to avoid cycles

        if isinstance(session, RefinementSession):
            payload = json.dumps(self._encode_session(session))
        else:
            payload = json.dumps(session)
        self._client.set(self._key(session_id), payload)

    def load_session(self, session_id: str) -> Any:
        """Load and deserialise a previously saved session."""
        raw = self._client.get(self._key(session_id))
        if raw is None:
            raise KeyError(session_id)
        # redis may return bytes or str depending on decode_responses setting
        if isinstance(raw, (bytes, bytearray)):
            raw = raw.decode("utf-8")
        data = json.loads(raw)
        if isinstance(data, dict) and data.get(self._SESSION_MARKER):
            return self._decode_session(data)
        return data

    def delete_session(self, session_id: str) -> None:
        self._client.delete(self._key(session_id))

    def session_exists(self, session_id: str) -> bool:
        return bool(self._client.exists(self._key(session_id)))

    # ------------------------------------------------------------------
    # Serialisation helpers
    # ------------------------------------------------------------------

    def _encode_session(self, session: Any) -> Dict[str, Any]:
        """Encode a ``RefinementSession`` to a JSON-safe dict."""
        return {
            self._SESSION_MARKER: True,
            "original_query": session.original_query,
            "synthesis_requested": session.synthesis_requested,
            # Store full Pydantic model data so we can reconstruct without the
            # framework being passed separately (unlike SessionManager).
            "_complete_framework": [
                a.model_dump() for a in session._complete_framework
            ],
            "steps": [
                {
                    "refinement_aspect": step.refinement_aspect.model_dump(),
                    "conversation_history": step.conversation_history,
                    "is_complete": step.is_complete,
                    "needs_review": step.needs_review,
                    "was_skipped": step.was_skipped,
                    "reasoning": step.reasoning,
                    "follow_up_question": step.follow_up_question,
                    "normalized_value": step.normalized_value,
                }
                for step in session.steps
            ],
        }

    def _decode_session(self, data: Dict[str, Any]) -> Any:
        """Reconstruct a ``RefinementSession`` from an encoded dict."""
        from query_refinement_module.session_models import RefinementSession, AspectRefinementState
        from query_refinement_module.schema import RefinementAspect

        complete_framework = [
            RefinementAspect.model_validate(a)
            for a in data.get("_complete_framework", [])
        ]
        aspect_map = {a.id: a for a in complete_framework}

        session = RefinementSession(original_query=data["original_query"])
        session.synthesis_requested = data.get("synthesis_requested", False)
        session._complete_framework = complete_framework

        for s in data.get("steps", []):
            aspect_id = s["refinement_aspect"]["id"]
            aspect = aspect_map.get(aspect_id) or RefinementAspect.model_validate(
                s["refinement_aspect"]
            )
            step = AspectRefinementState(
                refinement_aspect=aspect,
                conversation_history=s.get("conversation_history", []),
                is_complete=s.get("is_complete", False),
                needs_review=s.get("needs_review", False),
                was_skipped=s.get("was_skipped", False),
                reasoning=s.get("reasoning"),
                follow_up_question=s.get("follow_up_question"),
                normalized_value=s.get("normalized_value"),
            )
            session.steps.append(step)

        return session


class ConcurrentSessionStorage(SessionStorageInterface):
    """
    Wrapper that adds per-session async locking to any SessionStorageInterface.

    Ensures that concurrent async operations on the same session are serialized,
    preventing race conditions during parallel query refinement.

    Thread-safe: Uses asyncio.Lock per session_id for async coordination.
    Automatically cleans up locks for deleted sessions.

    Note: The web API uses ``SessionManager`` (Redis-backed) for session storage.
    This class is intended for CLI/batch scripts and direct programmatic use
    that require async-safe session access on top of an arbitrary backend.
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
        """Synchronous delete - delegates to backend directly.

        Note: This does NOT acquire the per-session asyncio.Lock; use
        ``delete_session_async`` in async contexts to ensure mutual exclusion.
        """
        self._backend.delete_session(session_id)
        self._cleanup_lock(session_id)

    def session_exists(self, session_id: str) -> bool:
        """Synchronous existence check - delegates to backend directly."""
        return self._backend.session_exists(session_id)
