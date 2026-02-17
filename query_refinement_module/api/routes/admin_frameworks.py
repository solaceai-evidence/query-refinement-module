"""
Admin endpoints for framework management and monitoring.

Provides runtime validation, reload, and usage statistics for refinement frameworks.
"""
from typing import List, Dict, Any, Optional
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy import func
from datetime import datetime, timedelta
from pydantic import BaseModel

from query_refinement_module.api.auth import get_current_user
from query_refinement_module.api.routes.admin import require_superuser
from query_refinement_module.db.models.user import User
from query_refinement_module.db.models.query_session import QuerySession
from query_refinement_module.db.models.query import Query
from query_refinement_module.db.session import get_db
from query_refinement_module.db.crud import (
    get_user_by_id,
    assign_user_framework_access,
    revoke_user_framework_access,
    get_user_framework_names,
)
from query_refinement_module.schema.registry import (
    list_frameworks, 
    get_framework, 
    reload_from_env
)
from query_refinement_module.tracing import get_request_id
import os
from pathlib import Path

router = APIRouter(prefix="/api/admin/frameworks", tags=["admin", "frameworks"])


class FrameworkAccessRequest(BaseModel):
    framework_name: str


class FrameworkAccessResponse(BaseModel):
    user_id: int
    framework_names: List[str]


@router.get("/users/{user_id}/access", response_model=FrameworkAccessResponse)
async def get_user_framework_access(
    user_id: int,
    current_user: User = Depends(require_superuser),
    db: Session = Depends(get_db),
):
    """List framework assignments for a user (admin only)."""
    user = get_user_by_id(db, user_id)
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    return FrameworkAccessResponse(
        user_id=user_id,
        framework_names=sorted(get_user_framework_names(db, user_id)),
    )


@router.post("/users/{user_id}/access", response_model=FrameworkAccessResponse)
async def assign_framework_to_user(
    user_id: int,
    request: FrameworkAccessRequest,
    current_user: User = Depends(require_superuser),
    db: Session = Depends(get_db),
):
    """Assign one framework to a user (admin only)."""
    user = get_user_by_id(db, user_id)
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    available_frameworks = set(list_frameworks())
    framework_name = request.framework_name.strip()
    if framework_name not in available_frameworks:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Framework '{framework_name}' not found",
        )

    assign_user_framework_access(db, user_id=user_id, framework_name=framework_name)
    return FrameworkAccessResponse(
        user_id=user_id,
        framework_names=sorted(get_user_framework_names(db, user_id)),
    )


@router.delete("/users/{user_id}/access/{framework_name}", response_model=FrameworkAccessResponse)
async def revoke_framework_from_user(
    user_id: int,
    framework_name: str,
    current_user: User = Depends(require_superuser),
    db: Session = Depends(get_db),
):
    """Revoke one framework from a user (admin only)."""
    user = get_user_by_id(db, user_id)
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    revoke_user_framework_access(db, user_id=user_id, framework_name=framework_name)
    return FrameworkAccessResponse(
        user_id=user_id,
        framework_names=sorted(get_user_framework_names(db, user_id)),
    )


@router.get("/list", response_model=List[Dict[str, Any]])
async def list_all_frameworks(
    current_user: User = Depends(require_superuser)
):
    """
    List all available refinement frameworks.
    
    **Admin Only**
    
    Returns:
        List of frameworks with:
        - name: Framework identifier
        - aspects_count: Number of refinement aspects
    """
    framework_names = list_frameworks()
    
    result = []
    for fw_name in framework_names:
        try:
            aspects = get_framework(fw_name)
            result.append({
                "name": fw_name,
                "aspects_count": len(aspects) if aspects else 0,
            })
        except Exception as e:
            result.append({
                "name": fw_name,
                "aspects_count": 0,
                "error": str(e)
            })
    
    return result


