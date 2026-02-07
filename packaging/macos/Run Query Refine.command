#!/bin/bash
# Launcher script for QueryRefine CLI
# Double-click this file to run the application

cd "$(dirname "$0")"

# Load environment variables
if [ -f .env ]; then
    export $(cat .env | grep -v '^#' | xargs)
fi

# Check if .env exists
if [ ! -f .env ]; then
    echo "ERROR: .env file not found!"
    echo "Please run 'Configure Environment.command' first"
    echo ""
    read -p "Press Enter to exit..."
    exit 1
fi

# Check if API key is set
if [ -z "$QUERY_REFINEMENT_LLM_API_KEY" ] || [ "$QUERY_REFINEMENT_LLM_API_KEY" = "your-api-key-here" ]; then
    echo "ERROR: API key not configured!"
    echo "Please run 'Configure Environment.command' first"
    echo ""
    read -p "Press Enter to exit..."
    exit 1
fi

# Set default framework if not specified
if [ -z "$REFINEMENT_FRAMEWORK_PATH" ]; then
    export REFINEMENT_FRAMEWORK_PATH="./frameworks.yaml"
fi

echo "======================================"
echo "Query Refinement Module - CLI"
echo "======================================"
echo ""
echo "Model: $QUERY_REFINEMENT_LLM_MODEL"
echo "Framework: $REFINEMENT_FRAMEWORK_PATH"
echo ""
echo "Usage:"
echo "  --framework FRAMEWORK_NAME    Use built-in framework (pico_advanced, mph_dissertation)"
echo "  --query \"YOUR QUERY\"          Start with an initial query"
echo "  --help                        Show all options"
echo ""
echo "Example:"
echo "  ./QueryRefine.app/Contents/MacOS/QueryRefine --framework pico_advanced --query \"diabetic treatments\""
echo ""
echo "======================================"
echo ""

# Run the application
if [ -d "./QueryRefine.app" ]; then
    exec ./QueryRefine.app/Contents/MacOS/QueryRefine "$@"
else
    echo "ERROR: QueryRefine.app not found in current directory"
    echo ""
    read -p "Press Enter to exit..."
    exit 1
fi
