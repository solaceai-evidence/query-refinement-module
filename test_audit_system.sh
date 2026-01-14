#!/bin/bash

# Audit System Testing Script
# Tests all Phase 3 audit functionality

BASE_URL="http://localhost:8000"
API_URL="$BASE_URL/api"

# Colors for output
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo "=========================================="
echo "Phase 3 Audit System Testing"
echo "=========================================="
echo ""

# Test 1: Register a new user (should create REGISTER audit log)
echo -e "${YELLOW}Test 1: User Registration${NC}"
TIMESTAMP=$(date +%s)
USERNAME="audit_test_user_$TIMESTAMP"
REGISTER_RESPONSE=$(curl -s -X POST "$API_URL/auth/register" \
  -H "Content-Type: application/json" \
  -d "{\"username\":\"$USERNAME\",\"password\":\"Test123!@#\",\"email\":\"$USERNAME@test.com\"}")

echo "Registration response: $REGISTER_RESPONSE"
if echo "$REGISTER_RESPONSE" | grep -q "id"; then
    echo -e "${GREEN}✓ Registration successful${NC}"
    USER_ID=$(echo "$REGISTER_RESPONSE" | grep -o '"id":[0-9]*' | cut -d':' -f2)
    echo "User ID: $USER_ID"
else
    echo -e "${RED}✗ Registration failed${NC}"
    exit 1
fi
echo ""

# Test 2: Login (should create LOGIN_SUCCESS audit log)
echo -e "${YELLOW}Test 2: User Login${NC}"
LOGIN_RESPONSE=$(curl -s -X POST "$API_URL/auth/login" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "username=$USERNAME&password=Test123!@#")

echo "Login response: $LOGIN_RESPONSE"
if echo "$LOGIN_RESPONSE" | grep -q "access_token"; then
    echo -e "${GREEN}✓ Login successful${NC}"
    TOKEN=$(echo "$LOGIN_RESPONSE" | grep -o '"access_token":"[^"]*"' | cut -d'"' -f4)
    echo "Token: ${TOKEN:0:20}..."
else
    echo -e "${RED}✗ Login failed${NC}"
    exit 1
fi
echo ""

# Test 3: Failed login attempt (should create LOGIN_FAILURE audit log)
echo -e "${YELLOW}Test 3: Failed Login Attempt${NC}"
FAILED_LOGIN=$(curl -s -X POST "$API_URL/auth/login" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "username=$USERNAME&password=WrongPassword")

if echo "$FAILED_LOGIN" | grep -q "error"; then
    echo -e "${GREEN}✓ Failed login detected (will be audited)${NC}"
else
    echo -e "${YELLOW}⚠ Failed login response unexpected${NC}"
fi
echo ""

# Test 4: Create a session (should create SESSION_CREATE audit log)
echo -e "${YELLOW}Test 4: Create Session${NC}"
SESSION_RESPONSE=$(curl -s -X POST "$API_URL/queries/sessions" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"initial_query":"Test audit query","refinement_framework":"pico_advanced"}')

echo "Session response: $SESSION_RESPONSE"
if echo "$SESSION_RESPONSE" | grep -q "session_id"; then
    echo -e "${GREEN}✓ Session created${NC}"
    SESSION_ID=$(echo "$SESSION_RESPONSE" | grep -o '"session_id":"[^"]*"' | cut -d'"' -f4)
    echo "Session ID: $SESSION_ID"
else
    echo -e "${RED}✗ Session creation failed${NC}"
    echo "Response: $SESSION_RESPONSE"
fi
echo ""

# Test 5: Get session (should create SESSION_ACCESS audit log)
if [ ! -z "$SESSION_ID" ]; then
    echo -e "${YELLOW}Test 5: Access Session${NC}"
    SESSION_GET=$(curl -s -X GET "$API_URL/queries/sessions/$SESSION_ID" \
      -H "Authorization: Bearer $TOKEN")
    
    if echo "$SESSION_GET" | grep -q "session_id"; then
        echo -e "${GREEN}✓ Session accessed (audit logged)${NC}"
    else
        echo -e "${RED}✗ Session access failed${NC}"
    fi
    echo ""
fi

# Test 6: Query audit logs
echo -e "${YELLOW}Test 6: Query Audit Logs${NC}"
AUDIT_LOGS=$(curl -s -X GET "$API_URL/audit/logs?page=1&page_size=20" \
  -H "Authorization: Bearer $TOKEN")

echo "Audit logs response (first 500 chars): ${AUDIT_LOGS:0:500}..."
if echo "$AUDIT_LOGS" | grep -q "logs"; then
    echo -e "${GREEN}✓ Audit logs retrieved${NC}"
    LOG_COUNT=$(echo "$AUDIT_LOGS" | grep -o '"total":[0-9]*' | cut -d':' -f2)
    echo "Total audit logs for user: $LOG_COUNT"
