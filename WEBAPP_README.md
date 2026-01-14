# Query Refinement Web Application

A full-stack web application for AI-powered query refinement with dynamic framework support, authentication, and scalable infrastructure.

## Architecture

### Frontend (React + Vite)
- **Framework**: React 18 with Vite build tool
- **Routing**: React Router v6 for SPA navigation
- **State Management**: React Context for auth state
- **API Client**: Axios with interceptors for auth and error handling
- **Styling**: Pure CSS with modular component styles

### Backend (FastAPI)
- **API Framework**: FastAPI with async/await support
- **Database**: SQLite (dev) / PostgreSQL (production)
- **Session Management**: Redis-backed sessions
- **Rate Limiting**: Distributed rate limiting via Redis
- **Authentication**: JWT-based auth with bcrypt password hashing

### Infrastructure
- **Reverse Proxy**: Nginx for load balancing and SSL termination
- **Containerization**: Docker with multi-stage builds
- **Orchestration**: Docker Compose for full stack deployment
- **Caching**: Redis for sessions and rate limit state

## Features

### Authentication
- User registration and login
- JWT token-based authentication
- Automatic token refresh handling
- Protected routes with React Router

### Dynamic Framework Support
- Automatic framework discovery from backend
- Framework selection interface
- Multi-turn conversational refinement
- Real-time aspect status tracking

### User Experience
- Session persistence (survives browser refresh)
- Conversation history display
- Progress tracking with visual indicators
- Final synthesis with export options (clipboard, JSON)
- Feedback submission system

### Production Ready
- Supports 100+ concurrent users
- Distributed rate limiting
- Connection pooling (PostgreSQL)
- Health check endpoints
- Structured logging
- CORS configuration

## Quick Start

### Development

1. **Start the backend**:
   ```bash
   cd /Users/w1214757/Dev/query-refinement-module
   python -m uvicorn query_refinement_module.api.main:app --reload
   ```

2. **Start the frontend**:
   ```bash
   cd frontend
   npm install
   npm run dev
   ```

3. **Access the application**:
   - Frontend: http://localhost:5173
   - Backend API: http://localhost:8000
   - API Docs: http://localhost:8000/docs

### Production Deployment

1. **Configure environment**:
   ```bash
   cp .env.production .env
   # Edit .env with your production values:
   # - DATABASE_URL (PostgreSQL)
   # - REDIS_URL
   # - SECRET_KEY
   # - QUERY_REFINEMENT_LLM_API_KEY
   # - ALLOWED_ORIGINS (your frontend domain)
   ```

2. **Start with Docker Compose**:
   ```bash
   docker-compose -f docker-compose.fullstack.yml up -d
   ```

3. **Run database migrations**:
   ```bash
   docker-compose exec backend alembic upgrade head
   ```

4. **Access the application**:
   - Frontend: http://localhost (or your domain)
   - Health Check: http://localhost/health

## Project Structure

```
query-refinement-module/
├── frontend/                      # React frontend application
│   ├── src/
│   │   ├── components/           # React components
│   │   │   ├── AspectStatusPanel.jsx
│   │   │   ├── FrameworkSelector.jsx
│   │   │   ├── QuestionRenderer.jsx
│   │   │   ├── SynthesisResult.jsx
│   │   │   └── ProtectedRoute.jsx
│   │   ├── context/              # React context providers
│   │   │   └── AuthContext.jsx
│   │   ├── pages/                # Page components
│   │   │   ├── Login.jsx
│   │   │   ├── Register.jsx
│   │   │   └── Refinement.jsx
│   │   ├── services/             # API services
│   │   │   ├── api.js            # Axios client with interceptors
│   │   │   └── refinement.js     # Refinement API calls
│   │   ├── utils/                # Utility functions
│   │   │   └── auth.js           # JWT token management
│   │   ├── App.jsx               # Main app component
│   │   └── main.jsx              # Entry point
│   ├── .env                      # Environment variables
│   ├── Dockerfile.production     # Production Docker build
│   ├── nginx.conf                # Nginx config for frontend
│   └── package.json
├── query_refinement_module/      # Python backend
│   ├── api/
│   │   ├── routes/               # API route handlers
│   │   │   ├── auth.py           # Authentication endpoints
│   │   │   ├── queries.py        # Query management
│   │   │   ├── refinement.py     # Refinement workflow
│   │   │   └── feedback.py       # User feedback
│   │   ├── config.py             # Application settings
│   │   ├── main.py               # FastAPI app initialization
│   │   ├── rate_limit.py         # Rate limiting middleware
│   │   └── session_manager.py    # Session management
│   └── ...
├── nginx/                         # Nginx reverse proxy config
│   └── nginx.conf
├── docker-compose.fullstack.yml   # Full stack orchestration
├── .env.production                # Production environment template
└── WEBAPP_README.md               # This file
```

## Configuration

### Frontend Environment Variables

Create `frontend/.env`:

```bash
VITE_API_BASE_URL=http://localhost:8000
VITE_API_TIMEOUT=30000
```

For production, update to your actual API URL.

### Backend Environment Variables

Key production settings in `.env.production`:

