"""
Session state management with Redis backend for query refinement workflows.

Provides persistent storage of QueryRefinementSession objects across API requests,
avoiding expensive re-initialization with LLM calls.

Key Features:
- JSON serialization of complex session objects
- TTL-based automatic expiration
- Graceful error handling with detailed logging
- Session statistics and monitoring
- Automatic retry logic for Redis connection failures

Performance Impact:
- Eliminates redundant LLM initialization calls
- Reduces API response times from ~2-5s to <100ms
- Preserves analysis results, follow-up history, and completion state
"""
import asyncio
import contextlib
import json
import logging
import threading
import time
from typing import Optional, Dict, Any, List
from datetime import timedelta

import redis
from redis.exceptions import RedisError, ConnectionError

from query_refinement_module.core import RefinementSession, AspectRefinementState
from query_refinement_module.schema import RefinementAspect
from query_refinement_module.tracing import get_logger

# Module logger - use get_logger() in methods for request context
logger = logging.getLogger(__name__)


def _serialize_step_state(step: AspectRefinementState) -> Dict[str, Any]:
    """Serialize one step to the canonical session-state format."""
    return {
        "refinement_aspect_id": step.refinement_aspect.id,
        "follow_up_history": step.conversation_history,
        "is_complete": step.is_complete,
        "needs_review": step.needs_review,
        "was_skipped": step.was_skipped,
        "needs_refinement_rationale": step.reasoning,
        "refinement_question": step.follow_up_question,
        "refinement_aspect_value": step.normalized_value,
    }


def serialize_session_state(session: RefinementSession) -> Dict[str, Any]:
    """Serialize a session to the shared persistence format used by all backends."""
    return {
        "original_query": session.original_query,
        "synthesis_requested": session.synthesis_requested,
        "steps": [_serialize_step_state(step) for step in session.steps],
        "complete_framework_ids": [aspect.id for aspect in session._complete_framework],
    }


def deserialize_session_state(
    data: Dict[str, Any],
    refinement_framework: List[RefinementAspect],
) -> RefinementSession:
    """Deserialize a session from the shared persistence format used by all backends."""
    aspect_map = {aspect.id: aspect for aspect in refinement_framework}

    session = RefinementSession(original_query=data["original_query"])
    session.synthesis_requested = data.get("synthesis_requested", False)

    framework_ids = data.get("complete_framework_ids", [])
    if framework_ids:
        session._complete_framework = [
            aspect_map[aspect_id] for aspect_id in framework_ids if aspect_id in aspect_map
        ]
    else:
        session._complete_framework = list(refinement_framework)

    for step_data in data["steps"]:
        aspect_id = step_data["refinement_aspect_id"]
        aspect = aspect_map.get(aspect_id)

        if not aspect:
            logger.warning("Aspect '%s' not found in framework, skipping step", aspect_id)
            continue

        step = AspectRefinementState(
            refinement_aspect=aspect,
            conversation_history=step_data.get("follow_up_history", []),
            is_complete=step_data.get("is_complete", False),
            needs_review=step_data.get("needs_review", False),
            was_skipped=step_data.get("was_skipped", False),
            reasoning=step_data.get("needs_refinement_rationale"),
            follow_up_question=step_data.get("refinement_question"),
            normalized_value=step_data.get("refinement_aspect_value"),
        )

        session.steps.append(step)

    return session


