# Query Refinement API

AI-powered query refinement API for scientific literature search. Built with FastAPI, SQLAlchemy, and PostgreSQL/SQLite.

## Features

- **User Authentication**: JWT-based authentication with registration and login
- **Query Sessions**: Create and manage multi-step query refinement sessions
- **Refinement Tracking**: Track refinement steps and follow-up interactions
- **Feedback Collection**: Collect user feedback on queries and results
- **RESTful API**: Clean, well-documented REST endpoints
- **OpenAPI Documentation**: Interactive API docs at `/docs`
- **Rate Limiting**: Built-in protection against API quota violations

## Quick Start

### Prerequisites

- Python 3.12+
- Poetry (dependency management)

### Installation

```bash
# Install dependencies
poetry install

# Set up environment variables
cp .env.example .env
# Edit .env with your configuration

# Run database migrations to create schema
poetry run alembic upgrade head

# Start the API server
poetry run uvicorn query_refinement_module.api.main:app --reload --host 0.0.0.0 --port 8000
```

### Access the API

- **API Root**: http://localhost:8000
- **Interactive Docs**: http://localhost:8000/docs
- **ReDoc**: http://localhost:8000/redoc
- **Health Check**: http://localhost:8000/health

## API Endpoints

### Authentication (`/api/auth`)

- `POST /api/auth/register` - Register a new user
- `POST /api/auth/login` - Login and get access token
- `GET /api/auth/me` - Get current user info (authenticated)

### Query Management (`/api/queries`)

- `POST /api/queries/sessions` - Create a new query session
- `GET /api/queries/sessions` - List user's sessions
- `GET /api/queries/sessions/{session_id}` - Get session details
- `POST /api/queries/sessions/{session_id}/end` - End a session
- `POST /api/queries/` - Create a new query
- `GET /api/queries/{query_id}` - Get query details
- `PUT /api/queries/{query_id}` - Update refined query
- `POST /api/queries/refinement-steps` - Create refinement step
- `GET /api/queries/{query_id}/refinement-steps` - List query refinement steps
- `POST /api/queries/followups` - Create follow-up entry
- `PUT /api/queries/followups/{followup_id}` - Update follow-up answer

### Query Refinement Workflow (`/api/refinement`)

**Core refinement endpoints that integrate the AI-powered refinement pipeline:**

- `GET /api/refinement/frameworks` - List available refinement frameworks
- `POST /api/refinement/start` - Start a new refinement workflow (initializes session, analyzes query)
- `POST /api/refinement/queries/{query_id}/answer` - Submit answer to refinement question
- `GET /api/refinement/queries/{query_id}/status` - Get current refinement status
- `POST /api/refinement/synthesize` - Synthesize final refined query from all answers

### Feedback (`/api/feedback`)

- `POST /api/feedback/` - Submit feedback
- `GET /api/feedback/my-feedback` - Get user's feedback
- `GET /api/feedback/query/{query_id}` - Get feedback for a query

## Example Usage

### 1. Register a User

```bash
curl -X POST "http://localhost:8000/api/auth/register" \
  -H "Content-Type: application/json" \
  -d '{
    "email": "user@example.com",
    "name": "Test User",
    "password": "secure_password123"
  }'
```

### 2. Login

```bash
curl -X POST "http://localhost:8000/api/auth/login" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "username=user@example.com&password=secure_password123"
```

Response:
```json
{
  "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "token_type": "bearer"
}
```

### 3. Create a Query Session (authenticated)

```bash
curl -X POST "http://localhost:8000/api/queries/sessions" \
  -H "Authorization: Bearer YOUR_ACCESS_TOKEN"
```

### 4. Submit a Query

```bash
curl -X POST "http://localhost:8000/api/queries/" \
  -H "Authorization: Bearer YOUR_ACCESS_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "session_id": 1,
    "original_query": "What are the effects of exercise on mental health?"
  }'
```

### 5. Submit Feedback

```bash
curl -X POST "http://localhost:8000/api/feedback/" \
  -H "Authorization: Bearer YOUR_ACCESS_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "query_id": 1,
    "rating": 5,
    "comments": "Very helpful refinement process!"
  }'
```

### 6. Complete Refinement Workflow

**Step 1: Get available frameworks**

```bash
curl -X GET "http://localhost:8000/api/refinement/frameworks" \
  -H "Authorization: Bearer YOUR_ACCESS_TOKEN"
```

**Step 2: Start refinement workflow**

```bash
curl -X POST "http://localhost:8000/api/refinement/start" \
  -H "Authorization: Bearer YOUR_ACCESS_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "original_query": "effects of aspirin on stroke prevention",
    "framework_name": "pico_template"
  }'
```

Response includes:
- `session_id`: Database session ID
- `query_id`: Query ID for tracking
- `summary`: Analysis of what needs refinement
- `next_prompt`: First question to answer

**Step 3: Submit answers to refinement questions**

```bash
curl -X POST "http://localhost:8000/api/refinement/queries/{query_id}/answer" \
  -H "Authorization: Bearer YOUR_ACCESS_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "answer": "Adults over 50 years old with high cardiovascular risk"
  }'
```

