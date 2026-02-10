#!/bin/bash
# Quick test script for synthesis flow
# Usage: ./test_synthesis.sh

set -e

echo "================================================"
echo "  Synthesis Flow Test"
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
echo "Running synthesis flow test..."
echo ""

poetry run python tests/api/test_synthesis_flow.py

echo ""
echo "================================================"
echo "  Test complete!"
echo "================================================"