class SessionManager:
    """
    Manages query refinement session state with Redis backend.
    
    Provides:
    - Session serialization/deserialization
    - Redis storage with TTL
    - Session retrieval by query_id
    - Automatic cleanup via Redis expiration
    - Retry logic for transient failures
    - Cache hit/miss tracking for diagnostics
    """
    
    def __init__(
        self,
        redis_url: str = "redis://localhost:6379/0",
        session_ttl_seconds: int = 3600,
        key_prefix: str = "qr:session:",
        max_retries: int = 3,
        retry_delay: float = 0.5,
        lock_timeout_seconds: int = 60,
        lock_blocking_timeout_seconds: int = 30,
    ):
        """
        Initialize session manager with Redis connection.
        
        Args:
            redis_url: Redis connection URL (redis://host:port/db)
            session_ttl_seconds: Session expiration time in seconds (default: 1 hour)
            key_prefix: Prefix for Redis keys to namespace sessions
            max_retries: Maximum retry attempts for Redis operations
            retry_delay: Delay between retries in seconds
        """
        self.redis_client = redis.from_url(redis_url, decode_responses=True)
        self.session_ttl = session_ttl_seconds
        self.key_prefix = key_prefix
        self.max_retries = max_retries
        self.retry_delay = retry_delay
        self.metrics_key = f"{key_prefix}metrics"

        # Per-session asyncio locks: prevent concurrent load→mutate→save races for
        # the same query_id within a single process.
        self._session_locks: Dict[int, asyncio.Lock] = {}
        self._session_locks_meta = threading.Lock()  # protects the dict itself

        # Distributed lock settings (cross-process mutual exclusion)
        self._lock_timeout = lock_timeout_seconds
        self._lock_blocking_timeout = lock_blocking_timeout_seconds

        # Test connection
        try:
            self.redis_client.ping()
            logger.info("SessionManager connected to Redis at %s", redis_url)
        except RedisError as e:
            logger.error("Failed to connect to Redis: %s", e)
            raise

    # ------------------------------------------------------------------
    # Per-session locking
    # ------------------------------------------------------------------

    def _get_session_lock(self, query_id: int) -> asyncio.Lock:
        """Return (and lazily create) the asyncio.Lock for *query_id*."""
        with self._session_locks_meta:
            if query_id not in self._session_locks:
                self._session_locks[query_id] = asyncio.Lock()
            return self._session_locks[query_id]

    @contextlib.asynccontextmanager
    async def session_lock(self, query_id: int):
        """Async context manager that serialises concurrent modifications of a session.

        Acquires two locks in order:
        1. A Redis distributed lock (cross-process) — acquired in a thread-pool
           executor so the event loop is never blocked.
        2. A per-process asyncio lock (within-process) — acquired after Redis.

        Together these guarantee at most one coroutine, across *all* gunicorn
        workers, holds the session at any moment.

        Usage::

            async with session_manager.session_lock(query_id):
                session = session_manager.load_session(query_id, framework)
                # ... mutate session ...
                session_manager.save_session(query_id, session)

        Raises:
            RuntimeError: If the Redis lock cannot be acquired within
                ``lock_blocking_timeout_seconds``.
        """
        lock_key = f"{self.key_prefix}lock:{query_id}"
        redis_lock = self.redis_client.lock(
            lock_key,
            timeout=self._lock_timeout,
            blocking_timeout=self._lock_blocking_timeout,
        )

        loop = asyncio.get_running_loop()
        acquired = await loop.run_in_executor(None, redis_lock.acquire)
        if not acquired:
            raise RuntimeError(
                f"Could not acquire distributed session lock for query {query_id} "
                f"within {self._lock_blocking_timeout}s — another worker may be processing this session"
            )

        try:
            asyncio_lock = self._get_session_lock(query_id)
            async with asyncio_lock:
                yield
        finally:
            try:
                await loop.run_in_executor(None, redis_lock.release)
            except Exception as exc:
                logger.warning(
                    "Failed to release Redis session lock for query %d: %s",
                    query_id,
                    exc,
                )
    
    def _retry_operation(self, operation_name: str, operation_func):
        """
        Execute Redis operation with automatic retry on connection failures.
        
        Args:
            operation_name: Name of the operation for logging
            operation_func: Callable that performs the Redis operation
            
        Returns:
            Result of the operation or None on failure
        """
        for attempt in range(self.max_retries):
            try:
                return operation_func()
            except ConnectionError as e:
                if attempt < self.max_retries - 1:
                    logger.warning(
                        f"Redis {operation_name} failed (attempt {attempt + 1}/{self.max_retries}): {e}. Retrying..."
                    )
                    time.sleep(self.retry_delay * (attempt + 1))  # Exponential backoff
                else:
                    logger.error(f"Redis {operation_name} failed after {self.max_retries} attempts: {e}")
                    return None
            except RedisError as e:
                logger.error(f"Redis {operation_name} error: {e}")
                return None
    
    def _make_key(self, query_id: int) -> str:
        """Generate Redis key for a query session."""
        return f"{self.key_prefix}{query_id}"
    
    def save_session(self, query_id: int, session: RefinementSession, request_id: Optional[str] = None) -> bool:
        """
        Save a QueryRefinementSession to Redis with comprehensive logging and retry logic.
        
        Args:
            query_id: Database query ID
            session: QueryRefinementSession instance to save
            request_id: Optional request ID for tracing
            
        Returns:
            True if saved successfully, False otherwise
        """
        log = get_logger(__name__, request_id=request_id)
        
        def _save():
            log.info(f"Saving session for query_id={query_id}")
            
            # Serialize session (logs internally if complex)
            serialized = self._serialize_session(session)
            key = self._make_key(query_id)
            
            # Calculate serialized size for monitoring
            serialized_json = json.dumps(serialized)
            size_kb = len(serialized_json) / 1024
            
            # Store with TTL
            self.redis_client.setex(
                key,
                timedelta(seconds=self.session_ttl),
                serialized_json
            )
            
            log.info(
                f"Successfully saved session for query_id={query_id} "
                f"(size={size_kb:.2f}KB, TTL={self.session_ttl}s, "
                f"steps={len(session.steps)})"
            )
            return True
        
        try:
            return self._retry_operation("save_session", _save)
        except Exception as e:
            log.error(
                f"Failed to save session for query_id={query_id}: {str(e)}", 
                exc_info=True
            )
            return False
    
    def load_session(
        self,
        query_id: int,
        refinement_framework: List[RefinementAspect],
        request_id: Optional[str] = None
    ) -> Optional[RefinementSession]:
        """
        Load a QueryRefinementSession from Redis with comprehensive logging.
        
        Args:
            query_id: Database query ID
            refinement_framework: Framework definition needed for deserialization
            request_id: Optional request ID for tracing
            
        Returns:
            QueryRefinementSession if found, None otherwise
        """
        log = get_logger(__name__, request_id=request_id)
        
        try:
            log.info(f"Loading session for query_id={query_id}")
            key = self._make_key(query_id)
            data = self.redis_client.get(key)
            
            if not data:
                log.info(f"No cached session found for query_id={query_id} (may need initialization)")
                # Track cache miss
                self._increment_metric("cache_misses")
                return None
            
            # Track cache hit
            self._increment_metric("cache_hits")
            
            # Parse and deserialize
            serialized = json.loads(data)
            session = self._deserialize_session(serialized, refinement_framework)
            
            log.info(
                f"Successfully loaded session for query_id={query_id} "
                f"(steps={len(session.steps)}, "
                f"active_step={session.get_active_step().refinement_aspect.name if session.get_active_step() else 'None'}"
            )
            return session
            
        except (RedisError, json.JSONDecodeError, Exception) as e:
            logger.error("Failed to load session for query_id=%d: %s", query_id, e)
            # Track as cache miss on error
            self._increment_metric("cache_misses")
            return None
    
    def delete_session(self, query_id: int) -> bool:
        """
        Delete a session from Redis.
        
        Args:
            query_id: Database query ID
            
        Returns:
            True if deleted, False otherwise
        """
        try:
            key = self._make_key(query_id)
            deleted = self.redis_client.delete(key)
            logger.debug("Deleted session for query_id=%d (existed=%s)", query_id, bool(deleted))
            return bool(deleted)
            
        except RedisError as e:
            logger.error("Failed to delete session for query_id=%d: %s", query_id, e)
            return False
    
    def extend_ttl(self, query_id: int, extra_seconds: Optional[int] = None) -> bool:
        """
        Extend the TTL of an existing session.
        
        Args:
            query_id: Database query ID
            extra_seconds: Additional seconds to add (default: reset to full TTL)
            
        Returns:
            True if TTL extended, False otherwise
        """
        try:
            key = self._make_key(query_id)
            ttl = extra_seconds if extra_seconds else self.session_ttl
            
            success = self.redis_client.expire(key, ttl)
            if success:
                logger.debug("Extended TTL for query_id=%d by %ds", query_id, ttl)
            return success
            
        except RedisError as e:
            logger.error("Failed to extend TTL for query_id=%d: %s", query_id, e)
            return False
    
    def session_exists(self, query_id: int) -> bool:
        """Check if a session exists in Redis."""
        try:
            key = self._make_key(query_id)
            return bool(self.redis_client.exists(key))
        except RedisError:
            return False
    
    def _serialize_session(self, session: RefinementSession) -> Dict[str, Any]:
        """
        Serialize QueryRefinementSession to JSON-compatible dict.
        
        Args:
            session: QueryRefinementSession instance
            
        Returns:
            Dictionary representation
        """
        return serialize_session_state(session)
    
    def _serialize_step(self, step: AspectRefinementState) -> Dict[str, Any]:
        """
        Serialize QueryAspectRefiner to JSON-compatible dict.
        
        Args:
            step: QueryAspectRefiner instance
            
        Returns:
            Dictionary representation
        """
        return _serialize_step_state(step)
    
    def _deserialize_session(
        self,
        data: Dict[str, Any],
        refinement_framework: List[RefinementAspect]
    ) -> RefinementSession:
        """
        Deserialize QueryRefinementSession from dict.
        
        Args:
            data: Serialized session data
            refinement_framework: Framework definition for aspect reconstruction
            
        Returns:
            QueryRefinementSession instance
        """
        return deserialize_session_state(data, refinement_framework)
    
    def get_session_stats(self) -> Dict[str, int]:
        """
        Get statistics about stored sessions.
        
        Returns:
            Dictionary with session counts
        """
        try:
            pattern = f"{self.key_prefix}*"
            keys = self.redis_client.keys(pattern)
            return {
                "total_sessions": len(keys),
                "key_prefix": self.key_prefix
            }
        except RedisError as e:
            logger.error("Failed to get session stats: %s", e)
            return {"total_sessions": 0, "error": str(e)}
    
    def clear_all_sessions(self) -> int:
        """
        Clear all sessions (use with caution!).
        
        Returns:
            Number of sessions deleted
        """
        try:
            pattern = f"{self.key_prefix}*"
            keys = self.redis_client.keys(pattern)
            if keys:
                deleted = self.redis_client.delete(*keys)
                logger.warning("Cleared %d sessions", deleted)
                return deleted
            return 0
        except RedisError as e:
            logger.error("Failed to clear sessions: %s", e)
            return 0
    
    def _increment_metric(self, metric_name: str) -> None:
        """
        Increment a Redis counter for cache metrics.
        
        Args:
            metric_name: Name of the metric to increment (e.g., 'cache_hits', 'cache_misses')
        """
        try:
            self.redis_client.hincrby(self.metrics_key, metric_name, 1)
        except RedisError as e:
            logger.debug(f"Failed to increment metric {metric_name}: {e}")
    
    def get_cache_metrics(self) -> Dict[str, Any]:
        """
        Get cache hit/miss statistics.
        
        Returns:
            Dictionary with cache metrics including hit rate
        """
        try:
            metrics = self.redis_client.hgetall(self.metrics_key)
            hits = int(metrics.get("cache_hits", 0))
            misses = int(metrics.get("cache_misses", 0))
            total = hits + misses
            
            return {
                "cache_hits": hits,
                "cache_misses": misses,
                "total_lookups": total,
                "hit_rate": round((hits / total * 100), 2) if total > 0 else 0.0,
                "miss_rate": round((misses / total * 100), 2) if total > 0 else 0.0
            }
        except (RedisError, ValueError) as e:
            logger.error(f"Failed to get cache metrics: {e}")
            return {"error": str(e)}
    
    def reset_cache_metrics(self) -> bool:
        """
        Reset cache metrics counters.
        
        Returns:
            True if reset successfully, False otherwise
        """
        try:
            self.redis_client.delete(self.metrics_key)
            logger.info("Reset cache metrics")
            return True
        except RedisError as e:
            logger.error(f"Failed to reset cache metrics: {e}")
            return False
    
    def log_reconstruction_attempt(
        self,
        query_id: int,
        success: bool,
        error_message: Optional[str] = None,
        request_id: Optional[str] = None
    ) -> None:
        """
        Log a session reconstruction attempt for diagnostics.
        
        Args:
            query_id: Database query ID
            success: Whether reconstruction succeeded
            error_message: Error details if failed
            request_id: Optional request ID for tracing
        """
        log = get_logger(__name__, request_id=request_id)
        
        # Store in Redis list with timestamp
        reconstruction_key = f"{self.key_prefix}reconstruction:{query_id}"
        attempt_data = {
            "timestamp": time.time(),
            "success": success,
            "error": error_message,
            "request_id": request_id
        }
        
        try:
            # Add to list (keep last 50 attempts per query)
            self.redis_client.lpush(reconstruction_key, json.dumps(attempt_data))
            self.redis_client.ltrim(reconstruction_key, 0, 49)  # Keep only 50 most recent
            # Set TTL for reconstruction logs (24 hours)
            self.redis_client.expire(reconstruction_key, 86400)
            
            status = "SUCCESS" if success else "FAILED"
            log.info(
                f"Logged reconstruction attempt for query_id={query_id}: {status}",
                extra={"error": error_message} if error_message else {}
            )
        except RedisError as e:
            logger.warning(f"Failed to log reconstruction attempt: {e}")
    
    def get_reconstruction_log(self, query_id: int, limit: int = 50) -> List[Dict[str, Any]]:
        """
        Get reconstruction attempt history for a query.
        
        Args:
            query_id: Database query ID
            limit: Maximum number of attempts to return
            
        Returns:
            List of reconstruction attempts with timestamps
        """
        reconstruction_key = f"{self.key_prefix}reconstruction:{query_id}"
        
        try:
            attempts = self.redis_client.lrange(reconstruction_key, 0, limit - 1)
            return [json.loads(attempt) for attempt in attempts]
        except (RedisError, json.JSONDecodeError) as e:
            logger.error(f"Failed to get reconstruction log for query_id={query_id}: {e}")
            return []


