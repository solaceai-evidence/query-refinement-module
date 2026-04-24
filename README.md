# Query Refinement Module

A web-based tool that guides users through a structured conversation to clarify and refine a research question. The tool asks targeted questions across the key dimensions of a chosen research framework (for example, PICO for medical research), then produces a refined, coherent research statement.

The tool is intended for:
- MPH students refining dissertation topics using the MPH Dissertation framework
- Systematic reviewers structuring evidence synthesis questions using the PICO framework
- Any researcher who needs to sharpen a research question before searching the literature

## Using the web application

1. Log in at the application URL provided to you.
2. Select a refinement framework.
3. Enter your initial research question or topic.
4. Answer the clarifying questions the tool asks. You can skip, go back, or finish early at any time.
5. Review the integrated research statement produced at the end.
6. Complete the feedback survey.

### Commands available during the dialogue

| Command   | What it does                                    |
| --------- | ----------------------------------------------- |
| `/skip`   | Skip the current question                       |
| `/back`   | Return to the previous question                 |
| `/done`   | Accept your current answer and move on          |
| `/status` | See how many questions remain                   |
| `/submit` | Finish early and generate the refined statement |
| `/help`   | List all commands                               |

## Running the application locally

### Prerequisites

- Python 3.12+
- Poetry
- Node.js 20+ (for the frontend)

### Backend

```bash
poetry install
cp .env.example .env
# Edit .env and set QUERY_REFINEMENT_LLM_API_KEY
poetry run alembic upgrade head
poetry run uvicorn query_refinement_module.api.main:app --reload
```

Backend available at: http://localhost:8001 (interactive API docs at /docs)

### Frontend

```bash
cd frontend
npm install
npm run dev
```

Frontend available at: http://localhost:5173

## Production deployment (Docker)

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d
```

See [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md) for the full deployment guide.

## CLI usage

```bash
# List available frameworks
poetry run query-refine --list-frameworks

# Start an interactive session
poetry run query-refine --framework pico_advanced
```

### Commands during a CLI session

| Command   | Purpose                          |
| --------- | -------------------------------- |
| `/back`   | Return to previous step          |
| `/skip`   | Skip current dimension           |
| `/done`   | Accept current value and move on |
| `/status` | Show progress summary            |
| `/submit` | Generate final refined query     |
| `/help`   | Show all commands                |

## Configuration

Key environment variables (copy `.env.example` to `.env` and fill in values):

| Variable                                    | Description                                                                                       |
| ------------------------------------------- | ------------------------------------------------------------------------------------------------- |
| `QUERY_REFINEMENT_LLM_API_KEY`              | API key for the LLM provider (use `EMPTY` for local vLLM)                                         |
| `QUERY_REFINEMENT_LLM_MODEL`                | Model identifier (default: `claude-sonnet-4-20250514`)                                            |
| `QUERY_REFINEMENT_LLM_API_BASE`             | Base URL for the LLM API; omit for Anthropic/OpenAI, set for vLLM/Ollama                          |
| `QUERY_REFINEMENT_LLM_CONSTRAINED_DECODING` | `true` to enable vLLM guided JSON decoding — **vLLM only**; leave `false` for all other providers |
| `SECRET_KEY`                                | Secret key for session tokens — change this in production                                         |
| `DATABASE_URL`                              | Database connection string (default: SQLite for local development)                                |
| `ALLOW_REGISTRATION`                        | Set to `false` to disable self-registration                                                       |
| `ENFORCE_WORKFLOW_LIMIT`                    | `true` = one workflow per user; `false` = unlimited                                               |
| `INTEGRATION_API_KEY`                       | Optional: for server-to-server API access without a user login                                    |

For external systems calling the API without a user login, also set:
- `INTEGRATION_API_KEY` — shared key sent via the `X-API-Key` header
- `INTEGRATION_SERVICE_USERNAME` — optional identity label (defaults to `api_integration_service`)

After changing these values, restart the API process or container.

### LLM provider backends

Three pre-filled environment templates are provided:

| File          | Provider                 | Constrained decoding |
| ------------- | ------------------------ | -------------------- |
| `.env.prod`   | Anthropic Claude (cloud) | off                  |
| `.env.ollama` | Ollama (local)           | off                  |
| `.env.vllm`   | vLLM (self-hosted)       | **on**               |

To switch to vLLM:

```bash
cp .env.vllm .env
# Edit QUERY_REFINEMENT_LLM_API_BASE to point at your vLLM server
# Edit QUERY_REFINEMENT_LLM_MODEL to match the model loaded on the server
```

When `QUERY_REFINEMENT_LLM_CONSTRAINED_DECODING=true` the provider sends
`guided_json` (the full Pydantic JSON Schema) in every structured LLM call,
enforcing schema-conformant output at the token level.  This option must only
be set when `QUERY_REFINEMENT_LLM_API_BASE` points at a vLLM server — it
will break structured output for Anthropic, OpenAI, and Ollama.

## User management

Registration is disabled by default. Create accounts using the provided scripts:

```bash
# Create a user (password auto-generated if omitted)
poetry run python scripts/create_user.py --username alice --email alice@example.com

# Create a superuser
poetry run python scripts/create_user.py --username admin --superuser

# Promote an existing user to superuser
poetry run python scripts/make_superuser.py alice

# Bulk import users from a credentials CSV
poetry run python scripts/import_credentials.py scripts/credentials.csv
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

## Project structure

```
query_refinement_module/   # Main Python package
  api/                     # HTTP endpoints and middleware
  db/                      # Database models and migrations
  providers/               # LLM provider abstraction
  core.py                  # Session management logic

frontend/                  # React web application
refinement_frameworks/     # YAML framework definitions
scripts/                   # User management and utility scripts
tests/                     # Automated tests
docs/                      # Technical documentation
```

## Documentation

- [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md) — Production deployment, infrastructure, and backups
- [docs/API.md](docs/API.md) — Full API reference for external integrations
- [docs/FRAMEWORKS.md](docs/FRAMEWORKS.md) — How to define custom refinement frameworks
- [docs/OPERATIONS.md](docs/OPERATIONS.md) — Migrations, backups, and rollback procedures

## License

See [LICENSE](LICENSE) file.