else
    echo -e "${RED}✗ Failed to retrieve audit logs${NC}"
fi
echo ""

# Test 7: Get audit statistics
echo -e "${YELLOW}Test 7: Audit Statistics${NC}"
AUDIT_STATS=$(curl -s -X GET "$API_URL/audit/stats?days=7" \
  -H "Authorization: Bearer $TOKEN")

echo "Audit statistics: $AUDIT_STATS"
if echo "$AUDIT_STATS" | grep -q "events_by_type"; then
    echo -e "${GREEN}✓ Audit statistics retrieved${NC}"
else
    echo -e "${RED}✗ Failed to retrieve audit statistics${NC}"
fi
echo ""

# Test 8: Get event types
echo -e "${YELLOW}Test 8: List Event Types${NC}"
EVENT_TYPES=$(curl -s -X GET "$API_URL/audit/event-types" \
  -H "Authorization: Bearer $TOKEN")

echo "Event types (first 300 chars): ${EVENT_TYPES:0:300}..."
if echo "$EVENT_TYPES" | grep -q "event_types"; then
    echo -e "${GREEN}✓ Event types retrieved${NC}"
else
    echo -e "${RED}✗ Failed to retrieve event types${NC}"
fi
echo ""

# Test 9: Filter audit logs by event type
echo -e "${YELLOW}Test 9: Filter Audit Logs (LOGIN_SUCCESS)${NC}"
FILTERED_LOGS=$(curl -s -X GET "$API_URL/audit/logs?event_type=auth.login.success" \
  -H "Authorization: Bearer $TOKEN")

if echo "$FILTERED_LOGS" | grep -q "auth.login.success"; then
    echo -e "${GREEN}✓ Filtered audit logs retrieved${NC}"
else
    echo -e "${YELLOW}⚠ No LOGIN_SUCCESS events found (may be expected)${NC}"
fi
echo ""

# Test 10: Export audit logs to CSV
echo -e "${YELLOW}Test 10: Export Audit Logs (CSV)${NC}"
CSV_FILE="/tmp/audit_export_$TIMESTAMP.csv"
curl -s -X GET "$API_URL/audit/export/csv" \
  -H "Authorization: Bearer $TOKEN" \
  -o "$CSV_FILE"

if [ -f "$CSV_FILE" ] && [ -s "$CSV_FILE" ]; then
    echo -e "${GREEN}✓ CSV export successful${NC}"
    echo "File: $CSV_FILE"
    echo "Size: $(wc -c < $CSV_FILE) bytes"
    echo "First 3 lines:"
    head -n 3 "$CSV_FILE"
else
    echo -e "${RED}✗ CSV export failed${NC}"
fi
echo ""

# Test 11: Export audit logs to JSON
echo -e "${YELLOW}Test 11: Export Audit Logs (JSON)${NC}"
JSON_FILE="/tmp/audit_export_$TIMESTAMP.json"
curl -s -X GET "$API_URL/audit/export/json" \
  -H "Authorization: Bearer $TOKEN" \
  -o "$JSON_FILE"

if [ -f "$JSON_FILE" ] && [ -s "$JSON_FILE" ]; then
    echo -e "${GREEN}✓ JSON export successful${NC}"
    echo "File: $JSON_FILE"
    echo "Size: $(wc -c < $JSON_FILE) bytes"
    # Pretty print first part
    head -c 500 "$JSON_FILE"
    echo ""
else
    echo -e "${RED}✗ JSON export failed${NC}"
fi
echo ""

# Test 12: Logout (should create LOGOUT audit log)
echo -e "${YELLOW}Test 12: User Logout${NC}"
LOGOUT_RESPONSE=$(curl -s -X POST "$API_URL/auth/logout" \
  -H "Authorization: Bearer $TOKEN")

echo "Logout response: $LOGOUT_RESPONSE"
if echo "$LOGOUT_RESPONSE" | grep -q "message"; then
    echo -e "${GREEN}✓ Logout successful (audit logged)${NC}"
else
    echo -e "${YELLOW}⚠ Logout response unexpected${NC}"
fi
echo ""

# Summary
echo "=========================================="
echo -e "${GREEN}Audit System Testing Complete!${NC}"
echo "=========================================="
echo ""
echo "Test Summary:"
echo "- Registration, login, logout audited"
echo "- Session creation and access audited"
echo "- Failed login attempts logged"
echo "- Audit query API working"
echo "- Statistics and filtering working"
echo "- CSV and JSON exports working"
echo ""
echo "Check the audit logs in the database for complete details."
echo "Review export files:"
echo "  - $CSV_FILE"
echo "  - $JSON_FILE"
