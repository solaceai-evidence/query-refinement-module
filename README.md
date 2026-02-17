# Query Refinement Module

A conversational query refinement engine that guides users through structured clarification dialogues. Uses LLM-powered analysis to refine research queries across configurable dimensions (e.g., PICO framework for medical research).

## Features

- **Framework-driven refinement**: YAML-defined dimensions with dependencies
- **Conversational flow**: Multi-turn Q&A with follow-up questions
- **User commands**: `/skip`, `/done`, `/back`, `/status` for navigation
- **Structured outputs**: LLM responses validated via Pydantic models
- **Search optimization**: Generates semantic, keyword, and grey literature variants
- **Session persistence**: SQLite/PostgreSQL with Redis caching

## Quick Start

### Prerequisites

- Python 3.12+
- Poetry
- Node.js 20+ (for frontend)

### 1. Backend Setup

```bash
# Install dependencies
poetry install

# Create .env from example
cp .env.example .env
# Edit .env with your API key:
#   QUERY_REFINEMENT_LLM_API_KEY=your-key-here

# Run database migrations
poetry run alembic upgrade head

# Start backend
poetry run uvicorn query_refinement_module.api.main:app --reload
```

Backend available at: http://localhost:8000 (API docs at /docs)  
**API Endpoints:** All endpoints use `/api/v1/` prefix (e.g., `/api/v1/refinement/start`)

### 2. Frontend Setup

```bash
cd frontend
npm install
npm run dev
```

Frontend available at: http://localhost:5173

### 3. Use the Application

1. Login at http://localhost:5173 with provided credentials
2. Select a refinement framework
3. Enter your research query
4. Answer clarifying questions
5. Export refined query

## CLI Usage

```bash
# List available frameworks
poetry run query-refine --list-frameworks

# Start interactive session
poetry run query-refine --framework pico_advanced
```

### Commands During Session

| Command   | Purpose                        |
| --------- | ------------------------------ |
| `/back`   | Return to previous step        |
| `/skip`   | Skip current dimension         |
| `/done`   | Accept current answer, move on |
| `/status` | Show progress summary          |
| `/submit` | Generate final refined query   |
| `/help`   | Show all commands              |

## Configuration

Key environment variables (see `.env.example`):

```bash
# LLM Settings
QUERY_REFINEMENT_LLM_MODEL=anthropic/claude-sonnet-4-20250514
QUERY_REFINEMENT_LLM_API_KEY=your-api-key

# Database
DATABASE_URL=sqlite:///query_refinement.db

# Session Security
SECRET_KEY=change-this-in-production
ALLOW_REGISTRATION=false
ENFORCE_WORKFLOW_LIMIT=true
```

Workflow mode:

- `ENFORCE_WORKFLOW_LIMIT=true`: non-superusers are limited to one completed workflow
- `ENFORCE_WORKFLOW_LIMIT=false`: non-superusers can run unlimited workflows

## User Management (No Self-Registration)

Create users and superusers programmatically:

```bash
# Create a user (password auto-generated if omitted)
poetry run python scripts/create_user.py --username alice --email alice@example.com

# Create a superuser
poetry run python scripts/create_user.py --username admin --superuser

# Promote an existing user to superuser
poetry run python scripts/make_superuser.py alice

# Bulk import users from generated credentials
poetry run python scripts/import_credentials.py scripts/credentials.csv
```
## Custom Frameworks

Define frameworks in YAML:

```yaml
my_framework:
  - id: population
    aspect_name: Population
    aspect_description: Who is being studied
    refinement_instructions: |
      Analyze the research input: {input}
      Identify the target population.
    allow_follow_up: true
    max_follow_ups: 2
```

Set path: `export REFINEMENT_FRAMEWORK_PATH=/path/to/frameworks.yaml`

## Docker Deployment

```bash
# Production deployment
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d

# Run migrations
docker compose -f docker-compose.yml -f docker-compose.prod.yml exec api alembic upgrade head
```

## Testing

```bash
# All tests
poetry run pytest

# Unit tests only
poetry run pytest tests/unit/

# With coverage
poetry run pytest --cov=query_refinement_module
```

## Project Structure

```
query_refinement_module/   # Main package
├── api/                   # FastAPI routes and middleware
├── db/                    # SQLAlchemy models and migrations
├── schema/                # Pydantic models and framework loading
├── providers/             # LLM provider abstraction
└── core.py                # Session management logic

frontend/                  # React web application
refinement_frameworks/     # YAML framework definitions
tests/                     # Unit, integration, and API tests
docs/                      # Additional documentation
```

## Documentation

- [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md) - Deployment and environment setup
- [docs/API.md](docs/API.md) - API endpoints and commands
- [docs/FRAMEWORKS.md](docs/FRAMEWORKS.md) - Framework authoring
- [docs/OPERATIONS.md](docs/OPERATIONS.md) - Migrations, backups, and checks

## License

See [LICENSE](LICENSE) file.
