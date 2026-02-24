#!/bin/bash
# Start the Query Refinement API server using Poetry's virtual environment

echo "Starting Query Refinement API Server..."
echo ""

# Check if .env file exists
if [ ! -f ".env" ]; then
    echo "Warning: .env file not found"
    echo "   Creating from .env.example..."
    cp .env.example .env
    echo "Please edit .env with your API keys and settings"
    echo ""
fi

# Check if REFINEMENT_FRAMEWORK_PATH is set in .env
if ! grep -q "^REFINEMENT_FRAMEWORK_PATH=" .env; then
    echo "Warning: REFINEMENT_FRAMEWORK_PATH not set in .env"
    echo "   Using default: refinement_frameworks/frameworks.yaml"
    echo ""
fi

echo "Checking Poetry dependencies..."
if [ ! -f "poetry.lock" ]; then
    echo "   Installing dependencies..."
    poetry install
fi
echo ""

# Start the server with Poetry
PORT=${PORT:-8000}
echo "Starting server with Poetry on port $PORT..."
poetry run uvicorn query_refinement_module.api.main:app --host 0.0.0.0 --port "$PORT"

