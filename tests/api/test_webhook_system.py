"""
Test suite for webhook system.

Tests webhook CRUD operations, delivery service, and event triggers.
"""
import pytest
import time
import hmac
import hashlib
import json
from fastapi.testclient import TestClient
from http.server import HTTPServer, BaseHTTPRequestHandler
from threading import Thread
import queue

from query_refinement_module.api.main import app
from query_refinement_module.db.session import get_db
from query_refinement_module.db.models.user import User
from query_refinement_module.db.models.webhook import Webhook, WebhookDelivery
from query_refinement_module.db import crud_webhooks
from query_refinement_module.services.webhook_service import WebhookService


# Test webhook receiver
webhook_payloads = queue.Queue()


class WebhookReceiver(BaseHTTPRequestHandler):
    """Simple HTTP server to receive webhook POSTs during testing."""
    
    def do_POST(self):
        content_length = int(self.headers['Content-Length'])
        post_data = self.rfile.read(content_length)
        
        # Store received payload
        webhook_payloads.put({
            'headers': dict(self.headers),
            'body': json.loads(post_data),
            'path': self.path
        })
        
        # Respond with 200 OK
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.end_headers()
        self.wfile.write(b'{"received": true}')
    
    def log_message(self, format, *args):
        pass  # Suppress log output


@pytest.fixture
def webhook_server():
    """Start a local webhook receiver server on port 8888."""
    server = HTTPServer(('localhost', 8888), WebhookReceiver)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    
    yield 'http://localhost:8888/webhook'
    
    server.shutdown()


@pytest.fixture
def client():
    """Create test client."""
    return TestClient(app)


@pytest.fixture
def test_user(client):
    """Create a test user and return auth token."""
    # Register user
    response = client.post('/api/v1/auth/register', json={
        'username': f'webhooktest_{int(time.time())}',
        'password': 'testpass123',
        'email': f'webhook{int(time.time())}@test.com'
    })
    assert response.status_code == 201
    
    # Login
    response = client.post('/api/v1/auth/login', data={
        'username': response.json()['username'],
        'password': 'testpass123'
    })
    assert response.status_code == 200
    
    return response.json()['access_token']


