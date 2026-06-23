# Query Refinement Module

A tool that helps turn a rough research idea into a clear, structured question. It guides users through a short series of clarifying questions based on a chosen framework, then produces a refined statement ready for literature search or systematic review.

---

## Using the web application

1. Log in at the application URL provided to you.
2. Select a refinement framework.
3. Enter your initial research question.
4. Answer the guided questions. Each comes with example answers you can click or type your own. You can skip, go back, or finish early at any time.
5. Review the clarified research statement and search query artifacts produced at the end.
6. Complete the feedback survey.

### Commands during the dialogue

| Command   | What it does                                |
| --------- | ------------------------------------------- |
| `/skip`   | Skip the current question                   |
| `/back`   | Return to the previous question             |
| `/done`   | Accept your current answer and move on      |
| `/status` | See how many questions remain               |
| `/submit` | Finish early and generate the refined query |
| `/help`   | List all commands                           |

---

## Running locally

### Prerequisites

- Python 3.12+
- Poetry
- Node.js 20+ (for the frontend)

### Backend

```bash
poetry install --with dev

# Copy the template for your LLM provider:
cp .env.anthropic-claude-sonnet-4-6 .env   # Anthropic Claude (recommended)
cp .env.openai-gpt-4o .env                  # OpenAI GPT-4o
cp .env.ollama-qwen2.5-72b .env             # Ollama — local models
cp .env.vllm .env                           # vLLM — self-hosted

# Set LLM_API_KEY in .env (cloud providers), then:
poetry run alembic upgrade head
poetry run uvicorn query_refinement_module.api.main:app --reload
```

Backend: http://localhost:8001 — API docs at `/docs`

### Frontend

```bash
cd frontend
npm install
npm run dev
```

Frontend: http://localhost:5173

---

## Production deployment

Docker is the recommended path.

```bash
# Copy the matching production template
cp .env.prod .env                    # Anthropic Claude Sonnet 4.6
cp .env.prod.openai-gpt-4o .env      # OpenAI GPT-4o
cp .env.prod.ollama-qwen2.5-72b .env # Ollama / Qwen 2.5 72B

# Set these required values in .env:
# SECRET_KEY, LLM_API_KEY, POSTGRES_USER, POSTGRES_PASSWORD, POSTGRES_DB, ALLOWED_ORIGINS

docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d
```

See [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md) for the full guide including SSL, backups, and migrations.

---

## CLI usage

```bash
# List available frameworks
poetry run query-refine --list-frameworks

# Start an interactive session
poetry run query-refine --framework pico_advanced
```

At the end of the session, the CLI offers to generate optional search expansion levels — broader retrieval variants for fallback when initial search yields insufficient results. The Level 0 query is always the exact clarified statement; broader levels are search-only and do not change the canonical refined question.

---

## User management

Registration is disabled by default. Create accounts with the provided scripts:

```bash
# Create a user (password auto-generated if omitted)
poetry run python scripts/create_user.py --username alice --email alice@example.com

# Create a superuser
poetry run python scripts/create_user.py --username admin --superuser

# Grant framework access to a user
poetry run python scripts/create_user.py --username alice --framework pico_advanced

# Promote an existing user to superuser
poetry run python scripts/make_superuser.py alice

# Bulk import from CSV
poetry run python scripts/import_credentials.py scripts/credentials.csv
```

Non-superuser accounts can only use frameworks they have been explicitly granted access to. This also applies to the `api_integration_service` account used for direct API access — it starts with no framework access and must be granted access explicitly.

---

## API integration

The API is available at `/api/v1/refinement/`. Key endpoints:

| Endpoint | Description |
|---|---|
| `POST /start` | Begin a refinement session |
| `POST /queries/{id}/answer` | Submit an answer |
| `POST /normalize` | Agent A — clarified query only |
| `POST /represent` | Agent B — semantic + keyword queries + concept graph |
| `POST /construct` | Agent C — keyword search constructions + filters |
| `POST /synthesize` | Run full A → B → C pipeline in one call |
| `POST /expand` | Agent D — optional search broadening levels |

See [docs/API.md](docs/API.md) for the full reference.

For server-to-server calls without a user login, set `INTEGRATION_API_KEY` in `.env` and send it as the `X-API-Key` header.

---

## Testing

```bash
poetry run pytest              # all tests
poetry run pytest tests/unit/  # unit tests only
poetry run pytest --cov=query_refinement_module  # with coverage
```

---

## Project structure

```
query_refinement_module/   Main Python package
  api/                     HTTP endpoints and middleware
  db/                      Database models and migrations
  schema/                  LLM prompt builders and response schemas
  providers/               LLM provider abstraction
  core.py                  Refinement session and synthesis logic

frontend/                  React web application
refinement_frameworks/     YAML framework definitions
scripts/                   User management utilities
tests/                     Automated tests
docs/                      Technical documentation
```

---

## Documentation

- [docs/API.md](docs/API.md) — Full API reference for external integrations
- [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md) — Production deployment, infrastructure, and backups
- [docs/FRAMEWORKS.md](docs/FRAMEWORKS.md) — How to define custom refinement frameworks
- [docs/OPERATIONS.md](docs/OPERATIONS.md) — Migrations, backups, and rollback procedures
- [docs/DATA_RECOVERY.md](docs/DATA_RECOVERY.md) — Database and cache recovery procedures

## License

See [LICENSE](LICENSE) file.
