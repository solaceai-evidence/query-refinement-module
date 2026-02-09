"""
Admin endpoints for session diagnostics and cache management.

Provides visibility into Redis cache behavior and session reconstruction
for debugging production issues and monitoring performance.
"""
from typing import List, Dict, Any
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from query_refinement_module.api.auth import get_current_user
from query_refinement_module.api.routes.admin import require_superuser
from query_refinement_module.api.session_manager import SessionManager
from query_refinement_module.api.config import get_settings
from query_refinement_module.db.models.user import User
from query_refinement_module.db.models.query import Query
from query_refinement_module.db.session import get_db
from query_refinement_module.db import crud
from query_refinement_module.schema.registry import get_framework
from query_refinement_module.tracing import get_request_id

router = APIRouter(prefix="/api/admin/sessions", tags=["admin", "sessions"])
settings = get_settings()


def get_session_manager() -> SessionManager:
    """Get the singleton SessionManager instance."""
    return SessionManager(
        redis_url=settings.redis_url,
        session_ttl_seconds=settings.session_ttl_seconds
    )


@router.get("/cache-metrics", response_model=Dict[str, Any])
async def get_cache_metrics(
    current_user: User = Depends(require_superuser),
    session_manager: SessionManager = Depends(get_session_manager)
):
    """
    Get Redis cache hit/miss statistics.
    
    **Admin Only**
    
    Returns:
        - cache_hits: Number of successful cache lookups
        - cache_misses: Number of cache misses requiring reconstruction
        - total_lookups: Total cache access attempts
        - hit_rate: Cache hit rate as percentage
        - miss_rate: Cache miss rate as percentage
    """
    return session_manager.get_cache_metrics()


@router.post("/cache-metrics/reset", status_code=status.HTTP_204_NO_CONTENT)
async def reset_cache_metrics(
    current_user: User = Depends(require_superuser),
    session_manager: SessionManager = Depends(get_session_manager)
):
    """
    Reset cache metrics counters.
    
    **Admin Only**
    
    Useful for starting fresh monitoring after deployment or maintenance.
    """
    success = session_manager.reset_cache_metrics()
    if not success:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to reset cache metrics"
        )


@router.get("/{query_id}/reconstruction-log", response_model=List[Dict[str, Any]])
async def get_reconstruction_log(
    query_id: int,
    limit: int = 50,
    current_user: User = Depends(require_superuser),
    session_manager: SessionManager = Depends(get_session_manager),
    db: Session = Depends(get_db)
):
    """
    Get session reconstruction attempt history for a specific query.
    
    **Admin Only**
    
    Args:
        query_id: Database query ID
        limit: Maximum number of attempts to return (default: 50)
    
    Returns:
        List of reconstruction attempts with:
        - timestamp: Unix timestamp of attempt
        - success: Whether reconstruction succeeded
        - error: Error message if failed
        - request_id: Request ID for tracing
    """
    # Verify query exists
    query = crud.get_query(db, query_id)
    if not query:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Query {query_id} not found"
        )
    
    attempts = session_manager.get_reconstruction_log(query_id, limit)
    return attempts


