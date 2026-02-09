"""
CRUD operations for webhooks.

Provides database operations for managing webhook configurations
and delivery records.
"""
from sqlalchemy.orm import Session
from typing import List, Optional
from datetime import datetime, timezone
import secrets

from query_refinement_module.db.models.webhook import Webhook, WebhookDelivery


# ==========================================
# Webhook CRUD Operations
# ==========================================

def create_webhook(
    db: Session,
    user_id: int,
    url: str,
    events: List[str],
    name: Optional[str] = None,
    description: Optional[str] = None,
    max_retries: int = 3,
    timeout_seconds: int = 30
) -> Webhook:
    """
    Create a new webhook configuration.
    
    Automatically generates a secure secret for HMAC signing.
    
    Args:
        db: Database session
        user_id: Owner user ID
        url: Target URL for webhook delivery
        events: List of event types to subscribe to
        name: Optional friendly name
        description: Optional description
        max_retries: Number of retry attempts (default: 3)
        timeout_seconds: Request timeout (default: 30)
        
    Returns:
        Created Webhook instance
    """
    # Generate secure secret for HMAC
    secret = secrets.token_urlsafe(32)
    
    webhook = Webhook(
        user_id=user_id,
        url=url,
        events=events,
        secret=secret,
        name=name,
        description=description,
        max_retries=max_retries,
        timeout_seconds=timeout_seconds,
        active=True
    )
    
    db.add(webhook)
    db.commit()
    db.refresh(webhook)
    return webhook


def get_webhook(db: Session, webhook_id: int) -> Optional[Webhook]:
    """Retrieve webhook by ID."""
    return db.query(Webhook).filter(Webhook.id == webhook_id).first()


def get_user_webhooks(
    db: Session,
    user_id: int,
    active_only: bool = False
) -> List[Webhook]:
    """
    Retrieve all webhooks for a user.
    
    Args:
        db: Database session
        user_id: User ID
        active_only: If True, only return active webhooks
        
    Returns:
        List of Webhook instances
    """
    query = db.query(Webhook).filter(Webhook.user_id == user_id)
    
    if active_only:
        query = query.filter(Webhook.active == True)
    
    return query.order_by(Webhook.created_at.desc()).all()


def get_active_webhooks_for_event(
    db: Session,
    event_type: str,
    user_id: Optional[int] = None
) -> List[Webhook]:
    """
    Get all active webhooks subscribed to a specific event.
    
    Args:
        db: Database session
        event_type: Event type (e.g., "refinement.complete")
        user_id: Optional user ID to filter by specific user
        
    Returns:
        List of active Webhook instances subscribed to the event
    """
    query = db.query(Webhook).filter(
        Webhook.active == True,
        Webhook.events.contains([event_type])  # JSON array contains
    )
    
    if user_id is not None:
        query = query.filter(Webhook.user_id == user_id)
    
    return query.all()


def update_webhook(
    db: Session,
    webhook_id: int,
    url: Optional[str] = None,
    events: Optional[List[str]] = None,
    name: Optional[str] = None,
    description: Optional[str] = None,
    active: Optional[bool] = None,
    max_retries: Optional[int] = None,
    timeout_seconds: Optional[int] = None
) -> Optional[Webhook]:
    """
    Update webhook configuration.
    
    Only updates provided fields, leaves others unchanged.
    
    Args:
        db: Database session
        webhook_id: Webhook ID
        **kwargs: Fields to update
        
    Returns:
        Updated Webhook instance or None if not found
    """
    webhook = get_webhook(db, webhook_id)
    if not webhook:
        return None
    
    if url is not None:
        webhook.url = url
    if events is not None:
        webhook.events = events
    if name is not None:
        webhook.name = name
    if description is not None:
        webhook.description = description
    if active is not None:
        webhook.active = active
    if max_retries is not None:
        webhook.max_retries = max_retries
    if timeout_seconds is not None:
        webhook.timeout_seconds = timeout_seconds
    
    webhook.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(webhook)
    return webhook


def regenerate_webhook_secret(db: Session, webhook_id: int) -> Optional[str]:
    """
    Regenerate webhook secret.
    
    Returns new secret if successful, None if webhook not found.
    """
    webhook = get_webhook(db, webhook_id)
    if not webhook:
        return None
    
    new_secret = secrets.token_urlsafe(32)
    webhook.secret = new_secret
    webhook.updated_at = datetime.now(timezone.utc)
    db.commit()
    
    return new_secret


