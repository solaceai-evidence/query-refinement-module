"""
Frontend log model for storing browser-side logs.

Captures JavaScript errors, console logs, user actions, and performance metrics
from the frontend application for debugging and monitoring.
"""

from datetime import datetime, timezone, timedelta
from typing import Optional
from sqlalchemy import Column, Integer, String, DateTime, Text, JSON, ForeignKey, Index
from sqlalchemy.orm import relationship

from query_refinement_module.db.database import Base


def _utcnow():
    """Return current UTC time (timezone-aware)."""
    return datetime.now(timezone.utc)


class FrontendLogLevel:
    """Frontend log severity levels matching browser console."""
    DEBUG = "debug"
    INFO = "info"
    WARN = "warn"
    ERROR = "error"
    
    @classmethod
    def all_levels(cls):
        return [cls.DEBUG, cls.INFO, cls.WARN, cls.ERROR]


class FrontendLogType:
    """Types of frontend logs."""
    CONSOLE = "console"           # Console.log, warn, error
    ERROR = "error"                # JavaScript errors
    NETWORK = "network"            # Network request failures
    PERFORMANCE = "performance"    # Performance metrics
    USER_ACTION = "user_action"    # User interactions (clicks, navigation)
    
    @classmethod
    def all_types(cls):
        return [cls.CONSOLE, cls.ERROR, cls.NETWORK, cls.PERFORMANCE, cls.USER_ACTION]


class FrontendLog(Base):
    """
    Frontend log entries from browser.
    
    Stores logs sent from the frontend application including console logs,
    errors, user actions, and performance metrics. Correlates with backend
    logs via request_id from Phase 2 distributed tracing.
    """
    
    __tablename__ = "frontend_logs"
    
    # Primary key
    id = Column(Integer, primary_key=True, index=True)
    
    # Timing
    timestamp = Column(DateTime, nullable=False, index=True, default=_utcnow)
    client_timestamp = Column(DateTime, nullable=True)  # Browser's timestamp
    
    # Log classification
    level = Column(String(20), nullable=False, index=True)  # debug, info, warn, error
    log_type = Column(String(50), nullable=False, index=True)  # console, error, network, etc.
    
    # User context
    user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    session_id = Column(Integer, ForeignKey("query_sessions.id", ondelete="SET NULL"), nullable=True, index=True)
    
    # Distributed tracing (Phase 2 integration)
    request_id = Column(String(36), nullable=True, index=True)  # Correlates with backend logs
    trace_id = Column(String(36), nullable=True, index=True)    # Full trace ID
    
    # Browser context
    url = Column(String(2048), nullable=True)           # Page URL
    user_agent = Column(String(500), nullable=True)     # Browser user agent
    screen_resolution = Column(String(50), nullable=True)  # e.g., "1920x1080"
    viewport_size = Column(String(50), nullable=True)   # e.g., "1200x800"
    
    # Log content
    message = Column(Text, nullable=False)              # Log message
    details = Column(JSON, nullable=True)               # Additional structured data
    
    # Error-specific fields
    error_name = Column(String(200), nullable=True)     # Error type (TypeError, etc.)
    error_stack = Column(Text, nullable=True)           # Stack trace
    error_line = Column(Integer, nullable=True)         # Line number
    error_column = Column(Integer, nullable=True)       # Column number
    error_file = Column(String(500), nullable=True)     # Source file
    
    # Network-specific fields
    network_url = Column(String(2048), nullable=True)   # API endpoint
    network_method = Column(String(10), nullable=True)  # GET, POST, etc.
    network_status = Column(Integer, nullable=True)     # HTTP status code
    network_duration_ms = Column(Integer, nullable=True)  # Request duration
    
    # Performance metrics
    performance_metric = Column(String(100), nullable=True)  # Metric name
    performance_value = Column(Integer, nullable=True)       # Value in ms
    
    # Relationships
    user = relationship("User", foreign_keys=[user_id])
    session = relationship("QuerySession", foreign_keys=[session_id])
    
    # Composite indexes for common queries
    __table_args__ = (
        Index('idx_frontend_user_timestamp', 'user_id', 'timestamp'),
        Index('idx_frontend_level_timestamp', 'level', 'timestamp'),
        Index('idx_frontend_type_timestamp', 'log_type', 'timestamp'),
        Index('idx_frontend_request', 'request_id', 'trace_id'),
        Index('idx_frontend_session', 'session_id', 'timestamp'),
    )
    
    def __repr__(self):
        return f"<FrontendLog(id={self.id}, level={self.level}, type={self.log_type}, message='{self.message[:50]}...')>"
    
    def to_dict(self) -> dict:
        """Convert to dictionary for API responses."""
        return {
            "id": self.id,
            "timestamp": self.timestamp.isoformat() if self.timestamp is not None else None,
            "client_timestamp": self.client_timestamp.isoformat() if self.client_timestamp is not None else None,
            "level": self.level,
            "log_type": self.log_type,
            "user_id": self.user_id,
            "session_id": self.session_id,
            "request_id": self.request_id,
            "trace_id": self.trace_id,
            "url": self.url,
            "user_agent": self.user_agent,
            "message": self.message,
            "details": self.details,
            "error_name": self.error_name,
            "error_stack": self.error_stack,
            "error_line": self.error_line,
            "error_column": self.error_column,
            "error_file": self.error_file,
            "network_url": self.network_url,
            "network_method": self.network_method,
            "network_status": self.network_status,
            "network_duration_ms": self.network_duration_ms,
            "performance_metric": self.performance_metric,
            "performance_value": self.performance_value,
        }
