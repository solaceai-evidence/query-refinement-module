# Query Refinement API

AI-powered query refinement API for scientific literature search. Built with FastAPI, SQLAlchemy, and PostgreSQL/SQLite.

## Features

- **User Authentication**: JWT-based authentication with registration and login
- **Query Sessions**: Create and manage multi-step query refinement sessions
- **Refinement Tracking**: Track refinement steps and follow-up interactions
- **Feedback Collection**: Collect user feedback on queries and results
- **RESTful API**: Clean, well-documented REST endpoints
- **OpenAPI Documentation**: Interactive API docs at `/docs`

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

# Initialize database
poetry run python test_db_setup.py

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
```

## Development

### Run Tests

```bash
poetry run pytest
```

### Database Migrations

```bash
# Create a new migration
poetry run alembic revision --autogenerate -m "Description"

# Apply migrations
poetry run alembic upgrade head

# Rollback
poetry run alembic downgrade -1
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
