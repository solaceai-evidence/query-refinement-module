"""
Webhook delivery service.

Handles webhook event delivery with retry logic, HMAC signing,
and delivery tracking.
"""
import hmac
import hashlib
import json
import time
import logging
from threading import Thread
import requests
from typing import Dict, Any, Optional, List
from datetime import datetime, timezone
from sqlalchemy.orm import Session

from query_refinement_module.db.database import SessionLocal
from query_refinement_module.db.models.webhook import Webhook, WebhookDelivery
from query_refinement_module.db.crud_webhooks import (
    get_active_webhooks_for_event,
    create_webhook_delivery,
    update_webhook_delivery,
    update_webhook_stats
)

logger = logging.getLogger(__name__)


class WebhookService:
    """Service for delivering webhook events to external systems."""
    
    def __init__(self, db: Session):
        """
        Initialize webhook service.
        
        Args:
            db: Database session
        """
        self.db = db
    
    @staticmethod
    def generate_signature(payload: bytes, secret: str) -> str:
        """
        Generate HMAC-SHA256 signature for webhook payload.
        
        Args:
            payload: JSON payload as bytes
            secret: Webhook secret key
            
        Returns:
            Hex-encoded HMAC signature
        """
        signature = hmac.new(
            key=secret.encode('utf-8'),
            msg=payload,
            digestmod=hashlib.sha256
        )
        return signature.hexdigest()
    
    def deliver_webhook(
        self,
        webhook: Webhook,
        event_type: str,
        event_data: Dict[str, Any],
        attempt_number: int = 1
    ) -> bool:
        """
        Deliver a single webhook event.
        
        Args:
            webhook: Webhook configuration
            event_type: Event type (e.g., "refinement.complete")
            event_data: Event payload
            attempt_number: Retry attempt number (1-based)
            
        Returns:
            True if delivery succeeded, False otherwise
        """
        # Create delivery record
        delivery = create_webhook_delivery(
            self.db,
            webhook_id=webhook.id,
            event_type=event_type,
            event_data=event_data,
            attempt_number=attempt_number
        )
        
        # Prepare payload
        payload = {
            "event": event_type,
            "data": event_data,
            "webhook_id": webhook.id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "attempt": attempt_number
        }
        payload_bytes = json.dumps(payload, separators=(',', ':')).encode('utf-8')
        
        # Generate signature
        signature = self.generate_signature(payload_bytes, webhook.secret)
        
        # Prepare headers
        headers = {
            "Content-Type": "application/json",
            "X-Webhook-Signature": f"sha256={signature}",
            "X-Webhook-Event": event_type,
            "X-Webhook-ID": str(webhook.id),
            "X-Webhook-Attempt": str(attempt_number),
            "User-Agent": "QueryRefinement-Webhook/1.0"
        }
        
        # Attempt delivery
        start_time = time.time()
        success = False
        status_code = None
        response_body = None
        error_message = None
        delivery_status = "failed"
        
        try:
            logger.info(
                f"Delivering webhook {webhook.id} ({webhook.name}): "
                f"{event_type} to {webhook.url} (attempt {attempt_number})"
            )
            
            response = requests.post(
                webhook.url,
                data=payload_bytes,
                headers=headers,
                timeout=webhook.timeout_seconds
            )
            
            status_code = response.status_code
            response_body = response.text[:1000]  # Limit stored response
            
            # Consider 2xx responses as success
            if 200 <= status_code < 300:
                success = True
                delivery_status = "success"
                logger.info(
                    f"Webhook {webhook.id} delivered successfully: "
                    f"{status_code} {event_type}"
                )
            else:
                error_message = f"HTTP {status_code}: {response_body}"
                logger.warning(
                    f"Webhook {webhook.id} failed with status {status_code}: "
                    f"{error_message}"
                )
        
        except requests.exceptions.Timeout:
            delivery_status = "timeout"
            error_message = f"Request timeout after {webhook.timeout_seconds}s"
            logger.warning(f"Webhook {webhook.id} timed out: {error_message}")
        
        except requests.exceptions.RequestException as e:
            error_message = f"Request failed: {str(e)}"
            logger.error(f"Webhook {webhook.id} delivery error: {error_message}")
        
        except Exception as e:
            error_message = f"Unexpected error: {str(e)}"
            logger.error(
                f"Webhook {webhook.id} unexpected error: {error_message}",
                exc_info=True
            )
        
        # Calculate duration
        duration_ms = int((time.time() - start_time) * 1000)
        
        # Update delivery record
        update_webhook_delivery(
            self.db,
            delivery_id=delivery.id,
            status=delivery_status,
            status_code=status_code,
            response_body=response_body,
            error_message=error_message,
            duration_ms=duration_ms
        )
        
        # Update webhook statistics
        update_webhook_stats(
            self.db,
            webhook_id=webhook.id,
            status=delivery_status,
            error=error_message
        )
        
        return success
    
    def deliver_with_retry(
        self,
        webhook: Webhook,
        event_type: str,
        event_data: Dict[str, Any]
    ) -> bool:
        """
        Deliver webhook with automatic retry on failure.
        
        Uses exponential backoff: 2^attempt seconds
        - Attempt 1: immediate
        - Attempt 2: wait 2s
        - Attempt 3: wait 4s
        - Attempt 4: wait 8s
        
        Args:
            webhook: Webhook configuration
            event_type: Event type
            event_data: Event payload
            
        Returns:
            True if any attempt succeeded, False if all failed
        """
        max_attempts = webhook.max_retries + 1  # +1 for initial attempt
        
        for attempt in range(1, max_attempts + 1):
            # Wait with exponential backoff (except first attempt)
            if attempt > 1:
                backoff_seconds = 2 ** (attempt - 1)
                logger.info(
                    f"Webhook {webhook.id} retry {attempt}/{max_attempts} "
                    f"after {backoff_seconds}s backoff"
                )
                time.sleep(backoff_seconds)
            
            # Attempt delivery
            success = self.deliver_webhook(webhook, event_type, event_data, attempt)
            
            if success:
                return True
        
        logger.error(
            f"Webhook {webhook.id} failed after {max_attempts} attempts: "
            f"{event_type}"
        )
        return False
    
    def trigger_event(
        self,
        event_type: str,
        event_data: Dict[str, Any],
        user_id: Optional[int] = None
    ) -> int:
        """
        Trigger webhook event for all subscribed webhooks.
        
        Args:
            event_type: Event type (e.g., "refinement.complete")
            event_data: Event payload
            user_id: Optional user ID to filter webhooks (if None, all users)
            
        Returns:
            Number of webhooks triggered
        """
        # Get all active webhooks subscribed to this event
        webhooks = get_active_webhooks_for_event(
            self.db,
            event_type=event_type,
            user_id=user_id
        )
        
        if not webhooks:
            logger.debug(f"No webhooks subscribed to {event_type}")
            return 0
        
        logger.info(
            f"Triggering {len(webhooks)} webhook(s) for event: {event_type}"
        )
        
        # Deliver to each webhook
        delivered_count = 0
        for webhook in webhooks:
            try:
                success = self.deliver_with_retry(webhook, event_type, event_data)
                if success:
                    delivered_count += 1
            except Exception as e:
                try:
                    self.db.rollback()
                except Exception:
                    logger.error(
                        "Failed to rollback DB session after webhook delivery error",
                        exc_info=True
                    )
                logger.error(
                    f"Failed to deliver webhook {webhook.id}: {str(e)}",
                    exc_info=True
                )
        
        logger.info(
            f"Delivered {delivered_count}/{len(webhooks)} webhooks for {event_type}"
        )
        return delivered_count


