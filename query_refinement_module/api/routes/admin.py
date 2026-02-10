"""
Admin API routes for cache management and system integrity.

Requires superuser privileges for all endpoints.
"""
from fastapi import APIRouter, Depends, HTTPException, status, Request
from sqlalchemy.orm import Session
from typing import List, Dict, Any, Optional
from pydantic import BaseModel
import logging

from query_refinement_module.db.session import get_db
from query_refinement_module.db.crud import (
    get_query,
    get_query_refinement_steps,
    get_query_session,
    delete_refinement_steps_by_aspects,
)
from query_refinement_module.api.auth import get_current_user
from query_refinement_module.db.models.user import User
from query_refinement_module.audit import audit_service
from query_refinement_module.db.models.audit_log import AuditEventType

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin", tags=["Admin"])


# ==========================================
# Admin Authorization
# ==========================================

def require_superuser(current_user: User = Depends(get_current_user)) -> User:
    """Verify current user has superuser privileges."""
    # Get actual boolean value from SQLAlchemy column
    is_super = bool(current_user.is_superuser) if hasattr(current_user, 'is_superuser') else False
    if not is_super:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Superuser privileges required"
        )
    return current_user


# ==========================================
# Response Models
# ==========================================

class CacheSessionInfo(BaseModel):
    """Redis cache session information."""
    query_id: int
    key: str
    ttl_seconds: Optional[int]
    size_bytes: Optional[int]
    last_accessed: Optional[str]


class CacheStatsResponse(BaseModel):
    """Redis cache statistics."""
    total_keys: int
    session_keys: int
    memory_used_bytes: Optional[int]
    memory_used_mb: Optional[float]
    hit_rate: Optional[float]
    uptime_seconds: Optional[int]
    connected_clients: Optional[int]
    cache_ttl_seconds: int


class IntegrityCheckResult(BaseModel):
    """Result of integrity check for a query."""
    query_id: int
    consistent: bool
    issues: List[str]
    redis_steps: List[str]
    db_steps: List[str]
    orphaned_steps: List[str]
    missing_steps: List[str]


class IntegrityCheckResponse(BaseModel):
    """Overall integrity check response."""
    total_queries_checked: int
    consistent_queries: int
    inconsistent_queries: int
    total_orphaned_steps: int
    issues: List[IntegrityCheckResult]


class OrphanedStepsResponse(BaseModel):
    """Response listing orphaned refinement steps."""
    total_orphaned: int
    orphaned_steps: List[Dict[str, Any]]


class RepairResponse(BaseModel):
    """Response from repair operation."""
    repaired_queries: int
    deleted_steps: int
    details: List[Dict[str, Any]]


# ==========================================
# Cache Management Endpoints
# ==========================================

@router.get("/cache/sessions", response_model=List[CacheSessionInfo])
def list_cache_sessions(
    request: Request,
    admin_user: User = Depends(require_superuser),
    db: Session = Depends(get_db)
):
    """
    List all active Redis cache sessions.
    
    **Requires:** Superuser privileges
    """
    try:
        from query_refinement_module.api.dependencies import get_session_manager
        session_manager = get_session_manager()
        
        # Get all keys matching session pattern
        pattern = f"{session_manager.key_prefix}*"
        keys = session_manager.redis_client.keys(pattern)  # type: ignore
        
        sessions = []
        for key in keys:  # type: ignore
            # Extract query_id from key
            query_id_str = key.replace(session_manager.key_prefix, "")
            try:
                query_id = int(query_id_str)
            except ValueError:
                continue
            
            # Get TTL and size info
            ttl = session_manager.redis_client.ttl(key)  # type: ignore
            size = None
            try:
                # Get approximate size
                cached_data = session_manager.redis_client.get(key)  # type: ignore
                if cached_data:
                    size = len(cached_data)  # type: ignore
            except Exception:
                pass
            
            sessions.append(CacheSessionInfo(
                query_id=query_id,
                key=key,
                ttl_seconds=ttl if ttl > 0 else None,  # type: ignore
                size_bytes=size,
                last_accessed=None  # Redis doesn't track this by default
            ))
        
        # Audit the operation
        audit_service.log_from_request(
            db=db,
            request=request,
            event_type=AuditEventType.SYSTEM_MAINTENANCE,
            user=admin_user,
            severity="info",
            resource_type="cache",
            action=f"Listed {len(sessions)} cached sessions",
            status="success",
            details={"session_count": len(sessions)}
        )
        
        return sessions
        
    except Exception as e:
        logger.error(f"Failed to list cache sessions: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to access Redis cache: {str(e)}"
        )


