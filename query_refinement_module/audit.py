"""
Audit logging service for security, compliance, and debugging.

Provides centralized audit logging with:
- Automatic request context enrichment (request_id, trace_id)
- User context extraction from FastAPI dependencies
- Structured event logging with standardized types
- HTTP request metadata capture
- Async logging for performance

Usage:
    from query_refinement_module.audit import audit_service
    from query_refinement_module.db.models.audit_log import AuditEventType
    
    # Simple audit log
    audit_service.log(
        event_type=AuditEventType.QUERY_CREATE,
        user_id=user.id,
        resource_type="query",
        resource_id=str(query.id),
        details={"query_text": query.text}
    )
    
    # With FastAPI request context
    @router.post("/queries")
    def create_query(request: Request, current_user=Depends(get_current_user)):
        query = ...
        audit_service.log_from_request(
            request=request,
            event_type=AuditEventType.QUERY_CREATE,
            user=current_user,
            resource_type="query",
            resource_id=str(query.id)
        )
"""
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, Any
from fastapi import Request

from sqlalchemy.orm import Session

from query_refinement_module.db.models.audit_log import (
    AuditLog,
    AuditEventType,
    AuditSeverity
)
from query_refinement_module.tracing import get_request_id, get_trace_id


logger = logging.getLogger(__name__)