def trigger_webhook_event(
    db: Session,
    event_type: str,
    event_data: Dict[str, Any],
    user_id: Optional[int] = None
) -> int:
    """
    Convenience function to trigger webhook event.
    
    Args:
        db: Database session
        event_type: Event type
        event_data: Event payload
        user_id: Optional user ID filter
        
    Returns:
        Number of webhooks triggered
    """
    service = WebhookService(db)
    try:
        return service.trigger_event(event_type, event_data, user_id)
    except Exception:
        try:
            db.rollback()
        except Exception:
            logger.error(
                "Failed to rollback DB session after trigger_webhook_event error",
                exc_info=True
            )
        raise


def _dispatch_webhook_event_worker(
    event_type: str,
    event_data: Dict[str, Any],
    user_id: Optional[int] = None,
) -> None:
    """Deliver workflow webhooks outside the request path using a fresh DB session."""
    db = SessionLocal()
    try:
        trigger_webhook_event(db, event_type, event_data, user_id)
    except Exception:
        logger.error(
            "Background webhook dispatch failed for %s",
            event_type,
            exc_info=True,
        )
    finally:
        db.close()


def dispatch_webhook_event_async(
    event_type: str,
    event_data: Dict[str, Any],
    user_id: Optional[int] = None,
) -> None:
    """Fire-and-forget wrapper for non-critical workflow webhook delivery."""
    thread = Thread(
        target=_dispatch_webhook_event_worker,
        args=(event_type, event_data, user_id),
        daemon=True,
        name=f"webhook-{event_type}",
    )
    thread.start()


