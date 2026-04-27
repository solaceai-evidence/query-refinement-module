#!/bin/bash
# Start the Query Refinement API server using Poetry's virtual environment

echo "Starting Query Refinement API Server..."
echo ""

# Check if .env file exists
if [ ! -f ".env" ]; then
    echo "Warning: .env file not found"
    echo "   Pick the template that matches your LLM provider:"
    echo "     cp .env.anthropic-claude-sonnet-4-6 .env   # Anthropic Claude Sonnet 4.6 (cloud)"
    echo "     cp .env.ollama-llama3.3-70b .env          # Ollama — Llama 3.3 70B (local)"
    echo "     cp .env.vllm .env                         # vLLM (self-hosted GPU)"
    echo "   Then set QUERY_REFINEMENT_LLM_API_KEY (cloud) or verify API_BASE (local)"
    echo ""
    exit 1
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
PORT=${PORT:-8001}
echo "Starting server with Poetry on port $PORT..."
poetry run uvicorn query_refinement_module.api.main:app --host 0.0.0.0 --port "$PORT"

