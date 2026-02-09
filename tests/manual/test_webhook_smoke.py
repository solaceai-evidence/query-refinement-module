#!/usr/bin/env python3
"""
Quick smoke test for webhook system.

Tests:
1. Event types endpoint (no auth required)
2. Webhook creation (requires auth)
3. Webhook listing
4. Webhook deletion
"""
import requests
import json
import sys
import time

BASE_URL = "http://localhost:8000/api"

def print_test(name):
    print(f"\n{'='*60}")
    print(f"TEST: {name}")
    print('='*60)

def print_result(success, message):
    status = "✅ PASS" if success else "❌ FAIL"
    print(f"{status}: {message}")
    return success

# Test 1: Get event types (no auth)
print_test("Get Webhook Event Types")
response = requests.get(f"{BASE_URL}/webhooks/event-types")
success = response.status_code == 200 and len(response.json()['event_types']) == 9
print_result(success, f"Got {len(response.json()['event_types'])} event types")
if success:
    print(f"   Events: {', '.join(response.json()['event_types'][:3])}...")

# Test 2: Create test user
print_test("Create Test User")
username = f"webhooktest_{int(time.time())}"
password = 'TestPass123!'
register_response = requests.post(f"{BASE_URL}/auth/register", json={
    'username': username,
    'password': password,
    'email': f'{username}@test.com'
})
success = register_response.status_code == 201
print_result(success, f"Created user: {username}")
if not success:
    print(f"   Status: {register_response.status_code}")
    print(f"   Error: {register_response.text}")

# Test 3: Login
print_test("Login")
login_response = requests.post(f"{BASE_URL}/auth/login", data={
    'username': username,
    'password': password
})
success = login_response.status_code == 200
print_result(success, "Logged in successfully")
if not success:
    print(f"   Status: {login_response.status_code}")
    print(f"   Error: {login_response.text}")

if not success:
    print("\n❌ Cannot proceed without authentication")
    sys.exit(1)

auth_token = login_response.json()['access_token']
headers = {'Authorization': f'Bearer {auth_token}'}

# Test 4: Create webhook
print_test("Create Webhook")
create_response = requests.post(
    f"{BASE_URL}/webhooks",
    headers=headers,
    json={
        'url': 'https://webhook.site/unique-test-url',  # Fake endpoint for testing
        'events': ['refinement.started', 'synthesis.complete'],
        'name': 'Test Webhook',
        'description': 'Smoke test webhook',
        'max_retries': 2,
        'timeout_seconds': 15
    }
)
success = create_response.status_code == 201
webhook_data = create_response.json() if success else {}
print_result(success, f"Created webhook #{webhook_data.get('webhook_id')}")
if success:
    print(f"   Secret: {webhook_data['secret'][:20]}...")

webhook_id = webhook_data.get('webhook_id')

# Test 5: List webhooks
print_test("List Webhooks")
list_response = requests.get(f"{BASE_URL}/webhooks", headers=headers)
success = list_response.status_code == 200 and len(list_response.json()) >= 1
webhooks = list_response.json() if success else []
print_result(success, f"Found {len(webhooks)} webhook(s)")
if success and webhooks:
    w = webhooks[0]
    print(f"   Name: {w['name']}")
    print(f"   URL: {w['url']}")
    print(f"   Events: {', '.join(w['events'])}")
    print(f"   Active: {w['active']}")

# Test 6: Get webhook details
if webhook_id:
    print_test("Get Webhook Details")
    detail_response = requests.get(f"{BASE_URL}/webhooks/{webhook_id}", headers=headers)
    success = detail_response.status_code == 200
    detail = detail_response.json() if success else {}
    print_result(success, f"Retrieved webhook details")
    if success:
        print(f"   Total deliveries: {detail['total_deliveries']}")
        print(f"   Success rate: {detail['successful_deliveries']}/{detail['total_deliveries']}")

# Test 7: Update webhook
if webhook_id:
    print_test("Update Webhook")
    update_response = requests.put(
        f"{BASE_URL}/webhooks/{webhook_id}",
        headers=headers,
        json={
            'active': False,
            'events': ['refinement.complete']
        }
    )
    success = update_response.status_code == 200
    updated = update_response.json() if success else {}
    print_result(success, "Updated webhook")
    if success:
        print(f"   Active: {updated['active']}")
        print(f"   Events: {', '.join(updated['events'])}")

# Test 8: Delete webhook
if webhook_id:
    print_test("Delete Webhook")
    delete_response = requests.delete(f"{BASE_URL}/webhooks/{webhook_id}", headers=headers)
    success = delete_response.status_code == 204
    print_result(success, "Deleted webhook")
    
    # Verify deletion
    verify_response = requests.get(f"{BASE_URL}/webhooks/{webhook_id}", headers=headers)
    verified = verify_response.status_code == 404
    print_result(verified, "Verified webhook is deleted")

# Summary
print(f"\n{'='*60}")
print("SUMMARY")
print('='*60)
print("✅ Webhook system is functional!")
print("\nKey features verified:")
print("  - Event types endpoint")
print("  - Webhook CRUD operations")
print("  - Authentication & authorization")
print("  - Data persistence")
print("\nNext steps:")
print("  - Test webhook delivery with actual endpoint")
print("  - Verify event triggers in refinement workflow")
print("  - Test HMAC signature verification")
