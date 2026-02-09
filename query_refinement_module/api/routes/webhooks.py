"""
Webhook management endpoints.

Provides API for managing webhook configurations and viewing delivery history.
"""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List, Optional
from pydantic import BaseModel, HttpUrl, Field
from datetime import datetime

from query_refinement_module.api.auth import get_current_user
from query_refinement_module.db.session import get_db
from query_refinement_module.db.models.user import User
from query_refinement_module.db.models.webhook import Webhook, WebhookDelivery, WebhookEventType
from query_refinement_module.db import crud_webhooks
from query_refinement_module.services.webhook_service import WebhookService, trigger_webhook_event

router = APIRouter(prefix="/webhooks", tags=["webhooks"])


# ==========================================
# Pydantic Schemas
# ==========================================

class WebhookCreateRequest(BaseModel):
    """Request schema for creating a webhook."""
    url: HttpUrl = Field(..., description="Webhook endpoint URL")
    events: List[str] = Field(..., description="List of event types to subscribe to")
    name: Optional[str] = Field(None, max_length=100, description="Friendly name for webhook")
    description: Optional[str] = Field(None, max_length=500, description="Description of webhook purpose")
    max_retries: int = Field(3, ge=0, le=10, description="Maximum retry attempts")
    timeout_seconds: int = Field(30, ge=5, le=120, description="Request timeout in seconds")


class WebhookUpdateRequest(BaseModel):
    """Request schema for updating a webhook."""
    url: Optional[HttpUrl] = Field(None, description="Webhook endpoint URL")
    events: Optional[List[str]] = Field(None, description="List of event types")
    name: Optional[str] = Field(None, max_length=100, description="Friendly name")
    description: Optional[str] = Field(None, max_length=500, description="Description")
    active: Optional[bool] = Field(None, description="Active status")
    max_retries: Optional[int] = Field(None, ge=0, le=10, description="Maximum retry attempts")
    timeout_seconds: Optional[int] = Field(None, ge=5, le=120, description="Request timeout")


class WebhookResponse(BaseModel):
    """Response schema for webhook details."""
    id: int
    user_id: int
    url: str
    events: List[str]
    name: Optional[str]
    description: Optional[str]
    active: bool
    max_retries: int
    timeout_seconds: int
    total_deliveries: int
    successful_deliveries: int
    failed_deliveries: int
    last_delivery_at: Optional[datetime]
    last_delivery_status: Optional[str]
    last_error: Optional[str]
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class WebhookSecretResponse(BaseModel):
    """Response schema containing webhook secret (only shown on create/regenerate)."""
    webhook_id: int
    secret: str
    message: str = "Store this secret securely. It cannot be retrieved later."


class WebhookDeliveryResponse(BaseModel):
    """Response schema for delivery history."""
    id: int
    webhook_id: int
    event_type: str
    attempt_number: int
    status: str
    status_code: Optional[int]
    response_body: Optional[str]
    error_message: Optional[str]
    duration_ms: Optional[int]
    created_at: datetime
    completed_at: Optional[datetime]

    class Config:
        from_attributes = True


class WebhookEventTypesResponse(BaseModel):
    """Response schema for available event types."""
    event_types: List[str]


class WebhookTestRequest(BaseModel):
    """Request schema for testing a webhook."""
    test_data: Optional[dict] = Field(default=None, description="Custom test payload")


class WebhookTestResponse(BaseModel):
    """Response schema for webhook test result."""
    success: bool
    status_code: Optional[int]
    response_body: Optional[str]
    error_message: Optional[str]
    duration_ms: int


# ==========================================
# Helper Functions
# ==========================================

