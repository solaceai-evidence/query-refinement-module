"""
Audit log model for compliance and security tracking.

Captures all significant user actions and system events for:
- Security monitoring
- Compliance requirements (HIPAA, GDPR, SOC2)
- Debugging and troubleshooting
- User behavior analysis

Each audit entry is immutable and includes full context for investigation.
"""
from sqlalchemy import Column, Integer, String, DateTime, Text, JSON, Index, ForeignKey
from sqlalchemy.orm import relationship
from datetime import datetime, timezone
from typing import Optional, Dict, Any

from query_refinement_module.db.models.user import Base


class AuditEventType:
    """Enum-like class for standardized audit event types."""
    
    # Authentication events
    LOGIN_SUCCESS = "auth.login.success"
    LOGIN_FAILURE = "auth.login.failure"
    LOGOUT = "auth.logout"
    REGISTER = "auth.register"
    PASSWORD_CHANGE = "auth.password_change"
    TOKEN_REFRESH = "auth.token_refresh"
    
    # Query session events
    SESSION_CREATE = "session.create"
    SESSION_END = "session.end"
    SESSION_ACCESS = "session.access"
    SESSION_ABANDONED = "session.abandoned"
    
    # Query events
    QUERY_CREATE = "query.create"
    QUERY_UPDATE = "query.update"
    QUERY_DELETE = "query.delete"
    QUERY_REFINE = "query.refine"
    
    # Refinement events
    REFINEMENT_START = "refinement.start"
    REFINEMENT_STEP = "refinement.step"
    REFINEMENT_COMPLETE = "refinement.complete"
    REFINEMENT_ABORT = "refinement.abort"
    
    # Command events (user commands during refinement)
    COMMAND_EXECUTE = "command.execute"
    COMMAND_BACK = "command.back"
    COMMAND_RESTART = "command.restart"
    COMMAND_CLEAR = "command.clear"
    COMMAND_SKIP = "command.skip"
    COMMAND_DONE = "command.done"
    COMMAND_GOTO = "command.goto"
    COMMAND_STATUS = "command.status"
    COMMAND_HELP = "command.help"
    COMMAND_STEPS = "command.steps"
    
    # Feedback events
    FEEDBACK_CREATE = "feedback.create"
    FEEDBACK_UPDATE = "feedback.update"
    
    # Data access events
    DATA_EXPORT = "data.export"
    DATA_VIEW = "data.view"
    DATA_DOWNLOAD = "data.download"
    
    # Admin events (for future admin functionality)
    ADMIN_ACCESS = "admin.access"
    ADMIN_USER_MODIFY = "admin.user.modify"
    ADMIN_USER_DELETE = "admin.user.delete"
    
    # System events
    SYSTEM_ERROR = "system.error"
    SYSTEM_MAINTENANCE = "system.maintenance"
    RATE_LIMIT_EXCEEDED = "system.rate_limit"
    
    # LLM events
    LLM_CALL = "llm.call"
    LLM_ERROR = "llm.error"
    LLM_RATE_LIMIT = "llm.rate_limit"
    
    @classmethod
    def all_types(cls) -> list:
        """Return all event types."""
        return [
            getattr(cls, attr) for attr in dir(cls)
            if not attr.startswith('_') and isinstance(getattr(cls, attr), str)
        ]


class AuditSeverity:
    """Severity levels for audit events."""
    
    INFO = "info"        # Normal operations
    WARNING = "warning"  # Potentially problematic
    ERROR = "error"      # Error conditions
    CRITICAL = "critical"  # Security/compliance critical


class AuditLog(Base):
    """
    Comprehensive audit log for all significant system events.
    
    Design Principles:
    - Immutable: Never update or delete audit logs
    - Complete: Capture full context for investigation
    - Traceable: Link to request_id for distributed tracing
    - Compliant: Meet HIPAA, GDPR, SOC2 requirements
    - Searchable: Indexed for fast querying
    """
    __tablename__ = "audit_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    
    # Event identification
    event_type = Column(String(100), nullable=False, index=True)
    severity = Column(String(20), nullable=False, default=AuditSeverity.INFO, index=True)
    
    # Temporal information
    timestamp = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc), index=True)
    
    # User context (nullable for system events)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    username = Column(String(50), nullable=True)  # Denormalized for performance
    
    # Distributed tracing correlation
    request_id = Column(String(36), nullable=True, index=True)  # UUID from middleware
    trace_id = Column(String(36), nullable=True, index=True)
    
    # Request context
    ip_address = Column(String(45), nullable=True)  # IPv4 or IPv6
    user_agent = Column(String(500), nullable=True)
    endpoint = Column(String(255), nullable=True, index=True)  # API endpoint path
    http_method = Column(String(10), nullable=True)
    
    # Resource information
    resource_type = Column(String(50), nullable=True, index=True)  # e.g., "query", "session", "user"
    resource_id = Column(String(100), nullable=True, index=True)  # Resource identifier
    
    # Event details
    action = Column(String(100), nullable=True)  # Human-readable action description
    status = Column(String(20), nullable=True)  # "success", "failure", "partial"
    
    # Detailed context (JSON for flexibility)
    details = Column(JSON, nullable=True)  # Additional event-specific data
    
    # Error information (if applicable)
    error_message = Column(Text, nullable=True)
    error_code = Column(String(50), nullable=True)
    
    # Compliance metadata
    retention_until = Column(DateTime, nullable=True)  # For compliance-driven retention
    
    # Relationships
    user = relationship("User", foreign_keys=[user_id], backref="audit_logs")
    
    # Composite indexes for common queries
    __table_args__ = (
        # Query by user over time
        Index('idx_audit_user_timestamp', 'user_id', 'timestamp'),
        # Query by event type over time
        Index('idx_audit_event_timestamp', 'event_type', 'timestamp'),
        # Query by resource
        Index('idx_audit_resource', 'resource_type', 'resource_id'),
        # Distributed tracing
        Index('idx_audit_request_trace', 'request_id', 'trace_id'),
        # Compliance queries
        Index('idx_audit_severity_timestamp', 'severity', 'timestamp'),
    )
    
    def __repr__(self):
        return (
            f"<AuditLog(id={self.id}, event_type='{self.event_type}', "
            f"user_id={self.user_id}, timestamp={self.timestamp})>"
        )
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert audit log to dictionary for API responses."""
        return {
            "id": self.id,
            "event_type": self.event_type,
            "severity": self.severity,
            "timestamp": self.timestamp.isoformat() if self.timestamp is not None else None,
            "user_id": self.user_id,
            "username": self.username,
            "request_id": self.request_id,
            "trace_id": self.trace_id,
            "ip_address": self.ip_address,
            "user_agent": self.user_agent,
            "endpoint": self.endpoint,
            "http_method": self.http_method,
            "resource_type": self.resource_type,
            "resource_id": self.resource_id,
            "action": self.action,
            "status": self.status,
            "details": self.details,
            "error_message": self.error_message,
            "error_code": self.error_code,
        }