```bash
# Database (PostgreSQL with connection pooling)
DATABASE_URL=postgresql://user:pass@postgres:5432/db
DB_POOL_SIZE=20
DB_MAX_OVERFLOW=40

# Redis
REDIS_URL=redis://redis:6379/0
SESSION_STORAGE_BACKEND=redis
RATE_LIMITER_BACKEND=redis

# Rate Limiting (for 100 concurrent users)
LLM_RATE_LIMIT_RPM=1000
LLM_MAX_CONCURRENT=50
LLM_RATE_LIMIT_PER_USER_RPM=20
LLM_MAX_CONCURRENT_PER_USER=5

# CORS (update with your domain)
ALLOWED_ORIGINS=http://localhost:5173,https://yourdomain.com

# Security
SECRET_KEY=change-this-to-a-secure-random-key
```

## API Integration

### Authentication Flow

1. **Register**: `POST /api/auth/register`
   ```json
   {
     "username": "user",
     "email": "user@example.com",
     "password": "password"
   }
   ```

2. **Login**: `POST /api/auth/token`
   ```
   Form data:
   - username: user
   - password: password
   - grant_type: password
   ```

3. **Use token**: Add to requests:
   ```
   Authorization: Bearer <access_token>
   ```

### Refinement Workflow

1. **Get frameworks**: `GET /api/refinement/frameworks`
2. **Start refinement**: `POST /api/refinement/start`
3. **Answer questions**: `POST /api/refinement/continue` (multi-turn)
4. **Get synthesis**: `POST /api/refinement/synthesize`

See [API_README.md](../API_README.md) for complete API documentation.

## Performance & Scaling

### Current Capacity
- **Concurrent Users**: 100+
- **Requests/Minute**: 1000 (global), 20 (per-user)
- **Response Time**: <2s average, <5s 95th percentile

### Scaling Strategies

1. **Horizontal Scaling**:
   - Add more backend worker containers
   - Use load balancer (nginx/HAProxy)
   - Share Redis instance across workers

2. **Database Optimization**:
   - Connection pooling (configured)
   - Read replicas for query-heavy loads
   - Indexes on frequently queried fields

3. **Caching**:
   - Redis caching for framework definitions
   - CDN for static frontend assets
   - Browser caching for immutable assets

4. **Rate Limiting**:
   - Distributed via Redis (configured)
   - Adaptive rate limiting (configured)
   - Per-user fairness limits (configured)

## Monitoring

### Health Checks

- **Backend**: `GET /health` - Basic health
- **Backend**: `GET /ready` - Readiness check (DB + Redis)
- **Frontend**: Nginx status via monitoring

### Logging

- **Format**: JSON (production) or text (development)
- **Level**: INFO (production) or DEBUG (development)
- **Location**: `/app/logs` (containerized) or stdout

### Metrics to Monitor

- Request latency (p50, p95, p99)
- Error rates (4xx, 5xx)
- Active sessions
- Database connection pool utilization
- Redis memory usage
- LLM API rate limit headroom

## Load Testing

See [docs/load_testing_guide.md](../docs/load_testing_guide.md) for comprehensive load testing instructions.

Quick test with Locust:

```bash
cd tests/load
locust -f test_refinement_workflow.py --host http://localhost:8000
```

Access Locust UI at http://localhost:8089 and configure:
- Number of users: 100
- Spawn rate: 10/s

## Security

### Current Implementation
- ✅ JWT authentication
- ✅ Password hashing (bcrypt)
- ✅ CORS configuration
- ✅ Rate limiting
- ✅ SQL injection protection (SQLAlchemy ORM)
- ✅ XSS protection (React auto-escaping)

### Production Recommendations
- [ ] Enable HTTPS (update nginx config)
- [ ] Add SSL certificates (Let's Encrypt)
- [ ] Implement refresh tokens
- [ ] Add CSRF protection
- [ ] Set up WAF (Web Application Firewall)
- [ ] Enable audit logging
- [ ] Implement IP whitelisting if needed

## Troubleshooting

### Frontend won't connect to API
- Check CORS settings in backend `.env`
- Verify `VITE_API_BASE_URL` in frontend `.env`
- Check browser console for CORS errors

### Authentication fails
- Verify `SECRET_KEY` matches between requests
- Check token expiration time
- Clear localStorage and re-login

### Rate limit errors
- Check Redis connection
- Verify `RATE_LIMITER_BACKEND=redis` in `.env`
- Adjust rate limits in `.env`

### Session not persisting
- Check Redis connection
- Verify `SESSION_STORAGE_BACKEND=redis`
- Check browser localStorage for session data

## Development

### Frontend Development

```bash
cd frontend
npm run dev        # Start dev server
npm run build      # Build for production
npm run preview    # Preview production build
npm run lint       # Run ESLint
```

### Backend Development

```bash
# Run tests
pytest

# Run with auto-reload
uvicorn query_refinement_module.api.main:app --reload

# Format code
black query_refinement_module/
isort query_refinement_module/
```

## License

[MIT License](../LICENSE)

## Support

For issues and questions:
- Backend API: See [API_README.md](../API_README.md)
- General: See [README.md](../README.md)
- Load Testing: See [docs/load_testing_guide.md](../docs/load_testing_guide.md)
