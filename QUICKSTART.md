# 🚀 Quick Start Guide - Query Refinement Web App

Get the web application running in under 5 minutes!

## Prerequisites

- Python 3.12+ 
- Poetry (install from https://python-poetry.org)
- Node.js 20+ and npm
- Redis (optional for development, required for production)

## Development Setup

### 1. Backend Setup

```bash
# Install dependencies
poetry install

# Create .env file (if not exists) -use available .env.example file-
cat > .env << 'EOF'
DATABASE_URL=sqlite:///query_refinement.db
SECRET_KEY=dev-secret-key
QUERY_REFINEMENT_LLM_API_KEY=your-api-key-here
ALLOWED_ORIGINS=http://localhost:5173
EOF

# Run database migrations
poetry run alembic upgrade head

# Start the backend
poetry run uvicorn query_refinement_module.api.main:app --reload
```

Backend will be available at:
- **API**: http://localhost:8000
- **Docs**: http://localhost:8000/docs

### 2. Frontend Setup

```bash
# Navigate to frontend directory
cd frontend

# Install dependencies
npm install

# Start development server
npm run dev
```

Frontend will be available at:
- **App**: http://localhost:5173

### 3. Access the Application

1. Open http://localhost:5173 in your browser
2. Click **Register** to create an account
3. Login with your credentials
4. Select a refinement framework
5. Enter your initial query
6. Answer the questions to refine your query
7. View and export your refined query!

## One-Command Start (Development)

```bash
./start_webapp_dev.sh
```

This script will:
- Check dependencies
- Start Redis service on port 6379
- Start PostgreSQL if set in .env file
- Start backend on port 8000
- Start frontend on port 5173
- Show logs in backend.log and frontend.log

Stop with `Ctrl+C`

## Production Deployment

### Docker Compose (Recommended)

```bash
# 1. Create production config
cp .env.production.template .env.production
# Edit .env.production with your values

# 2. Start all services
docker-compose -f docker-compose.fullstack.yml up -d

# 3. Run migrations
docker-compose exec backend alembic upgrade head

# 4. Check health
curl http://localhost/health
```

Access at: http://localhost (or your domain)

### Manual Production Setup

See [WEBAPP_README.md](WEBAPP_README.md) for detailed instructions.

## Testing the Application

### 1. Register a User

```bash
curl -X POST http://localhost:8000/api/auth/register \
  -H "Content-Type: application/json" \
  -d '{
    "username": "testuser",
    "email": "test@example.com",
    "password": "Password123!"
  }'
```

### 2. Login

```bash
curl -X POST http://localhost:8000/api/auth/token \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "username=testuser&password=Password123!&grant_type=password"
```

### 3. Test Refinement (with token)

```bash
TOKEN="your-access-token-here"

# Get frameworks
curl http://localhost:8000/api/refinement/frameworks \
  -H "Authorization: Bearer $TOKEN"

# Start refinement
curl -X POST http://localhost:8000/api/refinement/start \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "framework_name": "pico_framework",
    "initial_query": "diabetes treatment"
  }'
```

## Troubleshooting

### Backend won't start
- Check Python environment is activated
- Verify .env file exists with correct values
- Run `alembic upgrade head` for database setup

### Frontend won't connect
- Ensure backend is running on port 8000
- Check CORS settings in backend .env
- Verify frontend .env has `VITE_API_BASE_URL=http://localhost:8000`

### Redis connection errors
- For development: Comment out Redis URL in .env (will use memory storage)
- For production: Start Redis with `brew services start redis` (macOS)

### Authentication errors
- Clear browser localStorage and try again
- Check SECRET_KEY in backend .env
- Verify token hasn't expired (30 minutes default)

## What's Next?

- **Customize Frameworks**: Add your own YAML frameworks to `/examples`
- **Load Testing**: See [docs/load_testing_guide.md](docs/load_testing_guide.md)
- **API Integration**: See [API_README.md](API_README.md)
- **Production Scaling**: See [WEBAPP_README.md](WEBAPP_README.md#performance--scaling)

## Architecture Overview

```
┌─────────────────┐
│   React App     │  Frontend (port 5173/80)
│   (Vite)        │  - Auth UI
│                 │  - Framework Selection
│                 │  - Conversation Interface
└────────┬────────┘
         │ HTTP/REST
         ↓
┌─────────────────┐
│   FastAPI       │  Backend (port 8000)
│   + SQLAlchemy  │  - JWT Auth
│   + Redis       │  - Session Management
│                 │  - Rate Limiting
└────────┬────────┘
         │
         ↓
┌─────────────────┐
│  LLM Provider   │  (Anthropic/OpenAI/etc)
│  (via LiteLLM)  │  - Query Refinement
└─────────────────┘
```

## Support

- **Full Documentation**: [WEBAPP_README.md](WEBAPP_README.md)
- **API Reference**: [API_README.md](API_README.md)
- **Main README**: [README.md](README.md)

Happy refining! 🎯