class AuditService:
    """
    Centralized service for audit logging.
    
    Handles all audit log creation with automatic context enrichment.
    """
    
    # Default retention periods (days) by event severity
    RETENTION_POLICIES = {
        AuditSeverity.INFO: 90,      # 3 months
        AuditSeverity.WARNING: 180,  # 6 months
        AuditSeverity.ERROR: 365,    # 1 year
        AuditSeverity.CRITICAL: 2555  # 7 years (compliance requirement)
    }
    
    def log(
        self,
        db: Session,
        event_type: str,
        severity: str = AuditSeverity.INFO,
        user_id: Optional[int] = None,
        username: Optional[str] = None,
        resource_type: Optional[str] = None,
        resource_id: Optional[str] = None,
        action: Optional[str] = None,
        status: Optional[str] = "success",
        details: Optional[Dict[str, Any]] = None,
        error_message: Optional[str] = None,
        error_code: Optional[str] = None,
        # Request context (auto-populated if available)
        request_id: Optional[str] = None,
        trace_id: Optional[str] = None,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None,
        endpoint: Optional[str] = None,
        http_method: Optional[str] = None,
    ) -> AuditLog:
        """
        Create an audit log entry.
        
        Args:
            db: Database session
            event_type: Event type from AuditEventType
            severity: Severity level (info, warning, error, critical)
            user_id: User ID (if applicable)
            username: Username (denormalized for performance)
            resource_type: Type of resource affected (e.g., "query", "session")
            resource_id: ID of affected resource
            action: Human-readable action description
            status: "success", "failure", or "partial"
            details: Additional event-specific data (JSON)
            error_message: Error message if applicable
            error_code: Error code if applicable
            request_id: Request ID for distributed tracing
            trace_id: Trace ID for distributed tracing
            ip_address: Client IP address
            user_agent: Client user agent
            endpoint: API endpoint path
            http_method: HTTP method (GET, POST, etc.)
            
        Returns:
            Created AuditLog instance
        """
        # Auto-populate request context if not provided
        if request_id is None:
            request_id = get_request_id()
        if trace_id is None:
            trace_id = get_trace_id()
        
        # Calculate retention date based on severity
        retention_days = self.RETENTION_POLICIES.get(severity, 90)
        retention_until = datetime.now(timezone.utc) + timedelta(days=retention_days)
        
        # Create audit log entry
        audit_entry = AuditLog(
            event_type=event_type,
            severity=severity,
            timestamp=datetime.now(timezone.utc),
            user_id=user_id,
            username=username,
            request_id=request_id,
            trace_id=trace_id,
            ip_address=ip_address,
            user_agent=user_agent,
            endpoint=endpoint,
            http_method=http_method,
            resource_type=resource_type,
            resource_id=resource_id,
            action=action,
            status=status,
            details=details,
            error_message=error_message,
            error_code=error_code,
            retention_until=retention_until
        )
        
        try:
            db.add(audit_entry)
            db.commit()
            db.refresh(audit_entry)
            
            # Log to application logger as well
            log_message = f"Audit: {event_type}"
            if action:
                log_message += f" - {action}"
            
            logger_method = getattr(logger, severity, logger.info)
            logger_method(
                log_message,
                extra={
                    "context": {
                        "event_type": event_type,
                        "user_id": user_id,
                        "resource_type": resource_type,
                        "resource_id": resource_id,
                        "request_id": request_id,
                        "audit_id": audit_entry.id
                    }
                }
            )
            
            return audit_entry
            
        except Exception as e:
            # Critical: Never let audit logging break the application
            logger.error(
                f"Failed to create audit log: {e}",
                exc_info=True,
                extra={
                    "context": {
                        "event_type": event_type,
                        "user_id": user_id,
                        "request_id": request_id
                    }
                }
            )
            db.rollback()
            # Return a dummy entry to prevent None errors
            return audit_entry
    
    def log_from_request(
        self,
        db: Session,
        request: Request,
        event_type: str,
        user: Optional[Any] = None,
        severity: str = AuditSeverity.INFO,
        resource_type: Optional[str] = None,
        resource_id: Optional[str] = None,
        action: Optional[str] = None,
        status: str = "success",
        details: Optional[Dict[str, Any]] = None,
        error_message: Optional[str] = None,
        error_code: Optional[str] = None,
    ) -> AuditLog:
        """
        Create audit log from FastAPI Request with automatic context extraction.
        
        Args:
            db: Database session
            request: FastAPI Request object
            event_type: Event type from AuditEventType
            user: User object (from get_current_user dependency)
            severity: Severity level
            resource_type: Type of resource affected
            resource_id: ID of affected resource
            action: Human-readable action description
            status: "success", "failure", or "partial"
            details: Additional event-specific data
            error_message: Error message if applicable
            error_code: Error code if applicable
            
        Returns:
            Created AuditLog instance
        """
        # Extract user context
        user_id = user.id if user else None
        username = user.username if user else None
        
        # Extract request metadata
        ip_address = self._get_client_ip(request)
        user_agent = request.headers.get("user-agent")
        endpoint = str(request.url.path)
        http_method = request.method
        
        return self.log(
            db=db,
            event_type=event_type,
            severity=severity,
            user_id=user_id,
            username=username,
            resource_type=resource_type,
            resource_id=resource_id,
            action=action,
            status=status,
            details=details,
            error_message=error_message,
            error_code=error_code,
            ip_address=ip_address,
            user_agent=user_agent,
            endpoint=endpoint,
            http_method=http_method
        )
    
    def log_auth_event(
        self,
        db: Session,
        event_type: str,
        username: str,
        success: bool,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
        error_message: Optional[str] = None
    ) -> AuditLog:
        """
        Log authentication event (login, logout, register).
        
        Args:
            db: Database session
            event_type: Auth event type (LOGIN_SUCCESS, LOGIN_FAILURE, etc.)
            username: Username attempting auth
            success: Whether auth succeeded
            ip_address: Client IP address
            user_agent: Client user agent
            details: Additional details (e.g., login method)
            error_message: Error if auth failed
            
        Returns:
            Created AuditLog instance
        """
        severity = AuditSeverity.INFO if success else AuditSeverity.WARNING
        status = "success" if success else "failure"
        
        return self.log(
            db=db,
            event_type=event_type,
            severity=severity,
            username=username,
            resource_type="user",
            action=f"Authentication: {event_type}",
            status=status,
            details=details,
            error_message=error_message,
            ip_address=ip_address,
            user_agent=user_agent,
            endpoint="/auth/login" if "login" in event_type else "/auth/logout"
        )
    
    def log_data_access(
        self,
        db: Session,
        user_id: int,
        username: str,
        resource_type: str,
        resource_id: str,
        action: str,
        details: Optional[Dict[str, Any]] = None
    ) -> AuditLog:
        """
        Log data access event for compliance.
        
        Args:
            db: Database session
            user_id: User accessing data
            username: Username
            resource_type: Type of data accessed
            resource_id: ID of data accessed
            action: What was done with the data
            details: Additional context
            
        Returns:
            Created AuditLog instance
        """
        return self.log(
            db=db,
            event_type=AuditEventType.DATA_VIEW,
            severity=AuditSeverity.INFO,
            user_id=user_id,
            username=username,
            resource_type=resource_type,
            resource_id=resource_id,
            action=action,
            status="success",
            details=details
        )
    
    def log_llm_call(
        self,
        db: Session,
        user_id: Optional[int],
        username: Optional[str],
        model: str,
        tokens_used: int,
        cost: Optional[float],
        success: bool,
        details: Optional[Dict[str, Any]] = None,
        error_message: Optional[str] = None
    ) -> AuditLog:
        """
        Log LLM API call for cost tracking and debugging.
        
        Args:
            db: Database session
            user_id: User initiating the LLM call
            username: Username
            model: LLM model used
            tokens_used: Number of tokens consumed
            cost: Estimated cost (if available)
            success: Whether call succeeded
            details: Additional context (prompt info, etc.)
            error_message: Error if call failed
            
        Returns:
            Created AuditLog instance
        """
        event_type = AuditEventType.LLM_CALL if success else AuditEventType.LLM_ERROR
        severity = AuditSeverity.INFO if success else AuditSeverity.WARNING
        
        llm_details = {
            "model": model,
            "tokens_used": tokens_used,
            **(details or {})
        }
        if cost is not None:
            llm_details["cost"] = cost
        
        return self.log(
            db=db,
            event_type=event_type,
            severity=severity,
            user_id=user_id,
            username=username,
            resource_type="llm_call",
            action=f"LLM API call: {model}",
            status="success" if success else "failure",
            details=llm_details,
            error_message=error_message
        )
    
    def _get_client_ip(self, request: Request) -> Optional[str]:
        """
        Extract client IP address from request.

        ``X-Forwarded-For`` and ``X-Real-IP`` headers are only trusted when the
        direct connection comes from a loopback address (127.x, ::1) or from a
        private RFC-1918 / RFC-4193 range, indicating the request arrived through
        a trusted reverse proxy (Nginx, load balancer).  Direct connections from
        public IPs are never allowed to self-declare their address via these headers.

        Args:
            request: FastAPI Request

        Returns:
            Client IP address or None
        """
        import ipaddress

        def _is_trusted_proxy(host: Optional[str]) -> bool:
            if not host:
                return False
            try:
                addr = ipaddress.ip_address(host)
                return addr.is_loopback or addr.is_private
            except ValueError:
                return False

        direct_host = request.client.host if request.client else None

        if _is_trusted_proxy(direct_host):
            # Request arrived via a trusted proxy — honour forwarded headers.
            forwarded_for = request.headers.get("x-forwarded-for")
            if forwarded_for:
                # X-Forwarded-For: <client>, <proxy1>, <proxy2> — first is the original client
                return forwarded_for.split(",")[0].strip()

            real_ip = request.headers.get("x-real-ip")
            if real_ip:
                return real_ip

        # Fallback to the direct connection address.
        return direct_host


# Global audit service instance
audit_service = AuditService()
