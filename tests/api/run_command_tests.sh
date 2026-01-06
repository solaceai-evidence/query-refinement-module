#!/bin/bash
# Test runner for API command features
# 
# This script starts the API server, runs comprehensive command tests,
# and provides detailed output.

set -e  # Exit on error

echo "=================================="
echo "API Command Features Test Runner"
echo "=================================="
echo ""

# Check if poetry is available
if ! command -v poetry &> /dev/null; then
    echo "❌ Poetry not found. Please install poetry first:"
    echo "   curl -sSL https://install.python-poetry.org | python3 -"
    exit 1
fi

# Check if Redis is running
if ! command -v redis-cli &> /dev/null; then
    echo "⚠️  Redis CLI not found. Tests may fail if Redis is not running."
else
    if ! redis-cli ping &> /dev/null; then
        echo "⚠️  Redis is not responding. Starting Redis..."
        if command -v redis-server &> /dev/null; then
            redis-server --daemonize yes
            sleep 2
        else
            echo "❌ Redis server not found. Please install and start Redis."
            exit 1
        fi
    else
        echo "✓ Redis is running"
    fi
fi

# Check environment variables
if [ -z "$REFINEMENT_FRAMEWORK_PATH" ]; then
    echo "⚠️  REFINEMENT_FRAMEWORK_PATH not set. Using default from .env"
else
    echo "✓ Framework path: $REFINEMENT_FRAMEWORK_PATH"
fi

# Start API server in background
echo ""
echo "Starting API server..."
poetry run uvicorn query_refinement_module.api.main:app \
    --host 127.0.0.1 \
    --port 8000 \
    --log-level warning &

API_PID=$!
echo "✓ API server started (PID: $API_PID)"

# Wait for server to be ready
echo "Waiting for API server to be ready..."
MAX_WAIT=30
WAITED=0
while ! curl -s http://localhost:8000/health > /dev/null; do
    sleep 1
    WAITED=$((WAITED + 1))
    if [ $WAITED -ge $MAX_WAIT ]; then
        echo "❌ API server failed to start within ${MAX_WAIT}s"
        kill $API_PID 2>/dev/null || true
        exit 1
    fi
done
echo "✓ API server is ready"

# Function to cleanup on exit
cleanup() {
    echo ""
    echo "Shutting down API server..."
    kill $API_PID 2>/dev/null || true
    wait $API_PID 2>/dev/null || true
    echo "✓ Cleanup complete"
}
trap cleanup EXIT

# Run the tests
echo ""
echo "=================================="
echo "Running Tests"
echo "=================================="
echo ""

# Run basic integration tests first
echo "Running basic integration tests..."
poetry run python tests/api/test_refinement_endpoints.py
BASIC_RESULT=$?

echo ""
echo "=================================="
echo "Running comprehensive command tests..."
poetry run python tests/api/test_command_features_comprehensive.py
COMPREHENSIVE_RESULT=$?

# Summary
echo ""
echo "=================================="
echo "TEST EXECUTION SUMMARY"
echo "=================================="
if [ $BASIC_RESULT -eq 0 ]; then
    echo "✓ Basic integration tests: PASSED"
else
    echo "❌ Basic integration tests: FAILED"
fi

if [ $COMPREHENSIVE_RESULT -eq 0 ]; then
    echo "✓ Comprehensive command tests: PASSED"
else
    echo "❌ Comprehensive command tests: FAILED"
fi
echo "=================================="

# Exit with combined result
if [ $BASIC_RESULT -eq 0 ] && [ $COMPREHENSIVE_RESULT -eq 0 ]; then
    echo ""
    echo "🎉 All tests passed!"
    exit 0
else
    echo ""
    echo "❌ Some tests failed. See output above for details."
    exit 1
fi
