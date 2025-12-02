#!/bin/bash
#
# Stop API test server
#

echo "🛑 Stopping API server..."
pkill -f "uvicorn query_refinement_module.api.main:app"

if [ $? -eq 0 ]; then
    echo "✅ Server stopped"
else
    echo "ℹ️  No running server found"
fi