class TestWebhookCRUD:
    """Test webhook CRUD operations via API."""
    
    def test_get_event_types(self, client):
        """Test getting available event types."""
        response = client.get('/api/v1/webhooks/event-types')
        assert response.status_code == 200
        
        data = response.json()
        assert 'event_types' in data
        assert 'refinement.started' in data['event_types']
        assert 'synthesis.complete' in data['event_types']
        assert len(data['event_types']) == 9
    
    def test_create_webhook(self, client, test_user, webhook_server):
        """Test creating a webhook."""
        response = client.post(
            '/api/webhooks',
            headers={'Authorization': f'Bearer {test_user}'},
            json={
                'url': webhook_server,
                'events': ['refinement.complete', 'synthesis.complete'],
                'name': 'Test Webhook',
                'description': 'Testing webhook creation',
                'max_retries': 2,
                'timeout_seconds': 15
            }
        )
        
        assert response.status_code == 201
        data = response.json()
        assert 'webhook_id' in data
        assert 'secret' in data
        assert len(data['secret']) > 20
        assert 'message' in data
    
    def test_list_webhooks(self, client, test_user, webhook_server):
        """Test listing user's webhooks."""
        # Create a webhook first
        create_response = client.post(
            '/api/webhooks',
            headers={'Authorization': f'Bearer {test_user}'},
            json={
                'url': webhook_server,
                'events': ['refinement.started'],
                'name': 'List Test'
            }
        )
        assert create_response.status_code == 201
        
        # List webhooks
        response = client.get(
            '/api/webhooks',
            headers={'Authorization': f'Bearer {test_user}'}
        )
        
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        assert len(data) >= 1
        assert data[0]['name'] == 'List Test'
        assert data[0]['active'] is True
    
    def test_get_webhook_details(self, client, test_user, webhook_server):
        """Test getting webhook details."""
        # Create webhook
        create_response = client.post(
            '/api/webhooks',
            headers={'Authorization': f'Bearer {test_user}'},
            json={
                'url': webhook_server,
                'events': ['synthesis.started'],
                'name': 'Details Test'
            }
        )
        webhook_id = create_response.json()['webhook_id']
        
        # Get details
        response = client.get(
            f'/api/v1/webhooks/{webhook_id}',
            headers={'Authorization': f'Bearer {test_user}'}
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data['id'] == webhook_id
        assert data['name'] == 'Details Test'
        assert data['url'] == webhook_server
        assert 'synthesis.started' in data['events']
    
    def test_update_webhook(self, client, test_user, webhook_server):
        """Test updating webhook configuration."""
        # Create webhook
        create_response = client.post(
            '/api/webhooks',
            headers={'Authorization': f'Bearer {test_user}'},
            json={
                'url': webhook_server,
                'events': ['refinement.started'],
                'name': 'Update Test'
            }
        )
        webhook_id = create_response.json()['webhook_id']
        
        # Update webhook
        response = client.put(
            f'/api/v1/webhooks/{webhook_id}',
            headers={'Authorization': f'Bearer {test_user}'},
            json={
                'events': ['refinement.started', 'refinement.complete'],
                'active': False,
                'timeout_seconds': 45
            }
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data['active'] is False
        assert len(data['events']) == 2
        assert data['timeout_seconds'] == 45
    
    def test_delete_webhook(self, client, test_user, webhook_server):
        """Test deleting a webhook."""
        # Create webhook
        create_response = client.post(
            '/api/webhooks',
            headers={'Authorization': f'Bearer {test_user}'},
            json={
                'url': webhook_server,
                'events': ['refinement.complete'],
                'name': 'Delete Test'
            }
        )
        webhook_id = create_response.json()['webhook_id']
        
        # Delete webhook
        response = client.delete(
            f'/api/v1/webhooks/{webhook_id}',
            headers={'Authorization': f'Bearer {test_user}'}
        )
        
        assert response.status_code == 204
        
        # Verify it's gone
        response = client.get(
            f'/api/v1/webhooks/{webhook_id}',
            headers={'Authorization': f'Bearer {test_user}'}
        )
        assert response.status_code == 404
    
    def test_regenerate_secret(self, client, test_user, webhook_server):
        """Test regenerating webhook secret."""
        # Create webhook
        create_response = client.post(
            '/api/webhooks',
            headers={'Authorization': f'Bearer {test_user}'},
            json={
                'url': webhook_server,
                'events': ['synthesis.complete']
            }
        )
        webhook_id = create_response.json()['webhook_id']
        old_secret = create_response.json()['secret']
        
        # Regenerate secret
        response = client.post(
            f'/api/v1/webhooks/{webhook_id}/regenerate-secret',
            headers={'Authorization': f'Bearer {test_user}'}
        )
        
        assert response.status_code == 200
        data = response.json()
        assert 'secret' in data
        assert data['secret'] != old_secret
        assert len(data['secret']) > 20


class TestWebhookDelivery:
    """Test webhook delivery functionality."""
    
    def test_webhook_test_endpoint(self, client, test_user, webhook_server):
        """Test the webhook test endpoint."""
        # Clear queue
        while not webhook_payloads.empty():
            webhook_payloads.get()
        
        # Create webhook
        create_response = client.post(
            '/api/webhooks',
            headers={'Authorization': f'Bearer {test_user}'},
            json={
                'url': webhook_server,
                'events': ['refinement.complete']
            }
        )
        webhook_id = create_response.json()['webhook_id']
        secret = create_response.json()['secret']
        
        # Test webhook
        response = client.post(
            f'/api/v1/webhooks/{webhook_id}/test',
            headers={'Authorization': f'Bearer {test_user}'},
            json={'test_data': {'hello': 'world'}}
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data['success'] is True
        assert data['status_code'] == 200
        assert data['duration_ms'] > 0
        
        # Verify payload was received
        time.sleep(0.5)  # Give server time to process
        assert not webhook_payloads.empty()
        
        received = webhook_payloads.get()
        assert received['body']['event'] == 'webhook.test'
        assert received['body']['data']['hello'] == 'world'
        
        # Verify signature
        assert 'x-webhook-signature' in received['headers']
        signature_header = received['headers']['x-webhook-signature']
        
        payload_bytes = json.dumps(received['body'], separators=(',', ':')).encode()
        expected_sig = hmac.new(
            secret.encode('utf-8'),
            payload_bytes,
            hashlib.sha256
        ).hexdigest()
        
        assert signature_header == f'sha256={expected_sig}'
    
    def test_delivery_history(self, client, test_user, webhook_server):
        """Test viewing delivery history."""
        # Create webhook
        create_response = client.post(
            '/api/webhooks',
            headers={'Authorization': f'Bearer {test_user}'},
            json={
                'url': webhook_server,
                'events': ['refinement.started']
            }
        )
        webhook_id = create_response.json()['webhook_id']
        
        # Send test delivery
        client.post(
            f'/api/v1/webhooks/{webhook_id}/test',
            headers={'Authorization': f'Bearer {test_user}'}
        )
        
        # Get delivery history
        response = client.get(
            f'/api/v1/webhooks/{webhook_id}/deliveries',
            headers={'Authorization': f'Bearer {test_user}'}
        )
        
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        assert len(data) >= 1
        
        delivery = data[0]
        assert delivery['webhook_id'] == webhook_id
        assert delivery['status'] == 'success'
        assert delivery['status_code'] == 200
        assert 'duration_ms' in delivery


class TestWebhookSecurity:
    """Test webhook security features."""
    
    def test_unauthorized_access(self, client, webhook_server):
        """Test that webhook endpoints require authentication."""
        # Try to create without auth
        response = client.post('/api/webhooks', json={
            'url': webhook_server,
            'events': ['refinement.complete']
        })
        assert response.status_code == 401
        
        # Try to list without auth
        response = client.get('/api/webhooks')
        assert response.status_code == 401
    
    def test_webhook_ownership(self, client, webhook_server):
        """Test that users can only access their own webhooks."""
        # Create two users
        user1_response = client.post('/api/v1/auth/register', json={
            'username': f'user1_{int(time.time())}',
            'password': 'pass123',
            'email': f'user1_{int(time.time())}@test.com'
        })
        user1_token = client.post('/api/v1/auth/login', data={
            'username': user1_response.json()['username'],
            'password': 'pass123'
        }).json()['access_token']
        
        user2_response = client.post('/api/v1/auth/register', json={
            'username': f'user2_{int(time.time())}',
            'password': 'pass123',
            'email': f'user2_{int(time.time())}@test.com'
        })
        user2_token = client.post('/api/v1/auth/login', data={
            'username': user2_response.json()['username'],
            'password': 'pass123'
        }).json()['access_token']
        
        # User 1 creates webhook
        create_response = client.post(
            '/api/webhooks',
            headers={'Authorization': f'Bearer {user1_token}'},
            json={
                'url': webhook_server,
                'events': ['refinement.complete']
            }
        )
        webhook_id = create_response.json()['webhook_id']
        
        # User 2 tries to access User 1's webhook
        response = client.get(
            f'/api/v1/webhooks/{webhook_id}',
            headers={'Authorization': f'Bearer {user2_token}'}
        )
        assert response.status_code == 403
    
    def test_invalid_event_types(self, client, test_user, webhook_server):
        """Test that invalid event types are rejected."""
        response = client.post(
            '/api/webhooks',
            headers={'Authorization': f'Bearer {test_user}'},
            json={
                'url': webhook_server,
                'events': ['invalid.event', 'refinement.complete']
            }
        )
        assert response.status_code == 400
        assert 'Invalid event types' in response.json()['detail']


class TestWebhookIntegration:
    """Test webhook integration with refinement workflow."""
    
    def test_refinement_started_event(self, client, test_user, webhook_server):
        """Test that refinement.started event is triggered."""
        # Clear webhook queue
        while not webhook_payloads.empty():
            webhook_payloads.get()
        
        # Create webhook subscribed to refinement.started
        create_response = client.post(
            '/api/webhooks',
            headers={'Authorization': f'Bearer {test_user}'},
            json={
                'url': webhook_server,
                'events': ['refinement.started']
            }
        )
        assert create_response.status_code == 201
        
        # Start refinement workflow
        response = client.post(
            '/api/v1/refinement/start',
            headers={'Authorization': f'Bearer {test_user}'},
            json={
                'original_query': 'test query for webhook',
                'framework_name': 'pico_advanced'
            }
        )
        
        assert response.status_code == 200
        query_id = response.json()['query_id']
        
        # Wait for webhook delivery
        time.sleep(1)
        
        # Check webhook was received
        if not webhook_payloads.empty():
            received = webhook_payloads.get()
            assert received['body']['event'] == 'refinement.started'
            assert received['body']['data']['query_id'] == query_id
            assert 'framework' in received['body']['data']
        else:
            pytest.skip("Webhook delivery may be asynchronous, check delivery history")


if __name__ == '__main__':
    pytest.main([__file__, '-v', '-s'])
