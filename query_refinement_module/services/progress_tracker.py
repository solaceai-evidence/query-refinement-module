"""
Progress tracking service for real-time refinement status.

Provides in-memory and Redis-backed progress tracking with TTL.
"""
import asyncio
import logging
import time
from datetime import datetime, timezone
from typing import Dict, Optional

from query_refinement_module.models.progress import (
    ProgressStage,
    ProgressStatus,
    ProgressUpdate,
    STAGE_MESSAGES,
    STAGE_PROGRESS_MAP,
)

logger = logging.getLogger(__name__)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class ProgressTracker:
    """
    Thread-safe progress tracking for refinement queries.
    
    Stores progress in memory with automatic cleanup after TTL.
    Can be extended to use Redis for distributed deployments.
    """
    
    def __init__(self, ttl_seconds: int = 3600):
        """
        Initialize progress tracker.
        
        Args:
            ttl_seconds: Time-to-live for progress entries (default: 1 hour)
        """
        self._progress: Dict[str, ProgressStatus] = {}
        self._lock = asyncio.Lock()
        self._ttl_seconds = ttl_seconds
        
        logger.info(f"Progress tracker initialized (TTL: {ttl_seconds}s)")
    
    async def create(
        self,
        query_id: str,
        initial_stage: ProgressStage = ProgressStage.CREATED,
        initial_message: Optional[str] = None
    ) -> ProgressStatus:
        """
        Create initial progress entry for a query.
        
        Args:
            query_id: Unique query identifier
            initial_stage: Starting stage (default: CREATED)
            initial_message: Custom message (default: stage-based message)
            
        Returns:
            Initial progress status
        """
        async with self._lock:
            now = _utc_now()
            
            progress = ProgressStatus(
                query_id=query_id,
                stage=initial_stage,
                progress=STAGE_PROGRESS_MAP.get(initial_stage, 0.0),
                message=initial_message or STAGE_MESSAGES.get(initial_stage, "Processing..."),
                started_at=now,
                updated_at=now,
                elapsed_seconds=0.0,
            )
            
            self._progress[query_id] = progress
            
            logger.info(
                f"Progress tracking started for query {query_id}",
                extra={"query_id": query_id, "stage": initial_stage.value}
            )
            
            return progress
    
    async def update(
        self,
        query_id: str,
        update: ProgressUpdate
    ) -> Optional[ProgressStatus]:
        """
        Update progress for a query.
        
        Args:
            query_id: Query identifier
            update: Progress update data
            
        Returns:
            Updated progress status, or None if query not found
        """
        async with self._lock:
            if query_id not in self._progress:
                logger.warning(f"Attempted to update progress for unknown query: {query_id}")
                return None
            
            progress = self._progress[query_id]
            now = _utc_now()
            
            # Update fields
            progress.stage = update.stage
            progress.progress = update.progress
            progress.message = update.message
            progress.updated_at = now
            progress.elapsed_seconds = (now - progress.started_at).total_seconds()
            
            # Update optional fields if provided
            if update.details is not None:
                progress.details = update.details
            if update.turn_number is not None:
                progress.turn_number = update.turn_number
            if update.total_turns is not None:
                progress.total_turns = update.total_turns
            if update.aspects_count is not None:
                progress.aspects_count = update.aspects_count
            if update.suggestions_count is not None:
                progress.suggestions_count = update.suggestions_count
            if update.llm_calls_made is not None:
                progress.llm_calls_made = update.llm_calls_made
            if update.estimated_completion_seconds is not None:
                progress.estimated_completion_seconds = update.estimated_completion_seconds
            if update.error is not None:
                progress.error = update.error
            
            logger.debug(
                f"Progress updated for query {query_id}: {update.stage.value} ({update.progress:.0%})",
                extra={
                    "query_id": query_id,
                    "stage": update.stage.value,
                    "progress": update.progress,
                    "progress_message": update.message
                }
            )
            
            return progress
    
    async def get(self, query_id: str) -> Optional[ProgressStatus]:
        """
        Get current progress for a query.
        
        Args:
            query_id: Query identifier
            
        Returns:
            Current progress status, or None if not found
        """
        async with self._lock:
            progress = self._progress.get(query_id)
            
            if progress:
                # Update elapsed time
                now = _utc_now()
                progress.elapsed_seconds = (now - progress.started_at).total_seconds()
            
            return progress
    
    async def delete(self, query_id: str) -> bool:
        """
        Delete progress entry for a query.
        
        Args:
            query_id: Query identifier
            
        Returns:
            True if deleted, False if not found
        """
        async with self._lock:
            if query_id in self._progress:
                del self._progress[query_id]
                logger.debug(f"Progress deleted for query {query_id}")
                return True
            return False
    
    async def cleanup_expired(self) -> int:
        """
        Remove progress entries older than TTL.
        
        Returns:
            Number of entries removed
        """
        async with self._lock:
            now = _utc_now()
            expired_ids = []
            
            for query_id, progress in self._progress.items():
                age_seconds = (now - progress.started_at).total_seconds()
                if age_seconds > self._ttl_seconds:
                    expired_ids.append(query_id)
            
            for query_id in expired_ids:
                del self._progress[query_id]
            
            if expired_ids:
                logger.info(f"Cleaned up {len(expired_ids)} expired progress entries")
            
            return len(expired_ids)
    
    async def increment_llm_calls(self, query_id: str) -> None:
        """
        Increment LLM call counter for a query.
        
        Args:
            query_id: Query identifier
        """
        async with self._lock:
            if query_id in self._progress:
                self._progress[query_id].llm_calls_made += 1
    
    async def get_all(self) -> Dict[str, ProgressStatus]:
        """
        Get all progress entries (for debugging/admin).
        
        Returns:
            Dict mapping query_id to progress status
        """
        async with self._lock:
            return dict(self._progress)


# Global progress tracker instance
_progress_tracker: Optional[ProgressTracker] = None


def get_progress_tracker() -> ProgressTracker:
    """
    Get or create global progress tracker instance.
    
    Returns:
        Global progress tracker
    """
    global _progress_tracker
    
    if _progress_tracker is None:
        _progress_tracker = ProgressTracker(ttl_seconds=3600)
    
    return _progress_tracker


async def track_progress(
    query_id: str,
    stage: ProgressStage,
    message: Optional[str] = None,
    **kwargs
) -> None:
    """
    Convenience function to update progress.
    
    Args:
        query_id: Query identifier
        stage: Progress stage
        message: Custom message (default: use stage message)
        **kwargs: Additional fields for ProgressUpdate
    """
    tracker = get_progress_tracker()
    
    update = ProgressUpdate(
        stage=stage,
        progress=STAGE_PROGRESS_MAP.get(stage, 0.5),
        message=message or STAGE_MESSAGES.get(stage, "Processing..."),
        **kwargs
    )
    
    await tracker.update(query_id, update)