@router.get("/cache/sessions/{query_id}")
def inspect_cache_session(
    request: Request,
    query_id: int,
    admin_user: User = Depends(require_superuser),
    db: Session = Depends(get_db)
):
    """
    Inspect a specific cached session.
    
    Returns the serialized session data from Redis.
    
    **Requires:** Superuser privileges
    """
    try:
        from query_refinement_module.api.dependencies import get_session_manager
        session_manager = get_session_manager()
        
        key = session_manager._make_key(query_id)
        exists = session_manager.redis_client.exists(key)
        
        if not exists:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"No cached session found for query_id={query_id}"
            )
        
        # Get cached data
        cached_data = session_manager.redis_client.get(key)
        ttl = session_manager.redis_client.ttl(key)
        
        # Audit the operation
        audit_service.log_from_request(
            db=db,
            request=request,
            event_type=AuditEventType.SYSTEM_MAINTENANCE,
            user=admin_user,
            severity="info",
            resource_type="cache",
            resource_id=str(query_id),
            action=f"Inspected cached session",
            status="success"
        )
        
        return {
            "query_id": query_id,
            "key": key,
            "ttl_seconds": ttl if ttl > 0 else None,
            "size_bytes": len(cached_data) if cached_data else 0,
            "data": cached_data  # Raw JSON string
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to inspect cache session: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to inspect cache: {str(e)}"
        )


@router.delete("/cache/sessions/{query_id}")
def clear_cache_session(
    request: Request,
    query_id: int,
    admin_user: User = Depends(require_superuser),
    db: Session = Depends(get_db)
):
    """
    Clear a specific cached session from Redis.
    
    Use this to force session reconstruction from database.
    
    **Requires:** Superuser privileges
    """
    try:
        from query_refinement_module.api.dependencies import get_session_manager
        session_manager = get_session_manager()
        
        deleted = session_manager.delete_session(query_id)
        
        # Audit the operation
        audit_service.log_from_request(
            db=db,
            request=request,
            event_type=AuditEventType.SYSTEM_MAINTENANCE,
            user=admin_user,
            severity="warning",
            resource_type="cache",
            resource_id=str(query_id),
            action=f"Cleared cached session",
            status="success" if deleted else "not_found",
            details={"deleted": deleted}
        )
        
        if not deleted:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"No cached session found for query_id={query_id}"
            )
        
        return {
            "success": True,
            "query_id": query_id,
            "message": "Cached session cleared successfully"
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to clear cache session: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to clear cache: {str(e)}"
        )


@router.post("/cache/flush")
def flush_cache(
    request: Request,
    admin_user: User = Depends(require_superuser),
    db: Session = Depends(get_db)
):
    """
    Flush all session cache entries from Redis.
    
    **WARNING:** This will clear all cached sessions. Use with caution.
    
    **Requires:** Superuser privileges
    """
    try:
        from query_refinement_module.api.dependencies import get_session_manager
        session_manager = get_session_manager()
        
        # Get all session keys
        pattern = f"{session_manager.key_prefix}*"
        keys = session_manager.redis_client.keys(pattern)
        deleted_count = 0
        
        if keys:
            deleted_count = session_manager.redis_client.delete(*keys)
        
        # Audit the operation
        audit_service.log_from_request(
            db=db,
            request=request,
            event_type=AuditEventType.SYSTEM_MAINTENANCE,
            user=admin_user,
            severity="critical",
            resource_type="cache",
            action=f"Flushed all cached sessions",
            status="success",
            details={"deleted_count": deleted_count}
        )
        
        return {
            "success": True,
            "deleted_count": deleted_count,
            "message": f"Flushed {deleted_count} cached session(s)"
        }
        
    except Exception as e:
        logger.error(f"Failed to flush cache: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to flush cache: {str(e)}"
        )