# ==========================================
# Event Payload Builders
# ==========================================

def build_refinement_started_payload(query_id: int, user_id: int, framework: str) -> Dict[str, Any]:
    """Build payload for refinement.started event."""
    return {
        "query_id": query_id,
        "user_id": user_id,
        "framework": framework,
        "timestamp": datetime.now(timezone.utc).isoformat()
    }


def build_refinement_step_completed_payload(
    query_id: int,
    dimension: str,
    aspect: str,
    answer: str
) -> Dict[str, Any]:
    """Build payload for refinement.step_completed event."""
    return {
        "query_id": query_id,
        "dimension": dimension,
        "aspect": aspect,
        "answer": answer,
        "timestamp": datetime.now(timezone.utc).isoformat()
    }


def build_refinement_complete_payload(query_id: int, total_steps: int) -> Dict[str, Any]:
    """Build payload for refinement.complete event."""
    return {
        "query_id": query_id,
        "total_steps": total_steps,
        "timestamp": datetime.now(timezone.utc).isoformat()
    }


def build_synthesis_started_payload(query_id: int, initial_query: str) -> Dict[str, Any]:
    """Build payload for synthesis.started event."""
    return {
        "query_id": query_id,
        "initial_query": initial_query,
        "timestamp": datetime.now(timezone.utc).isoformat()
    }


def build_synthesis_complete_payload(
    query_id: int,
    refined_query: str,
    initial_query: str
) -> Dict[str, Any]:
    """Build payload for synthesis.complete event."""
    return {
        "query_id": query_id,
        "initial_query": initial_query,
        "refined_query": refined_query,
        "timestamp": datetime.now(timezone.utc).isoformat()
    }


def build_query_created_payload(query_id: int, initial_query: str, user_id: int) -> Dict[str, Any]:
    """Build payload for query.created event."""
    return {
        "query_id": query_id,
        "initial_query": initial_query,
        "user_id": user_id,
        "timestamp": datetime.now(timezone.utc).isoformat()
    }


def build_session_created_payload(session_id: str, query_id: int) -> Dict[str, Any]:
    """Build payload for session.created event."""
    return {
        "session_id": session_id,
        "query_id": query_id,
        "timestamp": datetime.now(timezone.utc).isoformat()
    }


def build_session_ended_payload(session_id: str, query_id: int, completed: bool) -> Dict[str, Any]:
    """Build payload for session.ended event."""
    return {
        "session_id": session_id,
        "query_id": query_id,
        "completed": completed,
        "timestamp": datetime.now(timezone.utc).isoformat()
    }