def delete_webhook(db: Session, webhook_id: int) -> bool:
    """
    Delete a webhook.
    
    Returns True if deleted, False if not found.
    """
    webhook = get_webhook(db, webhook_id)
    if not webhook:
        return False
    
    db.delete(webhook)
    db.commit()
    return True


def update_webhook_stats(
    db: Session,
    webhook_id: int,
    status: str,
    error: Optional[str] = None
) -> None:
    """
    Update webhook delivery statistics.
    
    Args:
        db: Database session
        webhook_id: Webhook ID
        status: Delivery status ("success", "failed", "timeout")
        error: Optional error message
    """
    webhook = get_webhook(db, webhook_id)
    if not webhook:
        return
    
    webhook.total_deliveries += 1
    webhook.last_delivery_at = datetime.now(timezone.utc)
    webhook.last_delivery_status = status
    
    if status == "success":
        webhook.successful_deliveries += 1
        webhook.last_error = None
    else:
        webhook.failed_deliveries += 1
        webhook.last_error = error
    
    db.commit()


# ==========================================
# Webhook Delivery CRUD Operations
# ==========================================

def create_webhook_delivery(
    db: Session,
    webhook_id: int,
    event_type: str,
    event_data: dict,
    attempt_number: int = 1
) -> WebhookDelivery:
    """
    Create a webhook delivery record.
    
    Args:
        db: Database session
        webhook_id: Webhook ID
        event_type: Event type being delivered
        event_data: Full event payload
        attempt_number: Retry attempt number
        
    Returns:
        Created WebhookDelivery instance
    """
    delivery = WebhookDelivery(
        webhook_id=webhook_id,
        event_type=event_type,
        event_data=event_data,
        attempt_number=attempt_number,
        status="pending"
    )
    
    db.add(delivery)
    db.commit()
    db.refresh(delivery)
    return delivery


def update_webhook_delivery(
    db: Session,
    delivery_id: int,
    status: str,
    status_code: Optional[int] = None,
    response_body: Optional[str] = None,
    error_message: Optional[str] = None,
    duration_ms: Optional[int] = None
) -> Optional[WebhookDelivery]:
    """
    Update webhook delivery with response details.
    
    Args:
        db: Database session
        delivery_id: Delivery ID
        status: Status ("success", "failed", "timeout")
        status_code: HTTP status code
        response_body: Response body from webhook endpoint
        error_message: Error message if failed
        duration_ms: Request duration in milliseconds
        
    Returns:
        Updated WebhookDelivery instance or None
    """
    delivery = db.query(WebhookDelivery).filter(WebhookDelivery.id == delivery_id).first()
    if not delivery:
        return None
    
    delivery.status = status
    delivery.status_code = status_code
    delivery.response_body = response_body
    delivery.error_message = error_message
    delivery.duration_ms = duration_ms
    delivery.completed_at = datetime.now(timezone.utc)
    
    db.commit()
    db.refresh(delivery)
    return delivery


def get_webhook_deliveries(
    db: Session,
    webhook_id: int,
    limit: int = 100,
    status: Optional[str] = None
) -> List[WebhookDelivery]:
    """
    Retrieve delivery history for a webhook.
    
    Args:
        db: Database session
        webhook_id: Webhook ID
        limit: Maximum number of deliveries to return
        status: Optional status filter
        
    Returns:
        List of WebhookDelivery instances
    """
    query = db.query(WebhookDelivery).filter(
        WebhookDelivery.webhook_id == webhook_id
    )
    
    if status:
        query = query.filter(WebhookDelivery.status == status)
    
    return query.order_by(
        WebhookDelivery.created_at.desc()
    ).limit(limit).all()


def get_recent_deliveries_by_user(
    db: Session,
    user_id: int,
    limit: int = 50
) -> List[WebhookDelivery]:
    """
    Get recent webhook deliveries for a user (across all their webhooks).
    
    Args:
        db: Database session
        user_id: User ID
        limit: Maximum number of deliveries
        
    Returns:
        List of WebhookDelivery instances
    """
    return db.query(WebhookDelivery).join(
        Webhook, WebhookDelivery.webhook_id == Webhook.id
    ).filter(
        Webhook.user_id == user_id
    ).order_by(
        WebhookDelivery.created_at.desc()
    ).limit(limit).all()
