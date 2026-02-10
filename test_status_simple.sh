#!/bin/bash

# Simple script to test /status command via API
# This bypasses the browser entirely

echo "=== Testing /status command directly ==="
echo ""
echo "Step 1: Login"
TOKEN=$(curl -s -X POST http://localhost:8000/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username":"testuser","password":"Pass123!"}' \
  | python3 -c "import sys, json; print(json.load(sys.stdin)['access_token'])")

if [ -z "$TOKEN" ]; then
    echo "ERROR: Failed to login. Check credentials."
    exit 1
fi

echo "✓ Logged in successfully"
echo ""

echo "Step 2: Start new session"
SESSION_DATA=$(curl -s -X POST http://localhost:8000/api/refinement/queries \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"user_query":"How can I improve my sales process?","framework_name":"business_strategy"}')

QUERY_ID=$(echo "$SESSION_DATA" | python3 -c "import sys, json; print(json.load(sys.stdin)['query']['id'])")

echo "✓ Session started with query_id: $QUERY_ID"
echo ""

echo "Step 3: Send /status command"
echo ""
curl -X POST "http://localhost:8000/api/refinement/queries/${QUERY_ID}/answer" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"answer":"/status"}' \
  | python3 -m json.tool

echo ""
echo "=== Test complete ==="
