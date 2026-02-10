#!/usr/bin/env python3
"""Test the /status command API endpoint directly."""
import requests
import json
import sys

BASE_URL = 'http://localhost:8000'

# Use the actual password - you'll need to update this
USERNAME = 'jedoal'
PASSWORD = input("Enter password for jedoal: ").strip()

print("1. Logging in...")
login_resp = requests.post(f'{BASE_URL}/api/auth/login', 
    json={'username': USERNAME, 'password': PASSWORD})

if login_resp.status_code != 200:
    print(f'❌ Login failed: {login_resp.text}')
    sys.exit(1)

token = login_resp.json()['access_token']
headers = {'Authorization': f'Bearer {token}', 'Content-Type': 'application/json'}
print(f'✓ Logged in successfully')

print("\n2. Starting new refinement session...")
start_resp = requests.post(f'{BASE_URL}/api/refinement/start', 
    json={
        'framework_name': 'pico_advanced', 
        'original_query': 'test query for status command debugging'
    },
    headers=headers)

if start_resp.status_code != 201:
    print(f'❌ Start failed: {start_resp.text}')
    sys.exit(1)

query_id = start_resp.json()['query_id']
print(f'✓ Created session with query_id: {query_id}')

print("\n3. Sending /status command...")
status_resp = requests.post(
    f'{BASE_URL}/api/refinement/queries/{query_id}/answer',
    json={'answer': '/status'},
    headers=headers
)

print(f'\n=== STATUS COMMAND RESPONSE ===')
print(f'Status Code: {status_resp.status_code}')
print(f'\nResponse Headers:')
for key, value in status_resp.headers.items():
    if 'content' in key.lower() or 'type' in key.lower():
        print(f'  {key}: {value}')

print(f'\nResponse Body:')
try:
    data = status_resp.json()
    print(json.dumps(data, indent=2))
    
    # Check for step_summary
    if 'step_summary' in data:
        print(f'\n✓ step_summary EXISTS in response')
        print(f'step_summary content:')
        print(json.dumps(data['step_summary'], indent=2))
    else:
        print(f'\n❌ step_summary NOT FOUND in response')
        print(f'Available keys: {list(data.keys())}')
except Exception as e:
    print(f'❌ Failed to parse JSON: {e}')
    print(f'Raw response: {status_resp.text}')

print('\n=== END ===')
