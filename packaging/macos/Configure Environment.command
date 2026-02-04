#!/bin/bash
# Configuration helper for QueryRefine
# Creates .env file from sample.env if it doesn't exist

cd "$(dirname "$0")"

echo "======================================"
echo "QueryRefine Configuration"
echo "======================================"
echo ""

# Check if .env already exists
if [ -f .env ]; then
    echo "✓ .env file already exists"
    echo ""
    read -p "Do you want to reconfigure? (y/N): " reconfigure
    if [[ ! $reconfigure =~ ^[Yy]$ ]]; then
        echo "Configuration cancelled."
        read -p "Press Enter to exit..."
        exit 0
    fi
fi

# Copy sample.env to .env
if [ ! -f sample.env ]; then
    echo "ERROR: sample.env not found!"
    read -p "Press Enter to exit..."
    exit 1
fi

cp sample.env .env
echo "✓ Created .env from sample.env"
echo ""

# Prompt for API key
echo "Please enter your LLM API key:"
echo "(Get it from: https://console.anthropic.com/settings/keys)"
read -p "API Key: " api_key

if [ -z "$api_key" ]; then
    echo ""
    echo "WARNING: No API key provided."
    echo "You must edit .env manually before running the app."
else
    # Update .env with the API key
    if [[ "$OSTYPE" == "darwin"* ]]; then
        sed -i '' "s/QUERY_REFINEMENT_LLM_API_KEY=.*/QUERY_REFINEMENT_LLM_API_KEY=$api_key/" .env
    else
        sed -i "s/QUERY_REFINEMENT_LLM_API_KEY=.*/QUERY_REFINEMENT_LLM_API_KEY=$api_key/" .env
    fi
    echo "✓ API key configured"
fi

echo ""
echo "======================================"
echo "Configuration complete!"
echo "======================================"
echo ""
echo "Next steps:"
echo "1. Review .env file to customize settings"
echo "2. Run 'Run Query Refine.command' to start"
echo ""
read -p "Press Enter to exit..."
