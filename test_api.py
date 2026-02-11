#!/usr/bin/env python3
import requests

BASE = "http://localhost:8000/api/v1"

# Register
print("1. Registering...")
r = requests.post(f"{BASE}/api/auth/register", json={
    "username": "quicktest",
    "password": "TestPass123!"
})
print(f"   Status: {r.status_code}")

# Login
print("2. Logging in...")
r = requests.post(f"{BASE}/api/auth/login", data={
    "username": "quicktest",
    "password": "TestPass123!",
    "grant_type": "password"
})
token = r.json()["access_token"]
print(f"   ✓ Got token: {token[:20]}...")

# Start refinement with CORS headers
print("3. Starting refinement...")
r = requests.post(
    f"{BASE}/refinement/start",
    headers={
        "Authorization": f"Bearer {token}",
        "Origin": "http://localhost:5173"
    },
    json={
        "framework_name": "pico_advanced",
        "original_query": "childhood obesity in urban areas"
    }
)
print(f"   Status: {r.status_code}")
print(f"   CORS header: {r.headers.get('access-control-allow-origin', 'MISSING')}")
if r.status_code == 201:
    data = r.json()
    print(f"   ✅ SUCCESS!")
    print(f"   Query ID: {data['query_id']}")
    print(f"   Session ID: {data['session_id']}")
    print(f"   Ready for synthesis: {data.get('ready_for_synthesis', False)}")
else:
    print(f"   ❌ ERROR: {r.text[:300]}")
