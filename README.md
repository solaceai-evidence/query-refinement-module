# Query Refinement Module

A multi-agent LLM pipeline that turns a rough research idea into a structured, search-ready question. Users go through a short guided dialogue based on a configurable framework (e.g. PICO, COCOPOP); the system then runs a four-agent synthesis pipeline that produces:

- A **clarified query** — the canonical refined statement in the user's own language
- A **semantic statement** — optimised for dense vector / embedding search
- A **keyword statement** — optimised for BM25 and keyword-based retrieval
- A **Boolean search construction** — AND/OR blocks with controlled vocabulary hints for databases such as PubMed or Embase
- A **concept graph** — structured synonyms, abbreviations, and domain terms per concept
- Optional **search expansion levels** — progressively broader retrieval variants for fallback recall

The system is framework-agnostic and domain-agnostic. It exposes a REST API for integration into external search and systematic review platforms, a Chainlit chat UI for guided refinement, and a CLI for developer workflows.

---

## Using the web application

1. Log in at the application URL with the account you were given.
2. Pick a refinement framework from the buttons. You only see the frameworks assigned to your account.
3. Enter your initial research question or statement.
4. Answer the guided questions. Each one comes with suggested answers: click one, type its number, or write your own. The buttons under each question let you go back, skip, finish a dimension or finish early. Restart, clear and finish early ask for confirmation first. A progress panel shows which dimensions have been captured.
5. Review the refined question, structured statement, semantic and keyword statements, Boolean search construction and search expansion levels. Open **Search details** for per-concept terms and the full expansion queries.
6. Download the structured output as **JSON** (for downstream tools) or a **Markdown** report. Both include the full refinement trace.
7. Optionally complete the short feedback survey and choose whether your data may be retained for research.

Every session is stored with its full question/answer and command history. If you close the page part-way through, you will be offered **Resume** the next time you log in.

### Commands during the dialogue

| Command                      | What it does                                                |
| ---------------------------- | ----------------------------------------------------------- |
| `/back` (`/prev`)            | Return to the previous dimension                            |
| `/skip`                      | Skip the current dimension                                  |
| `/done`                      | Accept what you have for this dimension and move on         |
| `/clear`                     | Clear the answer for the current dimension                  |
| `/restart`                   | Start the refinement again from the first dimension         |
| `/submit` (`/end`)           | Finish early and generate the refined query                 |
| `/status`, `/steps`, `/help` | Show progress, the list of dimensions, and help             |
| `/frameworks`                | Choose a different framework (chat UI only)                 |

---

## Running locally

### Prerequisites

- Python 3.12+
- Poetry

### Backend

```bash
poetry install --with dev

# Copy the template for your LLM provider:
cp .env.cloud .env              # Cloud providers (Anthropic Claude recommended, OpenAI, etc.)
cp .env.local .env              # Ollama — local models
cp .env.selfhosted .env         # Self-hosted inference (vLLM, etc.)

# Set LLM_API_KEY in .env (cloud providers), then:
poetry run alembic upgrade head
poetry run uvicorn query_refinement_module.api.main:app --reload
```

Backend: http://localhost:8001 — API docs at `/docs`

### Chainlit UI

The chat UI runs the same persisted workflow as the API in-process: same database, session store, access control and audit trail. Login is required.

```bash
# One-off: set a signing secret for chat logins in .env
poetry run chainlit create-secret        # copy the CHAINLIT_AUTH_SECRET line into .env

# Create an account and grant it a framework (see "User management" below)
poetry run python scripts/create_user.py --username alice --framework pico_advanced

poetry run chainlit run query_refinement_module/chainlit_app.py --host 0.0.0.0 --port 8501
```

Chainlit: http://localhost:8501

## Production deployment

Docker is the recommended path.

```bash
# Copy the matching production template
cp .env.prod .env                # Anthropic Claude (recommended, cloud)
cp .env.prod.selfhosted .env     # Self-hosted or local inference

# Set these required values in .env:
# SECRET_KEY, LLM_API_KEY (if using cloud), POSTGRES_USER, POSTGRES_PASSWORD, POSTGRES_DB, ALLOWED_ORIGINS

docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d
```

See [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md) for the full guide including SSL, backups, and migrations.

For a local multi-service run with the API, database, Redis, and the default Chainlit UI:

```bash
docker compose -f docker-compose.fullstack.yml up -d --build
```

---

## CLI usage

```bash
# List available frameworks
poetry run query-refine --list-frameworks

# Start an interactive session
poetry run query-refine --framework pico_advanced

# Start an interactive session and write logs/traces to disk
poetry run query-refine --framework pico_advanced --trace-dir logs/cli-trace --log-dir logs/cli
```

At the end of the session, the CLI now runs the full chained agent flow **A → B → C → D** automatically. Agent D generates search expansion levels for fallback retrieval when initial search yields insufficient results. The Level 0 query is always the exact clarified statement; broader levels are search-only and do not change the canonical refined question.

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

| Endpoint                    | Description                                          |
| --------------------------- | ---------------------------------------------------- |
| `POST /start`               | Begin a refinement session                           |
| `POST /queries/{id}/answer` | Submit an answer                                     |
| `POST /normalize`           | Agent A — clarified query only                       |
| `POST /represent`           | Agent B — semantic + keyword queries + concept graph |
| `POST /construct`           | Agent C — keyword search constructions + filters     |
| `POST /synthesize`          | Run full A → B → C pipeline in one call              |
| `POST /expand`              | Agent D — optional search broadening levels          |

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
  application/             Refinement application-layer facade and workflow services
  db/                      Database models and migrations
  schema/                  LLM prompt builders and response schemas
  providers/               LLM provider abstraction
  core.py                  Refinement session and synthesis logic

refinement_frameworks/     YAML framework definitions
scripts/                   User management utilities
tests/                     Automated tests
docs/                      Technical documentation
```

---

## Documentation

- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) — Internal architecture, layering, and extension points for contributors
- [docs/API.md](docs/API.md) — Full API reference for external integrations
- [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md) — Production deployment, infrastructure, and backups
- [docs/FRAMEWORKS.md](docs/FRAMEWORKS.md) — How to define custom refinement frameworks

## Contributor orientation

The refinement backend now follows a layered split:

- Route adapters in `query_refinement_module/api/routes/refinement.py`
- Transport models in `query_refinement_module/api/refinement_schemas.py`
- Application façade in `query_refinement_module/application/refinement_api_service.py`
- Shared interactive workflow in `query_refinement_module/application/interactive_refinement_service.py`
- Workflow collaborators in `query_refinement_module/application/`

Use [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) as the maintainer guide for where to add new endpoint behavior, new agent steps, or cross-cutting workflow rules.

## License

See [LICENSE](LICENSE) file.