@router.post("/{query_id}/force-reconstruct", response_model=Dict[str, Any])
async def force_session_reconstruction(
    query_id: int,
    current_user: User = Depends(require_superuser),
    session_manager: SessionManager = Depends(get_session_manager),
    db: Session = Depends(get_db)
):
    """
    Force session reconstruction from database (clears cache first).
    
    **Admin Only**
    
    Useful for debugging cache inconsistencies or testing reconstruction
    logic without waiting for TTL expiration.
    
    Args:
        query_id: Database query ID
    
    Returns:
        - query_id: The query ID
        - cache_cleared: Whether cache was cleared
        - reconstruction_attempted: Whether reconstruction was attempted
        - reconstruction_success: Whether reconstruction succeeded
        - error: Error message if reconstruction failed
        - steps_reconstructed: Number of refinement steps reconstructed
    """
    request_id = get_request_id()
    
    # Verify query exists
    query = crud.get_query(db, query_id)
    if not query:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Query {query_id} not found"
        )
    
    # Clear existing cache
    cache_cleared = session_manager.delete_session(query_id)
    
    # Attempt reconstruction
    try:
        # Load framework for the query's session
        session_obj = crud.get_query_session(db, query.session_id)
        if not session_obj:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Session {query.session_id} not found"
            )
        
        framework_name = session_obj.framework_name or "default"
        
        # Get framework aspects
        refinement_framework = get_framework(framework_name)
        
        if not refinement_framework:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Framework '{framework_name}' not found"
            )
        
        # Attempt to reconstruct from DB by loading (this will trigger reconstruction)
        # Since we cleared cache, this will force it to reconstruct from DB
        from query_refinement_module.core import RefinementSession
        from query_refinement_module.core.state import AspectRefinementState
        
        # Manually reconstruct from DB
        session = RefinementSession(original_query=query.original_query)
        
        # Load refinement steps from DB
        steps = crud.get_query_refinement_steps(db, query_id)
        
        # Build aspect lookup
        aspect_map = {aspect.id: aspect for aspect in refinement_framework}
        
        # Reconstruct steps
        for step_row in steps:
            aspect = aspect_map.get(step_row.aspect_id)
            if not aspect:
                continue
            
            # Load follow-ups for this step
            followups = crud.get_refinement_step_followups(db, step_row.id)
            conversation_history = [
                {"question": fup.question, "answer": fup.answer}
                for fup in followups
                if fup.answer is not None
            ]
            
            step = AspectRefinementState(
                refinement_aspect=aspect,
                conversation_history=conversation_history,
                is_complete=step_row.is_complete,
                needs_review=step_row.needs_review,
                was_skipped=step_row.was_skipped,
                reasoning=step_row.needs_refinement_rationale,
                follow_up_question=step_row.refinement_question,
                normalized_value=step_row.refinement_aspect_value
            )
            
            session.steps.append(step)
        
        session.synthesis_requested = query.synthesis_requested or False
        
        # Save reconstructed session to cache
        save_success = session_manager.save_session(query_id, session, request_id)
        
        # Log reconstruction attempt
        session_manager.log_reconstruction_attempt(
            query_id=query_id,
            success=save_success,
            error_message=None if save_success else "Failed to save reconstructed session",
            request_id=request_id
        )
        
        return {
            "query_id": query_id,
            "cache_cleared": cache_cleared,
            "reconstruction_attempted": True,
            "reconstruction_success": save_success,
            "error": None if save_success else "Failed to save reconstructed session",
            "steps_reconstructed": len(session.steps),
            "request_id": request_id
        }
        
    except Exception as e:
        # Log failed reconstruction
        session_manager.log_reconstruction_attempt(
            query_id=query_id,
            success=False,
            error_message=str(e),
            request_id=request_id
        )
        
        return {
            "query_id": query_id,
            "cache_cleared": cache_cleared,
            "reconstruction_attempted": True,
            "reconstruction_success": False,
            "error": str(e),
            "steps_reconstructed": 0,
            "request_id": request_id
        }


@router.get("/{query_id}/cache-status", response_model=Dict[str, Any])
async def get_session_cache_status(
    query_id: int,
    current_user: User = Depends(require_superuser),
    session_manager: SessionManager = Depends(get_session_manager),
    db: Session = Depends(get_db)
):
    """
    Check if a session is currently cached and get cache details.
    
    **Admin Only**
    
    Args:
        query_id: Database query ID
    
    Returns:
        - query_id: The query ID
        - cached: Whether session is in Redis cache
        - ttl: Remaining TTL in seconds (if cached)
        - cache_key: Redis key used for this session
        - size_kb: Approximate size of cached session in KB (if cached)
    """
    # Verify query exists
    query = crud.get_query(db, query_id)
    if not query:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Query {query_id} not found"
        )
    
    key = session_manager._make_key(query_id)
    
    try:
        # Check if key exists
        exists = session_manager.redis_client.exists(key)
        
        result = {
            "query_id": query_id,
            "cached": bool(exists),
            "cache_key": key
        }
        
        if exists:
            # Get TTL
            ttl = session_manager.redis_client.ttl(key)
            result["ttl_seconds"] = ttl if ttl > 0 else None
            
            # Get size
            data = session_manager.redis_client.get(key)
            if data:
                result["size_kb"] = round(len(data) / 1024, 2)
        else:
            result["ttl_seconds"] = None
            result["size_kb"] = None
        
        return result
        
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to check cache status: {str(e)}"
        )


@router.get("/active-sessions", response_model=Dict[str, Any])
async def get_active_cached_sessions(
    current_user: User = Depends(require_superuser),
    session_manager: SessionManager = Depends(get_session_manager)
):
    """
    Get list of all currently cached sessions.
    
    **Admin Only**
    
    Returns:
        - total_cached: Number of sessions in cache
        - sessions: List of cached session keys with TTL info
    """
    try:
        pattern = f"{session_manager.key_prefix}*"
        keys = session_manager.redis_client.keys(pattern)
        
        # Filter out metrics and reconstruction log keys
        session_keys = [
            k for k in keys 
            if not k.endswith(":metrics") and ":reconstruction:" not in k
        ]
        
        sessions = []
        for key in session_keys:
            # Extract query_id from key
            query_id_str = key.replace(session_manager.key_prefix, "")
            try:
                query_id = int(query_id_str)
                ttl = session_manager.redis_client.ttl(key)
                
                sessions.append({
                    "query_id": query_id,
                    "cache_key": key,
                    "ttl_seconds": ttl if ttl > 0 else None
                })
            except ValueError:
                # Skip non-numeric keys
                continue
        
        return {
            "total_cached": len(sessions),
            "sessions": sessions
        }
        
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get active sessions: {str(e)}"
        )