@router.get("/usage-stats", response_model=Dict[str, Any])
async def get_framework_usage_stats(
    days: int = 30,
    current_user: User = Depends(require_superuser),
    db: Session = Depends(get_db)
):
    """
    Get framework usage statistics.
    
    **Admin Only**
    
    Args:
        days: Number of days to analyze (default: 30)
    
    Returns:
        - total_sessions: Total sessions created
        - by_framework: Usage count per framework
        - default_framework_usage: Sessions using default framework
        - completion_rates: Completion rate by framework
        - avg_queries_per_session: Average queries per session by framework
    """
    cutoff_date = datetime.utcnow() - timedelta(days=days)
    
    # Total sessions in period
    total_sessions = db.query(func.count(QuerySession.id))\
        .filter(QuerySession.created_at >= cutoff_date)\
        .scalar() or 0
    
    # Usage by framework
    framework_usage = db.query(
        QuerySession.framework_name,
        func.count(QuerySession.id).label('count')
    ).filter(QuerySession.created_at >= cutoff_date)\
     .group_by(QuerySession.framework_name)\
     .all()
    
    by_framework = {
        fw_name or 'default': count 
        for fw_name, count in framework_usage
    }
    
    # Completion rates (sessions with ended_at set)
    completion_stats = db.query(
        QuerySession.framework_name,
        func.count(QuerySession.id).label('total'),
        func.sum(func.case((QuerySession.ended_at.isnot(None), 1), else_=0)).label('completed')
    ).filter(QuerySession.created_at >= cutoff_date)\
     .group_by(QuerySession.framework_name)\
     .all()
    
    completion_rates = {}
    for fw_name, total, completed in completion_stats:
        fw_key = fw_name or 'default'
        completion_rates[fw_key] = {
            "total": total,
            "completed": completed or 0,
            "rate": round((completed or 0) / total * 100, 2) if total > 0 else 0.0
        }
    
    # Average queries per session
    queries_per_session = db.query(
        QuerySession.framework_name,
        func.count(Query.id).label('query_count'),
        func.count(func.distinct(QuerySession.id)).label('session_count')
    ).join(Query, Query.session_id == QuerySession.id)\
     .filter(QuerySession.created_at >= cutoff_date)\
     .group_by(QuerySession.framework_name)\
     .all()
    
    avg_queries = {}
    for fw_name, query_count, session_count in queries_per_session:
        fw_key = fw_name or 'default'
        avg_queries[fw_key] = round(query_count / session_count, 2) if session_count > 0 else 0.0
    
    return {
        "period_days": days,
        "total_sessions": total_sessions,
        "by_framework": by_framework,
        "completion_rates": completion_rates,
        "avg_queries_per_session": avg_queries,
        "unique_frameworks_used": len(by_framework)
    }


@router.get("/{framework_name}/validate", response_model=Dict[str, Any])
async def validate_framework(
    framework_name: str,
    current_user: User = Depends(require_superuser)
):
    """
    Validate a framework's schema and structure.
    
    **Admin Only**
    
    Args:
        framework_name: Name of framework to validate
    
    Returns:
        - valid: Whether framework is valid
        - framework_name: Name validated
        - aspects_count: Number of aspects found
        - issues: List of validation issues (if any)
        - aspects: List of aspect details
    """
    issues = []
    
    try:
        # Try to load framework
        aspects = get_framework(framework_name)
        
        if not aspects:
            return {
                "valid": False,
                "framework_name": framework_name,
                "aspects_count": 0,
                "issues": [f"Framework '{framework_name}' not found"],
                "aspects": []
            }
        
        # Validate each aspect
        aspect_details = []
        for aspect in aspects:
            aspect_info = {
                "id": aspect.id,
                "name": aspect.name,
                "description": aspect.description[:100] + "..." if len(aspect.description) > 100 else aspect.description,
                "has_system_prompt": bool(aspect.system_prompt),
                "has_user_prompt": bool(aspect.user_prompt_template),
                "valid": True,
                "issues": []
            }
            
            # Validation checks
            if not aspect.id:
                aspect_info["issues"].append("Missing aspect ID")
                aspect_info["valid"] = False
                
            if not aspect.name:
                aspect_info["issues"].append("Missing aspect name")
                aspect_info["valid"] = False
                
            if not aspect.system_prompt:
                aspect_info["issues"].append("Missing system prompt")
                aspect_info["valid"] = False
                
            if not aspect.user_prompt_template:
                aspect_info["issues"].append("Missing user prompt template")
                aspect_info["valid"] = False
            
            aspect_details.append(aspect_info)
            
            if not aspect_info["valid"]:
                issues.extend([f"{aspect.id}: {issue}" for issue in aspect_info["issues"]])
        
        return {
            "valid": len(issues) == 0,
            "framework_name": framework_name,
            "aspects_count": len(aspects),
            "issues": issues,
            "aspects": aspect_details
        }
        
    except Exception as e:
        return {
            "valid": False,
            "framework_name": framework_name,
            "aspects_count": 0,
            "issues": [f"Validation error: {str(e)}"],
            "aspects": []
        }


@router.post("/reload", response_model=Dict[str, Any])
async def reload_framework_cache(
    current_user: User = Depends(require_superuser)
):
    """
    Reload all frameworks from disk into memory cache.
    
    **Admin Only**
    
    Useful after:
    - Updating framework YAML files
    - Adding new frameworks
    - Fixing framework definitions
    
    Returns:
        - reloaded: Whether reload was successful
        - frameworks_count: Number of frameworks loaded
        - frameworks: List of framework names
    """
    request_id = get_request_id()
    
    try:
        # Reload frameworks from environment path
        loaded_frameworks = reload_from_env(raise_on_error=True)
        
        # Get list of loaded framework names
        framework_names = list(loaded_frameworks.keys())
        
        return {
            "reloaded": True,
            "frameworks_count": len(framework_names),
            "frameworks": framework_names,
            "request_id": request_id,
            "timestamp": datetime.utcnow().isoformat()
        }
        
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to reload frameworks: {str(e)}"
        )


