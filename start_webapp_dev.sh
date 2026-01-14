#!/bin/bash

# Query Refinement Web App - Development Startup Script
#This script starts Redis, the backend API, and the frontend dev server.

set -e # exit on error

echo "Starting Query Refinement Web App (Development Mode)"
echo ""

# Colors for output
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

# check if Redis is running
echo -e "${YELLOW}[1/6] Checking Redis service...${NC}"
if ! redis-cli ping > /dev/null 2>&1; then
    echo -e "${YELLOW}Warning: Redis is not running. Starting Redis via Docker compose...${NC}"
    docker-compose -f docker-compose.yml up -d redis
    echo -e "${GREEN}Redis started via Docker compose.${NC}"
    sleep 2
else
    echo -e "${GREEN}Redis is already running.${NC}"
fi

# Check if PostgreSQL is needed (optional, based on .env file)
if grep -q "DATABASE_URL=postgresql" .env 2>/dev/null; then
    echo -e "${YELLOW}[2/6] Checking PostgreSQL service...${NC}"
    if ! docker ps | grep -q query-refinement-db; then
        echo -e "${YELLOW}Warning: PostgreSQL is not running. Starting PostgreSQL via Docker compose...${NC}"
        docker-compose -f docker-compose.yml up -d postgres
        echo -e "${GREEN}PostgreSQL started via Docker compose.${NC}"
        sleep 3
    else
        echo -e "${GREEN}PostgreSQL is already running.${NC}"
    fi
else
    echo -e "${BLUE}[2/6] PostgreSQL not configured (using in-memory storage)${NC}"
fi

# Check if Poetry is installed
echo -e "${BLUE}[3/6] Checking Poetry installation...${NC}"
if ! command -v poetry &> /dev/null; then
    echo -e "${RED}Error: Poetry is not installed${NC}"
    echo ""
    echo "Install Poetry with:"
    echo "  ${GREEN}curl -sSL https://install.python-poetry.org | python3 -${NC}"
    echo ""
    echo "Or visit: https://python-poetry.org/docs/#installation"
    exit 1
fi
echo -e "${GREEN}Poetry found: $(poetry --version)${NC}"

# Check if backend dependencies are installed
echo -e "${BLUE}[4/6] Checking backend dependencies...${NC}"
if [ ! -d ".venv" ] && [ ! -f "poetry.lock" ]; then
    echo -e "${YELLOW}Installing backend dependencies...${NC}"
    poetry install
else
    echo -e "${GREEN}Backend dependencies already installed${NC}"
fi

# Check if frontend dependencies are installed
echo -e "${BLUE}[5/6] Checking frontend dependencies...${NC}"
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

# Check and clean up existing processes
echo -e "${BLUE}[6/6] Checking for existing processes...${NC}"
EXISTING_BACKEND=$(lsof -ti:8000 2>/dev/null || true)
EXISTING_FRONTEND=$(lsof -ti:5173 2>/dev/null || true)

if [ ! -z "$EXISTING_BACKEND" ]; then
    echo -e "${YELLOW}Found existing backend process on port 8000. Stopping...${NC}"
    kill -9 $EXISTING_BACKEND 2>/dev/null
    sleep 1
fi

if [ ! -z "$EXISTING_FRONTEND" ]; then
    echo -e "${YELLOW}Found existing frontend process on port 5173. Stopping...${NC}"
    kill -9 $EXISTING_FRONTEND 2>/dev/null
    sleep 1
fi


# Start backend in background with Poetry
echo -e "${BLUE}[7/7] Starting backend API...${NC}"
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
echo -e "${BLUE}[8/8] Starting frontend...${NC}"
cd frontend

# Verify Vite proxy configuration exists
if ! grep -q "'/api'" vite.config.js; then
    echo -e "${RED}⚠️  WARNING: Vite proxy configuration not found in vite.config.js!${NC}"
    echo -e "${YELLOW}API requests may fail. Proxy should forward /api to http://localhost:8000${NC}"
else
    echo -e "${GREEN}✓ Vite proxy configuration verified${NC}"
fi

# Clear Vite cache for clean start
if [ -d "node_modules/.vite" ]; then
    echo -e "${YELLOW}Clearing Vite cache...${NC}"
    rm -rf node_modules/.vite
fi

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
