#!/usr/bin/env python3
"""Quick test of /status endpoint with proper authentication"""
import requests
import json

BASE_URL = "http://localhost:8000"

# Login
print("Logging in...")
login_resp = requests.post(
    f"{BASE_URL}/api/auth/login",
    data={"username": "testuser", "password": "Pass123!"}
)
if login_resp.status_code != 200:
    print(f"Login failed: {login_resp.status_code}")
    print(json.dumps(login_resp.json(), indent=2))
    exit(1)

token = login_resp.json()["access_token"]
headers = {"Authorization": f"Bearer {token}"}

# Try with existing session 818
print("\nTrying /status with query 818...")
status_resp = requests.post(
    f"{BASE_URL}/api/refinement/queries/818/answer",
    headers=headers,
    json={"answer": "/status"}
)

print(f"Status Code: {status_resp.status_code}")
print(f"Response:")
print(json.dumps(status_resp.json(), indent=2))