def validate_event_types(events: List[str]) -> None:
    """
    Validate that event types are valid.
    
    Raises HTTPException if any event type is invalid.
    """
    valid_events = {
        WebhookEventType.REFINEMENT_STARTED,
        WebhookEventType.REFINEMENT_STEP_COMPLETED,
        WebhookEventType.REFINEMENT_COMPLETE,
        WebhookEventType.SYNTHESIS_STARTED,
        WebhookEventType.SYNTHESIS_COMPLETE,
        WebhookEventType.QUERY_CREATED,
        WebhookEventType.QUERY_UPDATED,
        WebhookEventType.SESSION_CREATED,
        WebhookEventType.SESSION_ENDED,
    }
    
    invalid_events = [e for e in events if e not in valid_events]
    if invalid_events:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid event types: {', '.join(invalid_events)}"
        )


def validate_webhook_ownership(webhook: Optional[Webhook], user: User) -> Webhook:
    """
    Validate that webhook exists and belongs to user.
    
    Raises HTTPException if not found or unauthorized.
    """
    if not webhook:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Webhook not found"
        )
    
    if webhook.user_id != user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have permission to access this webhook"
        )
    
    return webhook


# ==========================================
# API Endpoints
# ==========================================

@router.get("/event-types", response_model=WebhookEventTypesResponse)
def get_event_types():
    """
    Get list of available webhook event types.
    
    Returns all event types that can be subscribed to.
    """
    return WebhookEventTypesResponse(event_types=[
        WebhookEventType.REFINEMENT_STARTED,
        WebhookEventType.REFINEMENT_STEP_COMPLETED,
        WebhookEventType.REFINEMENT_COMPLETE,
        WebhookEventType.SYNTHESIS_STARTED,
        WebhookEventType.SYNTHESIS_COMPLETE,
        WebhookEventType.QUERY_CREATED,
        WebhookEventType.QUERY_UPDATED,
        WebhookEventType.SESSION_CREATED,
        WebhookEventType.SESSION_ENDED,
    ])


