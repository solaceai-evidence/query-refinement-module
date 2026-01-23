"""
Audit log API routes for compliance and security monitoring.

Provides endpoints for:
- Querying audit logs with filters
- Exporting audit data (CSV, JSON)
- Compliance reporting
- User activity tracking
- Request tracing
"""
from fastapi import APIRouter, Depends, HTTPException, status, Query, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from sqlalchemy import and_
from typing import List, Optional
from datetime import datetime, timedelta
import csv
import io
import json

from query_refinement_module.db.session import get_db
from query_refinement_module.db.models.audit_log import AuditLog, AuditEventType, AuditSeverity
from query_refinement_module.api.auth import get_current_user
from query_refinement_module.audit import audit_service
from pydantic import BaseModel, Field


router = APIRouter(prefix="/audit", tags=["Audit Logs"])


# ==========================================
# Pydantic Schemas
# ==========================================

class AuditLogResponse(BaseModel):
    """Audit log entry response schema."""
    id: int
    event_type: str
    severity: str
    timestamp: datetime
    user_id: Optional[int] = None
    username: Optional[str] = None
    request_id: Optional[str] = None
    trace_id: Optional[str] = None
    ip_address: Optional[str] = None
    endpoint: Optional[str] = None
    http_method: Optional[str] = None
    resource_type: Optional[str] = None
    resource_id: Optional[str] = None
    action: Optional[str] = None
    status: Optional[str] = None
    details: Optional[dict] = None
    error_message: Optional[str] = None
    
    class Config:
        from_attributes = True


class AuditLogsResponse(BaseModel):
    """Paginated audit logs response."""
    total: int
    page: int
    page_size: int
    logs: List[AuditLogResponse]


class AuditStatsResponse(BaseModel):
    """Audit statistics response."""
    total_events: int
    events_by_type: dict
    events_by_severity: dict
    unique_users: int
    date_range: dict


# ==========================================
# Audit Query Endpoints
# ==========================================

@router.get("/logs", response_model=AuditLogsResponse)
def get_audit_logs(
    request: Request,
    current_user = Depends(get_current_user),
    db: Session = Depends(get_db),
    # Pagination
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(50, ge=1, le=500, description="Items per page"),
    # Filters
    event_type: Optional[str] = Query(None, description="Filter by event type"),
    severity: Optional[str] = Query(None, description="Filter by severity"),
    user_id: Optional[int] = Query(None, description="Filter by user ID"),
    resource_type: Optional[str] = Query(None, description="Filter by resource type"),
    resource_id: Optional[str] = Query(None, description="Filter by resource ID"),
    request_id: Optional[str] = Query(None, description="Filter by request ID"),
    start_date: Optional[datetime] = Query(None, description="Start date (ISO format)"),
    end_date: Optional[datetime] = Query(None, description="End date (ISO format)"),
):
    """
    Query audit logs with filters and pagination.
    
    Users can only see their own audit logs unless they have admin privileges.
    """
    # Build query
    query = db.query(AuditLog)
    
    # Users can only see their own logs (unless admin - TODO: implement admin check)
    query = query.filter(AuditLog.user_id == current_user.id)
    
    # Apply filters
    if event_type:
        query = query.filter(AuditLog.event_type == event_type)
    if severity:
        query = query.filter(AuditLog.severity == severity)
    if user_id and user_id == current_user.id:  # Security: Only own user_id
        query = query.filter(AuditLog.user_id == user_id)
    if resource_type:
        query = query.filter(AuditLog.resource_type == resource_type)
    if resource_id:
        query = query.filter(AuditLog.resource_id == resource_id)
    if request_id:
        query = query.filter(AuditLog.request_id == request_id)
    if start_date:
        query = query.filter(AuditLog.timestamp >= start_date)
    if end_date:
        query = query.filter(AuditLog.timestamp <= end_date)
    
    # Get total count
    total = query.count()
    
    # Apply pagination
    offset = (page - 1) * page_size
    logs = query.order_by(AuditLog.timestamp.desc()).offset(offset).limit(page_size).all()
    
    # Audit this data access
    audit_service.log_from_request(
        db=db,
        request=request,
        event_type=AuditEventType.DATA_VIEW,
        user=current_user,
        resource_type="audit_logs",
        action="Queried audit logs",
        status="success",
        details={
            "page": page,
            "page_size": page_size,
            "filters": {
                "event_type": event_type,
                "severity": severity,
                "resource_type": resource_type
            },
            "result_count": len(logs)
        }
    )
    
    return AuditLogsResponse(
        total=total,
        page=page,
        page_size=page_size,
        logs=[AuditLogResponse.from_orm(log) for log in logs]
    )


