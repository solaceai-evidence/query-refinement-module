#!/usr/bin/env python3
"""Test /status command via direct API calls"""
import requests
import json

BASE_URL = "http://localhost:8000"

print("=== Testing /status command ===\n")

# Step 1: Login
print("Step 1: Login...")
login_response = requests.post(
    f"{BASE_URL}/api/auth/login",
    data={"username": "testuser", "password": "Pass123!"}
)

if login_response.status_code != 200:
    print(f"❌ Login failed: {login_response.status_code}")
    print(json.dumps(login_response.json(), indent=2))
    exit(1)

token = login_response.json()["access_token"]
print("✓ Login successful\n")

# Step 2: Start session
print("Step 2: Start refinement session...")
headers = {"Authorization": f"Bearer {token}"}
session_response = requests.post(
    f"{BASE_URL}/api/refinement/queries",
    headers=headers,
    json={
        "user_query": "How can I improve my sales process?",
        "framework_name": "business_strategy"
    }
)

if session_response.status_code != 201:
    print(f"❌ Session creation failed: {session_response.status_code}")
    print(json.dumps(session_response.json(), indent=2))
    exit(1)

query_id = session_response.json()["query"]["id"]
print(f"✓ Session created (query_id: {query_id})\n")

# Step 3: Send /status command
print("Step 3: Testing /status command...")
status_response = requests.post(
    f"{BASE_URL}/api/refinement/queries/{query_id}/answer",
    headers=headers,
    json={"answer": "/status"}
)

print(f"\nResponse Status: {status_response.status_code}")
print(f"Response Headers:")
print(f"  Content-Type: {status_response.headers.get('Content-Type')}")
print(f"  Access-Control-Allow-Origin: {status_response.headers.get('Access-Control-Allow-Origin')}")
print(f"\nResponse Body:")
print(json.dumps(status_response.json(), indent=2))

print("\n=== Test Complete ===")
