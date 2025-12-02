#!/bin/bash
#
# Clean test runner for API endpoints
# This script ensures a clean database state before running tests
#
# Usage: Run from project root or tests/api directory
#   ./tests/api/run_api_tests.sh
#   OR cd tests/api && ./run_api_tests.sh

set -e

# Change to project root if we're in tests/api
if [[ $(basename "$PWD") == "api" ]]; then
    cd ../..
fi

echo "🧹 Cleaning up previous test run..."

# Kill any running API servers
pkill -f "uvicorn query_refinement_module.api.main:app" 2>/dev/null || true

# Remove old database
rm -f query_refinement.db

echo "✅ Cleaned up"
echo ""
echo "📊 Running database migrations..."

# Run Alembic migrations to create schema
poetry run alembic upgrade head > /dev/null 2>&1

if [ $? -eq 0 ]; then
    echo "✅ Database schema created"
else
    echo "❌ Migration failed"
    exit 1
fi

echo ""
echo "🚀 Starting API server..."

# Start API server in background
nohup poetry run uvicorn query_refinement_module.api.main:app \
    --host 0.0.0.0 \
    --port 8000 \
    > /tmp/api_server.log 2>&1 &

SERVER_PID=$!
echo "   Server PID: $SERVER_PID"
echo "   Log: /tmp/api_server.log"

# Wait for server to be ready
echo ""
echo "⏳ Waiting for server to initialize..."
sleep 3

# Check if server is healthy
if curl -s http://localhost:8000/health > /dev/null 2>&1; then
    echo "✅ Server is healthy"
else
    echo "❌ Server failed to start. Check logs:"
    echo "   tail /tmp/api_server.log"
    exit 1
fi

echo ""
echo "🧪 Running API tests..."
echo "========================================"

# Run tests
poetry run python tests/api/test_api_endpoints.py

TEST_EXIT=$?

echo ""
echo "========================================"
if [ $TEST_EXIT -eq 0 ]; then
    echo "✅ All tests passed!"
else
    echo "❌ Some tests failed (exit code: $TEST_EXIT)"
fi

echo ""
echo "💡 Server is still running (PID: $SERVER_PID)"
echo "   To stop: pkill -f uvicorn"
echo "   To view logs: tail -f /tmp/api_server.log"

exit $TEST_EXIT