@router.get("/logs/{audit_id}", response_model=AuditLogResponse)
def get_audit_log(
    request: Request,
    audit_id: int,
    current_user = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get a specific audit log entry by ID."""
    log = db.query(AuditLog).filter(AuditLog.id == audit_id).first()
    
    if not log:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Audit log not found")
    
    # Security: Users can only see their own logs
    if log.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")
    
    # Audit this access
    audit_service.log_from_request(
        db=db,
        request=request,
        event_type=AuditEventType.DATA_VIEW,
        user=current_user,
        resource_type="audit_log",
        resource_id=str(audit_id),
        action="Viewed audit log detail",
        status="success"
    )
    
    return log


@router.get("/stats", response_model=AuditStatsResponse)
def get_audit_stats(
    request: Request,
    current_user = Depends(get_current_user),
    db: Session = Depends(get_db),
    days: int = Query(30, ge=1, le=365, description="Number of days to analyze")
):
    """
    Get audit statistics for the current user.
    
    Returns event counts by type, severity, and time period.
    """
    start_date = datetime.utcnow() - timedelta(days=days)
    
    # Query user's audit logs
    logs = db.query(AuditLog).filter(
        and_(
            AuditLog.user_id == current_user.id,
            AuditLog.timestamp >= start_date
        )
    ).all()
    
    # Calculate statistics
    total_events = len(logs)
    
    events_by_type = {}
    for log in logs:
        events_by_type[log.event_type] = events_by_type.get(log.event_type, 0) + 1
    
    events_by_severity = {}
    for log in logs:
        events_by_severity[log.severity] = events_by_severity.get(log.severity, 0) + 1
    
    # Unique users (always 1 for non-admin users)
    unique_users = 1
    
    # Audit this request
    audit_service.log_from_request(
        db=db,
        request=request,
        event_type=AuditEventType.DATA_VIEW,
        user=current_user,
        resource_type="audit_stats",
        action="Viewed audit statistics",
        status="success",
        details={"days": days, "total_events": total_events}
    )
    
    return AuditStatsResponse(
        total_events=total_events,
        events_by_type=events_by_type,
        events_by_severity=events_by_severity,
        unique_users=unique_users,
        date_range={
            "start": start_date.isoformat(),
            "end": datetime.utcnow().isoformat()
        }
    )


@router.get("/event-types")
def get_event_types(
    current_user = Depends(get_current_user)
):
    """Get list of all audit event types."""
    return {
        "event_types": AuditEventType.all_types(),
        "severity_levels": [
            AuditSeverity.INFO,
            AuditSeverity.WARNING,
            AuditSeverity.ERROR,
            AuditSeverity.CRITICAL
        ]
    }


@router.get("/trace/{request_id}", response_model=List[AuditLogResponse])
def trace_request(
    request: Request,
    request_id: str,
    current_user = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Trace all audit events for a specific request_id.
    
    Useful for debugging and investigating issues across the entire request lifecycle.
    """
    # Query all audit logs for this request_id
    logs = db.query(AuditLog).filter(
        and_(
            AuditLog.request_id == request_id,
            AuditLog.user_id == current_user.id  # Security: Only own logs
        )
    ).order_by(AuditLog.timestamp.asc()).all()
    
    if not logs:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No audit logs found for this request_id"
        )
    
    # Audit this trace request
    audit_service.log_from_request(
        db=db,
        request=request,
        event_type=AuditEventType.DATA_VIEW,
        user=current_user,
        resource_type="audit_trace",
        action=f"Traced request: {request_id}",
        status="success",
        details={"request_id": request_id, "events_found": len(logs)}
    )
    
    return logs


# ==========================================
# Export & Compliance Endpoints
# ==========================================

