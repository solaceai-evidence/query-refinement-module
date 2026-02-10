#!/bin/bash
# Test script for session abandonment / Start Over functionality
# Usage: ./test_abandon.sh

set -e

echo "================================================"
echo "  Session Abandonment Test"
echo "================================================"
echo ""

# Check if API server is running
if ! curl -s http://localhost:8000/health > /dev/null 2>&1; then
    echo "❌ API server is not running"
    echo ""
    echo "Start the server in another terminal with:"
    echo "  poetry run uvicorn query_refinement_module.api.main:app --reload"
    echo ""
    exit 1
fi

echo "✓ API server is running"
echo ""

# Run the test
echo "Running session abandonment test..."
echo ""

poetry run python tests/api/test_abandon_session.py

echo ""
echo "================================================"
echo "  Test complete!"
echo "================================================"