@router.post("", response_model=WebhookSecretResponse, status_code=status.HTTP_201_CREATED)
def create_webhook(
    request: WebhookCreateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Create a new webhook configuration.
    
    Returns webhook ID and secret. The secret is only shown once and must be stored
    securely for HMAC signature verification.
    """
    # Validate event types
    validate_event_types(request.events)
    
    # Create webhook
    webhook = crud_webhooks.create_webhook(
        db=db,
        user_id=current_user.id,
        url=str(request.url),
        events=request.events,
        name=request.name,
        description=request.description,
        max_retries=request.max_retries,
        timeout_seconds=request.timeout_seconds
    )
    
    return WebhookSecretResponse(
        webhook_id=webhook.id,
        secret=webhook.secret
    )


@router.get("", response_model=List[WebhookResponse])
def list_webhooks(
    active_only: bool = False,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    List all webhooks for the authenticated user.
    
    Args:
        active_only: If true, only return active webhooks
    """
    webhooks = crud_webhooks.get_user_webhooks(
        db=db,
        user_id=current_user.id,
        active_only=active_only
    )
    return webhooks


@router.get("/{webhook_id}", response_model=WebhookResponse)
def get_webhook(
    webhook_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get details of a specific webhook."""
    webhook = crud_webhooks.get_webhook(db, webhook_id)
    validate_webhook_ownership(webhook, current_user)
    return webhook


@router.put("/{webhook_id}", response_model=WebhookResponse)
def update_webhook(
    webhook_id: int,
    request: WebhookUpdateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Update webhook configuration.
    
    Only provided fields are updated, others remain unchanged.
    """
    # Verify ownership
    webhook = crud_webhooks.get_webhook(db, webhook_id)
    validate_webhook_ownership(webhook, current_user)
    
    # Validate event types if provided
    if request.events is not None:
        validate_event_types(request.events)
    
    # Update webhook
    updated_webhook = crud_webhooks.update_webhook(
        db=db,
        webhook_id=webhook_id,
        url=str(request.url) if request.url else None,
        events=request.events,
        name=request.name,
        description=request.description,
        active=request.active,
        max_retries=request.max_retries,
        timeout_seconds=request.timeout_seconds
    )
    
    if not updated_webhook:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to update webhook"
        )
    
    return updated_webhook


@router.delete("/{webhook_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_webhook(
    webhook_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Delete a webhook.
    
    All delivery history will also be deleted.
    """
    # Verify ownership
    webhook = crud_webhooks.get_webhook(db, webhook_id)
    validate_webhook_ownership(webhook, current_user)
    
    # Delete webhook
    crud_webhooks.delete_webhook(db, webhook_id)


@router.post("/{webhook_id}/regenerate-secret", response_model=WebhookSecretResponse)
def regenerate_secret(
    webhook_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Regenerate webhook secret.
    
    The new secret is only shown once and must be stored securely.
    Old secret will be immediately invalidated.
    """
    # Verify ownership
    webhook = crud_webhooks.get_webhook(db, webhook_id)
    validate_webhook_ownership(webhook, current_user)
    
    # Regenerate secret
    new_secret = crud_webhooks.regenerate_webhook_secret(db, webhook_id)
    
    if not new_secret:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to regenerate secret"
        )
    
    return WebhookSecretResponse(
        webhook_id=webhook_id,
        secret=new_secret,
        message="Secret regenerated. Update your webhook endpoint with the new secret."
    )


@router.get("/{webhook_id}/deliveries", response_model=List[WebhookDeliveryResponse])
def get_webhook_deliveries(
    webhook_id: int,
    limit: int = 100,
    status_filter: Optional[str] = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Get delivery history for a webhook.
    
    Args:
        webhook_id: Webhook ID
        limit: Maximum number of deliveries to return (default: 100)
        status_filter: Optional status filter ("success", "failed", "timeout", "pending")
    """
    # Verify ownership
    webhook = crud_webhooks.get_webhook(db, webhook_id)
    validate_webhook_ownership(webhook, current_user)
    
    # Get deliveries
    deliveries = crud_webhooks.get_webhook_deliveries(
        db=db,
        webhook_id=webhook_id,
        limit=limit,
        status=status_filter
    )
    
    return deliveries


@router.post("/{webhook_id}/test", response_model=WebhookTestResponse)
def test_webhook(
    webhook_id: int,
    request: WebhookTestRequest = WebhookTestRequest(),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Send a test event to a webhook.
    
    Useful for verifying webhook configuration and endpoint availability.
    """
    # Verify ownership
    webhook = crud_webhooks.get_webhook(db, webhook_id)
    validate_webhook_ownership(webhook, current_user)
    
    # Prepare test payload
    test_data = request.test_data or {
        "test": True,
        "message": "This is a test webhook event",
        "user_id": current_user.id
    }
    
    # Deliver test event
    service = WebhookService(db)
    success = service.deliver_webhook(
        webhook=webhook,
        event_type="webhook.test",
        event_data=test_data,
        attempt_number=1
    )
    
    # Get delivery result
    deliveries = crud_webhooks.get_webhook_deliveries(db, webhook_id, limit=1)
    latest_delivery = deliveries[0] if deliveries else None
    
    return WebhookTestResponse(
        success=success,
        status_code=latest_delivery.status_code if latest_delivery else None,
        response_body=latest_delivery.response_body if latest_delivery else None,
        error_message=latest_delivery.error_message if latest_delivery else None,
        duration_ms=latest_delivery.duration_ms if latest_delivery else 0
    )


@router.get("/deliveries/recent", response_model=List[WebhookDeliveryResponse])
def get_recent_deliveries(
    limit: int = 50,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Get recent deliveries across all user's webhooks.
    
    Args:
        limit: Maximum number of deliveries to return (default: 50)
    """
    deliveries = crud_webhooks.get_recent_deliveries_by_user(
        db=db,
        user_id=current_user.id,
        limit=limit
    )
    
    return deliveries