@router.get("/export/csv")
def export_logs_csv(
    request: Request,
    current_user = Depends(get_current_user),
    db: Session = Depends(get_db),
    start_date: Optional[datetime] = Query(None, description="Start date (ISO format)"),
    end_date: Optional[datetime] = Query(None, description="End date (ISO format)"),
    event_type: Optional[str] = Query(None, description="Filter by event type"),
):
    """
    Export user's audit logs as CSV for compliance reporting.
    
    Returns a downloadable CSV file with all audit log fields.
    """
    # Build query
    query = db.query(AuditLog).filter(AuditLog.user_id == current_user.id)
    
    # Apply filters
    if start_date:
        query = query.filter(AuditLog.timestamp >= start_date)
    if end_date:
        query = query.filter(AuditLog.timestamp <= end_date)
    if event_type:
        query = query.filter(AuditLog.event_type == event_type)
    
    logs = query.order_by(AuditLog.timestamp.desc()).all()
    
    # Create CSV in memory
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=[
        'id', 'event_type', 'severity', 'timestamp', 'user_id', 'username',
        'request_id', 'trace_id', 'ip_address', 'user_agent', 'endpoint',
        'http_method', 'resource_type', 'resource_id', 'action', 'status',
        'error_message', 'error_code'
    ])
    
    writer.writeheader()
    for log in logs:
        writer.writerow({
            'id': log.id,
            'event_type': log.event_type,
            'severity': log.severity,
            'timestamp': log.timestamp.isoformat() if log.timestamp is not None else '',
            'user_id': log.user_id or '',
            'username': log.username or '',
            'request_id': log.request_id or '',
            'trace_id': log.trace_id or '',
            'ip_address': log.ip_address or '',
            'user_agent': log.user_agent or '',
            'endpoint': log.endpoint or '',
            'http_method': log.http_method or '',
            'resource_type': log.resource_type or '',
            'resource_id': log.resource_id or '',
            'action': log.action or '',
            'status': log.status or '',
            'error_message': log.error_message or '',
            'error_code': log.error_code or '',
        })
    
    # Audit this export
    audit_service.log_from_request(
        db=db,
        request=request,
        event_type=AuditEventType.DATA_EXPORT,
        user=current_user,
        resource_type="audit_logs",
        action="Exported audit logs (CSV)",
        status="success",
        details={
            "format": "csv",
            "records_exported": len(logs),
            "start_date": start_date.isoformat() if start_date else None,
            "end_date": end_date.isoformat() if end_date else None
        }
    )
    
    # Return as downloadable CSV
    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={
            "Content-Disposition": f"attachment; filename=audit_logs_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.csv"
        }
    )


@router.get("/export/json")
def export_logs_json(
    request: Request,
    current_user = Depends(get_current_user),
    db: Session = Depends(get_db),
    start_date: Optional[datetime] = Query(None, description="Start date (ISO format)"),
    end_date: Optional[datetime] = Query(None, description="End date (ISO format)"),
    event_type: Optional[str] = Query(None, description="Filter by event type"),
):
    """
    Export user's audit logs as JSON for compliance reporting.
    
    Returns a downloadable JSON file with complete audit data including details.
    """
    # Build query
    query = db.query(AuditLog).filter(AuditLog.user_id == current_user.id)
    
    # Apply filters
    if start_date:
        query = query.filter(AuditLog.timestamp >= start_date)
    if end_date:
        query = query.filter(AuditLog.timestamp <= end_date)
    if event_type:
        query = query.filter(AuditLog.event_type == event_type)
    
    logs = query.order_by(AuditLog.timestamp.desc()).all()
    
    # Convert to dict
    logs_data = [log.to_dict() for log in logs]
    
    export_data = {
        "export_date": datetime.utcnow().isoformat(),
        "user_id": current_user.id,
        "username": current_user.username,
        "total_records": len(logs),
        "filters": {
            "start_date": start_date.isoformat() if start_date else None,
            "end_date": end_date.isoformat() if end_date else None,
            "event_type": event_type
        },
        "logs": logs_data
    }
    
    # Audit this export
    audit_service.log_from_request(
        db=db,
        request=request,
        event_type=AuditEventType.DATA_EXPORT,
        user=current_user,
        resource_type="audit_logs",
        action="Exported audit logs (JSON)",
        status="success",
        details={
            "format": "json",
            "records_exported": len(logs),
            "start_date": start_date.isoformat() if start_date else None,
            "end_date": end_date.isoformat() if end_date else None
        }
    )
    
    # Return as downloadable JSON
    json_str = json.dumps(export_data, indent=2)
    return StreamingResponse(
        iter([json_str]),
        media_type="application/json",
        headers={
            "Content-Disposition": f"attachment; filename=audit_logs_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.json"
        }
    )


@router.delete("/cleanup")
def cleanup_expired_logs(
    request: Request,
    current_user = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Clean up expired audit logs based on retention policy.
    
    Deletes logs that have passed their retention_until date.
    This is typically run as a scheduled job, but can be manually triggered.
    """
    # Find expired logs for current user
    now = datetime.utcnow()
    expired_logs = db.query(AuditLog).filter(
        and_(
            AuditLog.user_id == current_user.id,
            AuditLog.retention_until.isnot(None),  # type: ignore
            AuditLog.retention_until < now  # type: ignore
        )
    ).all()
    
    count = len(expired_logs)
    
    # Delete expired logs
    for log in expired_logs:
        db.delete(log)
    
    db.commit()
    
    # Audit this cleanup operation
    audit_service.log_from_request(
        db=db,
        request=request,
        event_type=AuditEventType.SYSTEM_MAINTENANCE,
        user=current_user,
        resource_type="audit_logs",
        action="Cleaned up expired audit logs",
        status="success",
        details={
            "logs_deleted": count,
            "retention_cutoff": now.isoformat()
        }
    )
    
    return {
        "message": f"Successfully deleted {count} expired audit log(s)",
        "deleted_count": count
    }
