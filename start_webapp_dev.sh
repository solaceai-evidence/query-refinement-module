#!/bin/bash

# Query Refinement Web App - Development Startup Script

set -e

echo "🚀 Starting Query Refinement Web App (Development Mode)"
echo ""

# Colors for output
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

# Check if conda environment is active
echo -e "${BLUE}Checking conda environment...${NC}"
if [[ "$CONDA_DEFAULT_ENV" != "query-refinement" ]]; then
    echo -e "${RED}Error: query-refinement conda environment is not active${NC}"
    echo ""
    echo "Please activate the environment first:"
    echo "  ${GREEN}conda activate query-refinement${NC}"
    echo ""
    echo "If the environment doesn't exist, create it:"
    echo "  ${GREEN}conda env create -f environment.yml${NC}"
    echo "  ${GREEN}conda activate query-refinement${NC}"
    echo "  ${GREEN}poetry install${NC}"
    exit 1
fi

# Check if poetry dependencies are installed
echo -e "${BLUE}Checking poetry dependencies...${NC}"
if ! poetry check --quiet 2>/dev/null; then
    echo -e "${YELLOW}Installing Python dependencies with poetry...${NC}"
    poetry install
fi

# Check if frontend dependencies are installed
echo -e "${BLUE}Checking frontend dependencies...${NC}"
if [ ! -d "frontend/node_modules" ]; then
    echo -e "${YELLOW}Installing frontend dependencies...${NC}"
    cd frontend
    npm install
    cd ..
fi

# Check if .env exists
if [ ! -f ".env" ]; then
    echo -e "${YELLOW}No .env file found. Creating from template...${NC}"
    cat > .env << 'EOF'
# Development Environment Configuration
DATABASE_URL=sqlite:///query_refinement.db
REDIS_URL=redis://localhost:6379/0
SECRET_KEY=dev-secret-key-change-in-production
QUERY_REFINEMENT_LLM_API_KEY=your-api-key-here
ALLOWED_ORIGINS=http://localhost:5173,http://localhost:8000
EOF
    echo -e "${GREEN}Created .env file. Please update QUERY_REFINEMENT_LLM_API_KEY${NC}"
fi

# Start Redis if not running
echo -e "${BLUE}Checking Redis...${NC}"
if ! redis-cli ping &>/dev/null; then
    echo -e "${YELLOW}Redis not running. Please start Redis:${NC}"
    echo "  brew services start redis  # macOS"
    echo "  sudo systemctl start redis # Linux"
    echo ""
    echo -e "${YELLOW}Or run without Redis (memory-based session storage)${NC}"
fi

# Start backend in background
echo -e "${BLUE}Starting backend API...${NC}"
poetry run uvicorn query_refinement_module.api.main:app --reload --host 0.0.0.0 --port 8000 > backend.log 2>&1 &
BACKEND_PID=$!
echo -e "${GREEN}Backend started (PID: $BACKEND_PID)${NC}"
echo "  API: http://localhost:8000"
echo "  Docs: http://localhost:8000/docs"
echo "  Logs: backend.log"

# Wait for backend to be ready
echo -e "${BLUE}Waiting for backend to be ready...${NC}"
for i in {1..30}; do
    if curl -s http://localhost:8000/health > /dev/null 2>&1; then
        echo -e "${GREEN}Backend is ready!${NC}"
        break
    fi
    if [ $i -eq 30 ]; then
        echo -e "${YELLOW}Backend took too long to start. Check backend.log${NC}"
    fi
    sleep 1
done

# Start frontend
echo -e "${BLUE}Starting frontend...${NC}"
cd frontend
npm run dev > ../frontend.log 2>&1 &
FRONTEND_PID=$!
cd ..
echo -e "${GREEN}Frontend started (PID: $FRONTEND_PID)${NC}"
echo "  App: http://localhost:5173"
echo "  Logs: frontend.log"

echo ""
echo -e "${GREEN}✅ All services started!${NC}"
echo ""
echo "Access the application at: ${BLUE}http://localhost:5173${NC}"
echo ""
echo "To stop all services, run:"
echo "  kill $BACKEND_PID $FRONTEND_PID"
echo ""
echo "Or save these PIDs:"
echo "export BACKEND_PID=$BACKEND_PID"
echo "export FRONTEND_PID=$FRONTEND_PID"
echo ""

# Keep script running and handle Ctrl+C
trap 'echo ""; echo "Stopping services..."; kill $BACKEND_PID $FRONTEND_PID 2>/dev/null; exit 0' INT

echo "Press Ctrl+C to stop all services"
wait