@router.get("/cache/stats", response_model=CacheStatsResponse)
def get_cache_stats(
    request: Request,
    admin_user: User = Depends(require_superuser),
    db: Session = Depends(get_db)
):
    """
    Get Redis cache statistics.
    
    **Requires:** Superuser privileges
    """
    try:
        from query_refinement_module.api.dependencies import get_session_manager
        session_manager = get_session_manager()
        
        # Get Redis INFO
        info = session_manager.redis_client.info()
        
        # Count session keys
        pattern = f"{session_manager.key_prefix}*"
        session_keys = session_manager.redis_client.keys(pattern)
        
        # Calculate hit rate if available
        hit_rate = None
        if 'keyspace_hits' in info and 'keyspace_misses' in info:
            hits = info['keyspace_hits']
            misses = info['keyspace_misses']
            if (hits + misses) > 0:
                hit_rate = hits / (hits + misses)
        
        stats = CacheStatsResponse(
            total_keys=info.get('db0', {}).get('keys', 0),
            session_keys=len(session_keys),
            memory_used_bytes=info.get('used_memory', None),
            memory_used_mb=info.get('used_memory', 0) / (1024 * 1024) if 'used_memory' in info else None,
            hit_rate=hit_rate,
            uptime_seconds=info.get('uptime_in_seconds', None),
            connected_clients=info.get('connected_clients', None),
            cache_ttl_seconds=session_manager.session_ttl
        )
        
        # Audit the operation
        audit_service.log_from_request(
            db=db,
            request=request,
            event_type=AuditEventType.SYSTEM_MAINTENANCE,
            user=admin_user,
            severity="info",
            resource_type="cache",
            action="Retrieved cache statistics",
            status="success"
        )
        
        return stats
        
    except Exception as e:
        logger.error(f"Failed to get cache stats: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get cache stats: {str(e)}"
        )


# ==========================================
# Integrity Validation Endpoints
# ==========================================

@router.get("/integrity/check", response_model=IntegrityCheckResponse)
def check_integrity(
    request: Request,
    query_id: Optional[int] = None,
    admin_user: User = Depends(require_superuser),
    db: Session = Depends(get_db)
):
    """
    Check DB-Redis consistency for cached sessions.
    
    Validates that Redis session state matches database records.
    Detects orphaned refinement steps and missing cache entries.
    
    **Query Parameters:**
    - query_id: Check specific query (optional). If omitted, checks all cached sessions.
    
    **Requires:** Superuser privileges
    """
    try:
        from query_refinement_module.api.dependencies import get_session_manager, get_refinement_manager
        session_manager = get_session_manager()
        manager = get_refinement_manager()
        
        issues = []
        
        # Determine queries to check
        if query_id:
            query_ids = [query_id]
        else:
            # Check all cached sessions
            pattern = f"{session_manager.key_prefix}*"
            keys = session_manager.redis_client.keys(pattern)
            query_ids = []
            for key in keys:
                try:
                    qid = int(key.replace(session_manager.key_prefix, ""))
                    query_ids.append(qid)
                except ValueError:
                    continue
        
        for qid in query_ids:
            try:
                # Get DB records
                db_query = get_query(db, query_id=qid)
                if not db_query:
                    continue
                
                db_steps = get_query_refinement_steps(db, query_id=qid)
                db_step_names = [str(s.aspect_name) for s in db_steps]
                
                # Try to load from Redis
                from query_refinement_module.schema import get_framework
                framework = get_framework(str(db_query.framework_name) if db_query.framework_name else "pico_advanced")
                redis_session = session_manager.load_session(qid, framework)
                
                redis_step_names = []
                if redis_session:
                    redis_step_names = [s.refinement_aspect.name for s in redis_session.steps]
                
                # Compare
                db_set = set(db_step_names)
                redis_set = set(redis_step_names)
                
                orphaned = db_set - redis_set  # In DB but not in Redis
                missing = redis_set - db_set   # In Redis but not in DB
                
                consistent = len(orphaned) == 0 and len(missing) == 0
                
                if not consistent:
                    issue_list = []
                    if orphaned:
                        issue_list.append(f"Orphaned steps in DB: {list(orphaned)}")
                    if missing:
                        issue_list.append(f"Missing steps in DB: {list(missing)}")
                    
                    issues.append(IntegrityCheckResult(
                        query_id=qid,
                        consistent=False,
                        issues=issue_list,
                        redis_steps=redis_step_names,
                        db_steps=db_step_names,
                        orphaned_steps=list(orphaned),
                        missing_steps=list(missing)
                    ))
            
            except Exception as e:
                logger.warning(f"Failed to check integrity for query {qid}: {e}")
                continue
        
        total_orphaned = sum(len(i.orphaned_steps) for i in issues)
        
        response = IntegrityCheckResponse(
            total_queries_checked=len(query_ids),
            consistent_queries=len(query_ids) - len(issues),
            inconsistent_queries=len(issues),
            total_orphaned_steps=total_orphaned,
            issues=issues
        )
        
        # Audit the operation
        audit_service.log_from_request(
            db=db,
            request=request,
            event_type=AuditEventType.SYSTEM_MAINTENANCE,
            user=admin_user,
            severity="info" if len(issues) == 0 else "warning",
            resource_type="integrity",
            action="Performed integrity check",
            status="success",
            details={
                "queries_checked": len(query_ids),
                "inconsistent": len(issues),
                "orphaned_steps": total_orphaned
            }
        )
        
        return response
        
    except Exception as e:
        logger.error(f"Failed to check integrity: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Integrity check failed: {str(e)}"
        )