Repeat this step for each refinement question. The response will indicate if the aspect is complete or if follow-up questions are needed.

**Step 4: Check refinement status**

```bash
curl -X GET "http://localhost:8000/api/refinement/queries/{query_id}/status" \
  -H "Authorization: Bearer YOUR_ACCESS_TOKEN"
```

**Step 5: Synthesize refined query**

```bash
curl -X POST "http://localhost:8000/api/refinement/synthesize" \
  -H "Authorization: Bearer YOUR_ACCESS_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "query_id": 1
  }'
```

Returns the final refined query combining original query with all clarifications.

## Configuration

Key environment variables in `.env`:

```env
# Database
DATABASE_URL=sqlite:///query_refinement.db  # Or postgresql://user:pass@localhost/dbname

# Security
SECRET_KEY=your-secret-key-change-in-production
ACCESS_TOKEN_EXPIRE_MINUTES=30

# CORS (for frontend integration)
ALLOWED_ORIGINS=["http://localhost:3000"]

# LLM Configuration
REFINEMENT_FRAMEWORK_PATH=/path/to/framework.yaml
QUERY_REFINEMENT_LLM_MODEL=anthropic/claude-sonnet-4-20250514
QUERY_REFINEMENT_LLM_API_KEY=your-api-key
QUERY_REFINEMENT_LLM_TEMPERATURE=0.2
RATE_LIMIT_REQUESTS_PER_MINUTE=60
RATE_LIMIT_TOKENS_PER_MINUTE=90000
RATE_LIMIT_MAX_CONCURRENT_REQUESTS=10
```

### Rate Limiting Configuration

**Configure rate limits to prevent exceeding API quotas:**

- `RATE_LIMIT_REQUESTS_PER_MINUTE`: Maximum API calls per minute (default: 60)
- `RATE_LIMIT_TOKENS_PER_MINUTE`: Maximum tokens per minute (default: 90000)
- `RATE_LIMIT_MAX_CONCURRENT_REQUESTS`: Maximum concurrent API requests (default: 10)

The system automatically manages rate limits across all active sessions and includes retry logic with exponential backoff for failed requests.

## Development

### Run API Tests

**Automated (Recommended)**
```bash
cd tests/api && ./run_api_tests.sh
```
This script provides a clean test environment by:
- Stopping any running API servers
- Removing the test database for a fresh state
- Starting a new API server
- Running all 18 endpoint tests
- Leaving the server running for manual exploration

**Manual Testing**
```bash
# Start server (if not running)
poetry run uvicorn query_refinement_module.api.main:app --reload

# Run tests in another terminal
poetry run python tests/api/test_api_endpoints.py

# Stop server when done
cd tests/api && ./stop_api_server.sh
```

**Note:** For accurate test results, always start with a clean database. See `tests/README.md` for complete testing documentation.

### Run Unit Tests

```bash
poetry run pytest
```

### Database Migrations

The API uses Alembic for schema management. See [docs/database_migrations.md](docs/database_migrations.md) for complete guide.

```bash
# Apply migrations (required before first run)
poetry run alembic upgrade head

# Create a new migration after model changes
poetry run alembic revision --autogenerate -m "Description"

# Rollback one version
poetry run alembic downgrade -1

# Check current version
poetry run alembic current
```

### Code Quality

```bash
# Type checking
poetry run mypy query_refinement_module

# Linting
poetry run flake8 query_refinement_module
```

## Architecture

```
query_refinement_module/
├── api/
│   ├── main.py           # FastAPI app initialization
│   ├── config.py         # Application settings
│   ├── auth.py           # Authentication utilities
│   ├── schemas.py        # Pydantic request/response models
│   └── routes/
│       ├── auth.py       # Authentication endpoints
│       ├── queries.py    # Query refinement endpoints
│       └── feedback.py   # Feedback endpoints
├── db/
│   ├── database.py       # Database connection
│   ├── session.py        # Session management
│   ├── crud.py           # Database operations
│   └── models/           # SQLAlchemy models
└── core.py               # Core query refinement logic
```

## Production Deployment

### Using Docker

```dockerfile
FROM python:3.12-slim

WORKDIR /app
COPY . /app

RUN pip install poetry
RUN poetry install --no-dev

EXPOSE 8000
CMD ["poetry", "run", "uvicorn", "query_refinement_module.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

### Using Gunicorn + Uvicorn

```bash
poetry run gunicorn query_refinement_module.api.main:app \
  --workers 4 \
  --worker-class uvicorn.workers.UvicornWorker \
  --bind 0.0.0.0:8000
```

## Security Considerations

- Change `SECRET_KEY` in production
- Use HTTPS in production
- Configure proper CORS origins
- Use strong passwords (minimum 8 characters)
- Rotate JWT tokens regularly
- Use PostgreSQL for production (not SQLite)
- Enable rate limiting
- Implement API key management for external integrations

## License

MIT License - See LICENSE file for details
