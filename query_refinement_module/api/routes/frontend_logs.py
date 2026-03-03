"""
Frontend logging API routes.

Endpoints for receiving and querying frontend logs from browser applications.
Integrates with Phase 2 distributed tracing and Phase 3 audit system.
"""

from datetime import datetime, timedelta, timezone
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, status, Request
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from query_refinement_module.db.database import SessionLocal
from query_refinement_module.db.models.frontend_log import FrontendLog, FrontendLogLevel, FrontendLogType
from query_refinement_module.api.routes.auth import get_current_user
from query_refinement_module.audit import audit_service
from query_refinement_module.db.models.audit_log import AuditEventType

router = APIRouter(tags=["frontend-logs"])


def get_db():
    """Database session dependency."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# ============================================================================
# Pydantic Models
# ============================================================================

class FrontendLogEntry(BaseModel):
    """Single frontend log entry."""
    timestamp: datetime
    level: str = Field(..., description="Log level: debug, info, warn, error")
    log_type: str = Field(..., description="Log type: console, error, network, performance, user_action")
    message: str
    details: Optional[dict] = None
    
    # Browser context
    url: Optional[str] = None
    user_agent: Optional[str] = None
    screen_resolution: Optional[str] = None
    viewport_size: Optional[str] = None
    
    # Distributed tracing
    request_id: Optional[str] = None
    trace_id: Optional[str] = None
    session_id: Optional[int] = None
    
    # Error fields
    error_name: Optional[str] = None
    error_stack: Optional[str] = None
    error_line: Optional[int] = None
    error_column: Optional[int] = None
    error_file: Optional[str] = None
    
    # Network fields
    network_url: Optional[str] = None
    network_method: Optional[str] = None
    network_status: Optional[int] = None
    network_duration_ms: Optional[int] = None
    
    # Performance fields
    performance_metric: Optional[str] = None
    performance_value: Optional[int] = None


class FrontendLogBatch(BaseModel):
    """Batch of frontend logs."""
    logs: List[FrontendLogEntry] = Field(..., max_length=100, description="Up to 100 logs per batch")


class FrontendLogResponse(BaseModel):
    """Frontend log response."""
    id: int
    timestamp: datetime
    client_timestamp: Optional[datetime]
    level: str
    log_type: str
    user_id: Optional[int]
    session_id: Optional[int]
    request_id: Optional[str]
    trace_id: Optional[str]
    url: Optional[str]
    message: str
    details: Optional[dict]
    error_name: Optional[str]
    error_stack: Optional[str]
    network_url: Optional[str]
    network_status: Optional[int]
    performance_metric: Optional[str]
    performance_value: Optional[int]


class FrontendLogsListResponse(BaseModel):
    """Paginated frontend logs response."""
    total: int
    page: int
    page_size: int
    logs: List[FrontendLogResponse]


class FrontendLogStats(BaseModel):
    """Frontend log statistics."""
    total_logs: int
    logs_by_level: dict
    logs_by_type: dict
    error_count: int
    unique_errors: int
    date_range: dict


# ============================================================================
# API Endpoints
# ============================================================================

@router.post("/logs/frontend", status_code=status.HTTP_201_CREATED)
def submit_frontend_logs(
    request: Request,
    batch: FrontendLogBatch,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """
    Submit a batch of frontend logs from browser.
    
    Accepts up to 100 logs per request for efficient batching.
    Automatically associates logs with authenticated user.
    """
    created_count = 0
    
    for log_entry in batch.logs:
        # Validate log level and type
        if log_entry.level not in FrontendLogLevel.all_levels():
            continue  # Skip invalid logs
        
        if log_entry.log_type not in FrontendLogType.all_types():
            continue
        
        # Create frontend log
        frontend_log = FrontendLog(
            timestamp=datetime.now(timezone.utc),
            client_timestamp=log_entry.timestamp,
            level=log_entry.level,
            log_type=log_entry.log_type,
            user_id=current_user.id,
            session_id=log_entry.session_id,
            request_id=log_entry.request_id,
            trace_id=log_entry.trace_id,
            url=log_entry.url,
            user_agent=log_entry.user_agent or request.headers.get("user-agent"),
            screen_resolution=log_entry.screen_resolution,
            viewport_size=log_entry.viewport_size,
            message=log_entry.message,
            details=log_entry.details,
            error_name=log_entry.error_name,
            error_stack=log_entry.error_stack,
            error_line=log_entry.error_line,
            error_column=log_entry.error_column,
            error_file=log_entry.error_file,
            network_url=log_entry.network_url,
            network_method=log_entry.network_method,
            network_status=log_entry.network_status,
            network_duration_ms=log_entry.network_duration_ms,
            performance_metric=log_entry.performance_metric,
            performance_value=log_entry.performance_value,
        )
        
        db.add(frontend_log)
        created_count += 1

    try:
        db.commit()
    except IntegrityError:
        # A stale session_id FK caused the batch to fail — retry with session_id stripped
        db.rollback()
        created_count = 0
        for log_entry in batch.logs:
            if log_entry.level not in FrontendLogLevel.all_levels():
                continue
            if log_entry.log_type not in FrontendLogType.all_types():
                continue
            frontend_log = FrontendLog(
                timestamp=datetime.now(timezone.utc),
                client_timestamp=log_entry.timestamp,
                level=log_entry.level,
                log_type=log_entry.log_type,
                user_id=current_user.id,
                session_id=None,  # stripped to avoid FK violation
                request_id=log_entry.request_id,
                trace_id=log_entry.trace_id,
                url=log_entry.url,
                user_agent=log_entry.user_agent or request.headers.get("user-agent"),
                screen_resolution=log_entry.screen_resolution,
                viewport_size=log_entry.viewport_size,
                message=log_entry.message,
                details=log_entry.details,
                error_name=log_entry.error_name,
                error_stack=log_entry.error_stack,
                error_line=log_entry.error_line,
                error_column=log_entry.error_column,
                error_file=log_entry.error_file,
                network_url=log_entry.network_url,
                network_method=log_entry.network_method,
                network_status=log_entry.network_status,
                network_duration_ms=log_entry.network_duration_ms,
                performance_metric=log_entry.performance_metric,
                performance_value=log_entry.performance_value,
            )
            db.add(frontend_log)
            created_count += 1
        db.commit()
    
    # Audit the frontend log submission
    audit_service.log_from_request(
        db=db,
        request=request,
        event_type=AuditEventType.DATA_VIEW,  # Using existing event type
        user=current_user,
        action=f"Submitted {created_count} frontend logs",
        status="success",
        details={
            "log_count": created_count,
            "log_levels": [log.level for log in batch.logs],
            "log_types": list(set(log.log_type for log in batch.logs))
        }
    )
    
    return {
        "status": "success",
        "received": created_count,
        "message": f"Successfully stored {created_count} frontend logs"
    }


@router.get("/logs/frontend", response_model=FrontendLogsListResponse)
def get_frontend_logs(
    request: Request,
    page: int = 1,
    page_size: int = 50,
    level: Optional[str] = None,
    log_type: Optional[str] = None,
    session_id: Optional[int] = None,
    request_id: Optional[str] = None,
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """
    Query frontend logs with filters.
    
    Users can only see their own logs. Supports pagination and filtering
    by level, type, session, request_id, and date range.
    """
    # Validate pagination
    if page < 1:
        page = 1
    if page_size < 1 or page_size > 500:
        page_size = 50
    
    # Build query
    query = db.query(FrontendLog).filter(FrontendLog.user_id == current_user.id)
    
    # Apply filters
    if level:
        query = query.filter(FrontendLog.level == level)
    
    if log_type:
        query = query.filter(FrontendLog.log_type == log_type)
    
    if session_id:
        query = query.filter(FrontendLog.session_id == session_id)
    
    if request_id:
        query = query.filter(FrontendLog.request_id == request_id)
    
    if start_date:
        query = query.filter(FrontendLog.timestamp >= start_date)
    
    if end_date:
        query = query.filter(FrontendLog.timestamp <= end_date)
    
    # Get total count
    total = query.count()
    
    # Apply pagination and ordering
    logs = query.order_by(FrontendLog.timestamp.desc()) \
                .offset((page - 1) * page_size) \
                .limit(page_size) \
                .all()
    
    # Audit the query
    audit_service.log_from_request(
        db=db,
        request=request,
        event_type=AuditEventType.DATA_VIEW,
        user=current_user,
        action="Queried frontend logs",
        status="success",
        details={
            "page": page,
            "page_size": page_size,
            "filters": {
                "level": level,
                "log_type": log_type,
                "session_id": session_id,
                "request_id": request_id
            },
            "result_count": len(logs)
        }
    )
    
    return FrontendLogsListResponse(
        total=total,
        page=page,
        page_size=page_size,
        logs=[FrontendLogResponse(**log.to_dict()) for log in logs]
    )


@router.get("/logs/frontend/stats", response_model=FrontendLogStats)
def get_frontend_log_stats(
    request: Request,
    days: int = 7,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """
    Get frontend log statistics.
    
    Returns aggregated statistics for the specified time period.
    """
    if days < 1 or days > 365:
        days = 7
    
    start_date = datetime.now(timezone.utc) - timedelta(days=days)
    
    # Base query for user's logs in date range
    base_query = db.query(FrontendLog).filter(
        FrontendLog.user_id == current_user.id,
        FrontendLog.timestamp >= start_date
    )
    
    # Total logs
    total_logs = base_query.count()
    
    # Logs by level
    logs_by_level = {}
    for level in FrontendLogLevel.all_levels():
        count = base_query.filter(FrontendLog.level == level).count()
        if count > 0:
            logs_by_level[level] = count
    
    # Logs by type
    logs_by_type = {}
    for log_type in FrontendLogType.all_types():
        count = base_query.filter(FrontendLog.log_type == log_type).count()
        if count > 0:
            logs_by_type[log_type] = count
    
    # Error statistics
    error_count = base_query.filter(FrontendLog.level == FrontendLogLevel.ERROR).count()
    unique_errors = base_query.filter(
        FrontendLog.level == FrontendLogLevel.ERROR
    ).with_entities(FrontendLog.error_name).distinct().count()
    
    # Audit the stats query
    audit_service.log_from_request(
        db=db,
        request=request,
        event_type=AuditEventType.DATA_VIEW,
        user=current_user,
        action="Viewed frontend log statistics",
        status="success",
        details={"days": days, "total_logs": total_logs}
    )
    
    return FrontendLogStats(
        total_logs=total_logs,
        logs_by_level=logs_by_level,
        logs_by_type=logs_by_type,
        error_count=error_count,
        unique_errors=unique_errors,
        date_range={
            "start": start_date.isoformat(),
            "end": datetime.now(timezone.utc).isoformat()
        }
    )


@router.get("/logs/frontend/errors")
def get_frontend_errors(
    request: Request,
    page: int = 1,
    page_size: int = 50,
    days: int = 7,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """
    Get frontend errors with grouping by error type.
    
    Returns unique errors with occurrence counts for debugging.
    """
    if page < 1:
        page = 1
    if page_size < 1 or page_size > 100:
        page_size = 50
    if days < 1 or days > 365:
        days = 7
    
    start_date = datetime.now(timezone.utc) - timedelta(days=days)
    
    # Query errors grouped by error_name and error_file
    errors = db.query(
        FrontendLog.error_name,
        FrontendLog.error_file,
        FrontendLog.error_line,
        FrontendLog.message,
        func.count(FrontendLog.id).label('count'),
        func.max(FrontendLog.timestamp).label('last_occurrence')
    ).filter(
        FrontendLog.user_id == current_user.id,
        FrontendLog.level == FrontendLogLevel.ERROR,
        FrontendLog.timestamp >= start_date
    ).group_by(
        FrontendLog.error_name,
        FrontendLog.error_file,
        FrontendLog.error_line,
        FrontendLog.message
    ).order_by(
        func.count(FrontendLog.id).desc()
    ).offset((page - 1) * page_size).limit(page_size).all()
    
    # Get total unique errors
    total = db.query(
        func.count(func.distinct(FrontendLog.error_name))
    ).filter(
        FrontendLog.user_id == current_user.id,
        FrontendLog.level == FrontendLogLevel.ERROR,
        FrontendLog.timestamp >= start_date
    ).scalar()
    
    # Audit the error query
    audit_service.log_from_request(
        db=db,
        request=request,
        event_type=AuditEventType.DATA_VIEW,
        user=current_user,
        action="Queried frontend errors",
        status="success",
        details={"days": days, "error_count": len(errors)}
    )
    
    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "errors": [
            {
                "error_name": error.error_name,
                "error_file": error.error_file,
                "error_line": error.error_line,
                "message": error.message,
                "count": error.count,
                "last_occurrence": error.last_occurrence.isoformat() if error.last_occurrence else None
            }
            for error in errors
        ]
    }


@router.get("/logs/frontend/trace/{request_id}")
def trace_frontend_logs(
    request_id: str,
    request: Request,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """
    Get all frontend logs for a specific request_id.
    
    Integrates with Phase 2 distributed tracing to show all frontend
    events associated with a specific backend request.
    """
    logs = db.query(FrontendLog).filter(
        FrontendLog.user_id == current_user.id,
        FrontendLog.request_id == request_id
    ).order_by(FrontendLog.timestamp.asc()).all()
    
    # Audit the trace query
    audit_service.log_from_request(
        db=db,
        request=request,
        event_type=AuditEventType.DATA_VIEW,
        user=current_user,
        resource_type="frontend_trace",
        action=f"Traced frontend logs for request: {request_id}",
        status="success",
        details={"request_id": request_id, "log_count": len(logs)}
    )
    
    return [FrontendLogResponse(**log.to_dict()) for log in logs]
