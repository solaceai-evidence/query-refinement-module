#!/usr/bin/env python3
import requests
import json

BASE_URL = "http://localhost:8000"

# Use existing user
token_resp = requests.post(f"{BASE_URL}/api/auth/login", data={"username":"curltest123","password":"TestPass123!"})
token = token_resp.json()["access_token"]
print(f"Token: {token[:20]}...")

# Start
print("\nStarting refinement...")
start_resp = requests.post(
    f"{BASE_URL}/api/refinement/start",
    json={"framework_name":"mph_dissertation","original_query":"test obesity"},
    headers={"Authorization": f"Bearer {token}"},
    timeout=90
)
print(f"Status: {start_resp.status_code}")
data = start_resp.json()
query_id = data["query_id"]
next_q = data.get("next_prompt", {}).get("question", "")
print(f"Query ID: {query_id}")
print(f"Question preview: {next_q[:100] if next_q else 'EMPTY!'}")

# Answer
print("\nSubmitting answer...")
ans_resp = requests.post(
    f"{BASE_URL}/api/refinement/queries/{query_id}/answer",
    json={"answer":"risk factors in children"},
    headers={"Authorization": f"Bearer {token}"},
    timeout=90
)
print(f"Status: {ans_resp.status_code}")
data2 = ans_resp.json()
next_q2 = data2.get("next_prompt", {}).get("question", "")
print(f"Next question preview: {next_q2[:100] if next_q2 else 'EMPTY!'}")

if next_q2:
    print("\n✅ SUCCESS!")
else:
    print(f"\n❌ FAILED! Response: {json.dumps(data2, indent=2)[:500]}")