@router.get("/integrity/orphaned-steps", response_model=OrphanedStepsResponse)
def list_orphaned_steps(
    request: Request,
    admin_user: User = Depends(require_superuser),
    db: Session = Depends(get_db)
):
    """
    List all orphaned refinement steps across all queries.
    
    Orphaned steps are DB records without corresponding Redis session entries,
    typically caused by failed cascade deletes or cache eviction issues.
    
    **Requires:** Superuser privileges
    """
    try:
        from query_refinement_module.api.dependencies import get_session_manager
        from query_refinement_module.db.models.refinement_step import RefinementStep
        session_manager = get_session_manager()
        
        # Get all refinement steps
        all_steps = db.query(RefinementStep).all()
        orphaned = []
        
        for step in all_steps:
            # Check if Redis session exists for this query
            qid = int(step.query_id) if hasattr(step.query_id, '__int__') else step.query_id  # Handle Column[int]
            exists = session_manager.session_exists(qid)
            if not exists:
                # Session not in cache - could be expired or never cached
                # We'll mark as potentially orphaned
                orphaned.append({
                    "step_id": step.id,
                    "query_id": step.query_id,
                    "aspect_name": step.aspect_name,
                    "is_complete": step.is_complete,
                    "was_skipped": step.was_skipped,
                    "reason": "No Redis session found"
                })
        
        # Audit the operation
        audit_service.log_from_request(
            db=db,
            request=request,
            event_type=AuditEventType.SYSTEM_MAINTENANCE,
            user=admin_user,
            severity="info",
            resource_type="integrity",
            action="Listed orphaned steps",
            status="success",
            details={"orphaned_count": len(orphaned)}
        )
        
        return OrphanedStepsResponse(
            total_orphaned=len(orphaned),
            orphaned_steps=orphaned
        )
        
    except Exception as e:
        logger.error(f"Failed to list orphaned steps: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to list orphaned steps: {str(e)}"
        )


@router.post("/integrity/repair", response_model=RepairResponse)
def repair_integrity(
    request: Request,
    query_id: Optional[int] = None,
    dry_run: bool = True,
    admin_user: User = Depends(require_superuser),
    db: Session = Depends(get_db)
):
    """
    Repair integrity issues by removing orphaned DB records.
    
    **Query Parameters:**
    - query_id: Repair specific query (optional). If omitted, repairs all inconsistent queries.
    - dry_run: If true (default), only reports what would be repaired without making changes.
    
    **Requires:** Superuser privileges
    """
    try:
        # First run integrity check
        check_result = check_integrity(request, query_id, admin_user, db)
        
        if check_result.inconsistent_queries == 0:
            return RepairResponse(
                repaired_queries=0,
                deleted_steps=0,
                details=[{"message": "No integrity issues found"}]
            )
        
        repaired = 0
        deleted = 0
        details = []
        
        for issue in check_result.issues:
            if issue.orphaned_steps:
                if not dry_run:
                    # Delete orphaned steps
                    deleted_count = delete_refinement_steps_by_aspects(
                        db, query_id=issue.query_id, aspect_names=issue.orphaned_steps
                    )
                    deleted += deleted_count
                    repaired += 1
                    details.append({
                        "query_id": issue.query_id,
                        "action": "deleted_orphaned_steps",
                        "deleted_steps": deleted_count,
                        "step_names": issue.orphaned_steps
                    })
                else:
                    details.append({
                        "query_id": issue.query_id,
                        "action": "would_delete_orphaned_steps",
                        "step_count": len(issue.orphaned_steps),
                        "step_names": issue.orphaned_steps
                    })
        
        # Audit the operation
        audit_service.log_from_request(
            db=db,
            request=request,
            event_type=AuditEventType.SYSTEM_MAINTENANCE,
            user=admin_user,
            severity="warning" if not dry_run else "info",
            resource_type="integrity",
            action=f"{'Dry-run' if dry_run else 'Executed'} integrity repair",
            status="success",
            details={
                "dry_run": dry_run,
                "repaired_queries": repaired,
                "deleted_steps": deleted
            }
        )
        
        return RepairResponse(
            repaired_queries=repaired if not dry_run else 0,
            deleted_steps=deleted,
            details=details
        )
        
    except Exception as e:
        logger.error(f"Failed to repair integrity: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Integrity repair failed: {str(e)}"
        )
