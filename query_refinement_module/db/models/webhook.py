"""
Webhook model for external system integration.

Enables real-time notifications to external systems when events occur
in the query refinement workflow.
"""
from sqlalchemy import Column, Integer, String, DateTime, Boolean, Text, JSON, ForeignKey
from sqlalchemy.orm import relationship
from datetime import datetime, timezone
from typing import Optional

from query_refinement_module.db.models.user import Base


class WebhookEventType:
    """Enum-like class for webhook event types."""
    
    # Refinement workflow events
    REFINEMENT_STARTED = "refinement.started"
    REFINEMENT_STEP_COMPLETED = "refinement.step_completed"
    REFINEMENT_COMPLETE = "refinement.complete"
    
    # Synthesis events
    SYNTHESIS_STARTED = "synthesis.started"
    SYNTHESIS_COMPLETE = "synthesis.complete"
    
    # Query events
    QUERY_CREATED = "query.created"
    QUERY_UPDATED = "query.updated"
    QUERY_FORWARDED = "query.forwarded"  # Forwarded to external QA system
    
    # Session events
    SESSION_CREATED = "session.created"
    SESSION_ENDED = "session.ended"
    
    @classmethod
    def all_types(cls) -> list:
        """Return all event types."""
        return [
            getattr(cls, attr) for attr in dir(cls)
            if not attr.startswith('_') and isinstance(getattr(cls, attr), str)
        ]


class Webhook(Base):
    """
    Webhook configuration for external system integration.
    
    Webhooks enable real-time notifications to external systems when
    specific events occur during the query refinement workflow.
    
    Features:
    - Event filtering (subscribe to specific events)
    - HMAC signature for security verification
    - Automatic retry with exponential backoff
    - Delivery tracking and status monitoring
    - Active/inactive toggle for temporary disabling
    """
    __tablename__ = "webhooks"
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    
    # Webhook configuration
    url = Column(String(2048), nullable=False)  # Target URL for webhook delivery
    events = Column(JSON, nullable=False)  # List of event types to trigger on
    secret = Column(String(256), nullable=False)  # Secret for HMAC signature
    
    # Metadata
    name = Column(String(256), nullable=True)  # User-friendly name
    description = Column(Text, nullable=True)  # Optional description
    
    # Delivery settings
    active = Column(Boolean, default=True, nullable=False)  # Can be toggled off
    max_retries = Column(Integer, default=3, nullable=False)  # Number of retry attempts
    timeout_seconds = Column(Integer, default=30, nullable=False)  # Request timeout
    
    # Statistics and tracking
    total_deliveries = Column(Integer, default=0, nullable=False)
    successful_deliveries = Column(Integer, default=0, nullable=False)
    failed_deliveries = Column(Integer, default=0, nullable=False)
    last_delivery_at = Column(DateTime(timezone=True), nullable=True)
    last_delivery_status = Column(String(50), nullable=True)  # success, failed, timeout
    last_error = Column(Text, nullable=True)  # Last error message if any
    
    # Timestamps
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
    
    # Relationships
    user = relationship("User", back_populates="webhooks")
    deliveries = relationship("WebhookDelivery", back_populates="webhook", cascade="all, delete-orphan")
    
    def __repr__(self):
        return f"<Webhook(id={self.id}, url={self.url}, active={self.active})>"


class WebhookDelivery(Base):
    """
    Webhook delivery attempt record.
    
    Tracks each webhook delivery attempt for debugging and monitoring.
    Stores request/response details and timing information.
    """
    __tablename__ = "webhook_deliveries"
    
    id = Column(Integer, primary_key=True, index=True)
    webhook_id = Column(Integer, ForeignKey("webhooks.id"), nullable=False, index=True)
    
    # Event details
    event_type = Column(String(100), nullable=False, index=True)
    event_data = Column(JSON, nullable=False)  # Full event payload
    
    # Delivery details
    attempt_number = Column(Integer, default=1, nullable=False)  # Which retry attempt
    status_code = Column(Integer, nullable=True)  # HTTP response code
    response_body = Column(Text, nullable=True)  # Response from webhook endpoint
    
    # Status and timing
    status = Column(String(50), nullable=False, index=True)  # pending, success, failed, timeout
    error_message = Column(Text, nullable=True)
    duration_ms = Column(Integer, nullable=True)  # Request duration in milliseconds
    
    # Timestamps
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    completed_at = Column(DateTime(timezone=True), nullable=True)
    
    # Relationships
    webhook = relationship("Webhook", back_populates="deliveries")
    
    def __repr__(self):
        return f"<WebhookDelivery(id={self.id}, webhook_id={self.webhook_id}, status={self.status})>"