class InMemorySessionManager:
    """
    In-memory fallback session manager when Redis is unavailable.
    
    WARNING: Sessions will be lost on server restart. Use Redis in production.
    """
    
    def __init__(self, session_ttl_seconds: int = 3600):
        self._sessions: Dict[int, Dict[str, Any]] = {}
        self._timestamps: Dict[int, float] = {}
        self.session_ttl = session_ttl_seconds
        self._session_locks: Dict[int, asyncio.Lock] = {}
        self._session_locks_meta = threading.Lock()
        logger.warning(
            "InMemorySessionManager initialized. Sessions will NOT persist across server restarts."
        )

    def _get_session_lock(self, query_id: int) -> asyncio.Lock:
        """Return a per-query asyncio lock for in-process mutual exclusion."""
        with self._session_locks_meta:
            if query_id not in self._session_locks:
                self._session_locks[query_id] = asyncio.Lock()
            return self._session_locks[query_id]

    @contextlib.asynccontextmanager
    async def session_lock(self, query_id: int):
        """Match the Redis-backed SessionManager lock API for local in-memory mode."""
        async with self._get_session_lock(query_id):
            yield
    
    def _cleanup_expired(self):
        """Remove expired sessions."""
        now = time.time()
        expired = [
            qid for qid, ts in self._timestamps.items()
            if now - ts > self.session_ttl
        ]
        for qid in expired:
            self._sessions.pop(qid, None)
            self._timestamps.pop(qid, None)
    
    def save_session(self, query_id: int, session: RefinementSession, request_id: Optional[str] = None) -> bool:
        """Save session to memory."""
        self._cleanup_expired()
        try:
            serialized = serialize_session_state(session)
            self._sessions[query_id] = serialized
            self._timestamps[query_id] = time.time()
            logger.debug(f"Saved session {query_id} to memory (steps={len(session.steps)})")
            return True
        except Exception as e:
            logger.error(f"Failed to save session {query_id} to memory: {e}")
            return False
    
    def load_session(
        self,
        query_id: int,
        refinement_framework: List[RefinementAspect],
        request_id: Optional[str] = None
    ) -> Optional[RefinementSession]:
        """Load session from memory."""
        self._cleanup_expired()
        serialized = self._sessions.get(query_id)
        if not serialized:
            return None
        try:
            return deserialize_session_state(serialized, refinement_framework)
        except Exception as e:
            logger.error(f"Failed to deserialize session {query_id}: {e}")
            return None
    
    def delete_session(self, query_id: int, request_id: Optional[str] = None) -> bool:
        """Delete session from memory. Returns False if the session did not exist."""
        had_session = query_id in self._sessions
        self._sessions.pop(query_id, None)
        self._timestamps.pop(query_id, None)
        return had_session
    
    def get_session_stats(self) -> Dict[str, Any]:
        """Get session statistics."""
        self._cleanup_expired()
        return {
            "total_sessions": len(self._sessions),
            "backend": "memory",
            "warning": "Sessions will not persist across server restarts"
        }
    
    def clear_all_sessions(self) -> int:
        """Clear all sessions."""
        count = len(self._sessions)
        self._sessions.clear()
        self._timestamps.clear()
        return count