@router.get("/{framework_name}/details", response_model=Dict[str, Any])
async def get_framework_details(
    framework_name: str,
    current_user: User = Depends(require_superuser)
):
    """
    Get detailed information about a specific framework.
    
    **Admin Only**
    
    Args:
        framework_name: Name of framework
    
    Returns:
        - name: Framework name
        - aspects: Detailed list of all aspects
        - total_aspects: Count of aspects
        - file_info: File system information
    """
    frameworks = list_frameworks()
    framework_info = next((fw for fw in frameworks if fw.name == framework_name), None)
    
    if not framework_info:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Framework '{framework_name}' not found"
        )
    
    aspects = get_framework(framework_name)
    
    if not aspects:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Failed to load framework '{framework_name}'"
        )
    
    # Get file info
    file_path = Path(framework_info.file_path)
    file_info = {
        "path": str(file_path),
        "exists": file_path.exists(),
        "size_bytes": file_path.stat().st_size if file_path.exists() else 0,
        "modified": datetime.fromtimestamp(file_path.stat().st_mtime).isoformat() if file_path.exists() else None
    }
    
    # Detailed aspect information
    aspect_details = []
    for aspect in aspects:
        aspect_details.append({
            "id": aspect.id,
            "name": aspect.name,
            "description": aspect.description,
            "system_prompt_length": len(aspect.system_prompt) if aspect.system_prompt else 0,
            "user_prompt_length": len(aspect.user_prompt_template) if aspect.user_prompt_template else 0,
            "has_examples": bool(getattr(aspect, 'examples', None)),
            "synthesis_instructions_length": len(aspect.synthesis_instructions) if aspect.synthesis_instructions else 0
        })
    
    return {
        "name": framework_name,
        "description": framework_info.description,
        "total_aspects": len(aspects),
        "aspects": aspect_details,
        "file_info": file_info
    }


@router.get("/{framework_name}/usage", response_model=Dict[str, Any])
async def get_framework_specific_usage(
    framework_name: str,
    days: int = 30,
    current_user: User = Depends(require_superuser),
    db: Session = Depends(get_db)
):
    """
    Get usage statistics for a specific framework.
    
    **Admin Only**
    
    Args:
        framework_name: Name of framework
        days: Number of days to analyze (default: 30)
    
    Returns:
        - framework_name: Framework name
        - total_sessions: Sessions using this framework
        - total_queries: Queries in these sessions
        - completed_sessions: Sessions marked as ended
        - active_sessions: Currently active sessions
        - average_duration_minutes: Average session duration
    """
    cutoff_date = datetime.utcnow() - timedelta(days=days)
    
    # Query for sessions using this framework
    sessions = db.query(QuerySession)\
        .filter(QuerySession.framework_name == framework_name)\
        .filter(QuerySession.created_at >= cutoff_date)\
        .all()
    
    if not sessions:
        return {
            "framework_name": framework_name,
            "period_days": days,
            "total_sessions": 0,
            "total_queries": 0,
            "completed_sessions": 0,
            "active_sessions": 0,
            "average_duration_minutes": 0.0,
            "users_count": 0
        }
    
    total_sessions = len(sessions)
    completed_sessions = sum(1 for s in sessions if s.ended_at)
    active_sessions = total_sessions - completed_sessions
    
    # Calculate average duration for completed sessions
    durations = []
    for session in sessions:
        if session.ended_at and session.created_at:
            duration = (session.ended_at - session.created_at).total_seconds() / 60
            durations.append(duration)
    
    avg_duration = round(sum(durations) / len(durations), 2) if durations else 0.0
    
    # Count queries
    session_ids = [s.id for s in sessions]
    total_queries = db.query(func.count(Query.id))\
        .filter(Query.session_id.in_(session_ids))\
        .scalar() or 0
    
    # Count unique users
    users_count = db.query(func.count(func.distinct(QuerySession.user_id)))\
        .filter(QuerySession.id.in_(session_ids))\
        .scalar() or 0
    
    return {
        "framework_name": framework_name,
        "period_days": days,
        "total_sessions": total_sessions,
        "total_queries": total_queries,
        "completed_sessions": completed_sessions,
        "active_sessions": active_sessions,
        "average_duration_minutes": avg_duration,
        "users_count": users_count
    }
