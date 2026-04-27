# Query Refinement Module

A web-based tool that helps people turn a rough research idea into a clearer question. It asks a short series of guided questions based on a chosen refinement framework, then produces a refined statement that is more focused to use for a literature search or project plan.


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
poetry install --with dev
# Pick the template for your LLM provider:
#   cp .env.anthropic-claude-sonnet-4-6 .env   # Anthropic Claude (cloud)
#   cp .env.ollama-llama3.3-70b .env           # Ollama — Llama 3.3 70B (local)
#   cp .env.vllm .env                          # vLLM (self-hosted GPU)
# Then set QUERY_REFINEMENT_LLM_API_KEY (cloud) or verify API_BASE (local)
poetry run alembic upgrade head
poetry run uvicorn query_refinement_module.api.main:app --reload
```

Or use the startup script, which checks the environment and runs migrations automatically:

```bash
./start_api.sh
```

Backend available at: http://localhost:8001 (interactive API docs at /docs)

### Frontend

```bash
cd frontend
npm install
npm run dev
```

Frontend available at: http://localhost:5173

## Production deployment

The simplest deployment path is Docker. This is the recommended option if you are putting the app on a server for other people to use.

1. Install Docker and the Docker Compose plugin on the target server.
2. Copy the production environment file and fill in the values:

```bash
cp .env.prod .env
```

3. In `.env`, set the values that make the app safe and usable in your environment:

- `SECRET_KEY`
- `QUERY_REFINEMENT_LLM_API_KEY` — required for cloud providers (Anthropic, OpenAI); leave blank for Ollama or vLLM
- `POSTGRES_USER`
- `POSTGRES_PASSWORD`
- `POSTGRES_DB`
- `ALLOWED_ORIGINS`

4. Start the stack:

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d
```

   Or use the pre-flight startup script, which checks connectivity and runs migrations before starting Gunicorn:

```bash
./start_production.sh
```

5. Open the site in your browser and check the app, API docs, and sign-in flow.

If you are deploying against a local AI server instead of a hosted provider, use `.env.ollama-llama3.3-70b` or `.env.vllm` as the starting point instead of `.env.prod`. For local Anthropic Claude development, use `.env.anthropic-claude-sonnet-4-6`.

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

Key environment variables — pick the template for your provider and copy it to `.env`:

| Variable                                    | Description                                                                                       |
| ------------------------------------------- | ------------------------------------------------------------------------------------------------- |
| `QUERY_REFINEMENT_LLM_API_KEY`              | API key for cloud providers (Anthropic, OpenAI); leave blank for Ollama or vLLM                   |
| `QUERY_REFINEMENT_LLM_MODEL`                | Model identifier (default: `anthropic/claude-sonnet-4-6`)                                         |
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

| File                               | Provider                       | Constrained decoding |
| ---------------------------------- | ------------------------------ | -------------------- |
| `.env.anthropic-claude-sonnet-4-6` | Anthropic Claude Sonnet 4.6    | off                  |
| `.env.prod`                        | Anthropic Claude (production)  | off                  |
| `.env.ollama-llama3.3-70b`         | Ollama — Llama 3.3 70B (local) | off                  |
| `.env.vllm`                        | vLLM — Llama 3.3 70B (GPU)     | **on**               |

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

## Architecture: how the LLM pipeline works

Understanding this helps when choosing a provider and diagnosing unexpected output.

### Dimension-by-dimension evaluation

The refinement workflow processes each framework dimension (e.g. Population, Intervention, Comparison, Outcome in PICO) as a **separate, independent LLM call**. The framework YAML (~109 KB) is parsed at startup; only the rendered specification for the current dimension is sent to the model.

Each call receives:

| #   | Message role   | Content                                                | Grows over the session?              |
| --- | -------------- | ------------------------------------------------------ | ------------------------------------ |
| 1   | System         | Global directive                                       | No — static                          |
| 2   | System         | User context profile                                   | No — static                          |
| 3   | System         | Previously completed dimension *values* (summaries)    | +~150 tokens per completed dimension |
| 4   | System         | Current dimension spec + examples                      | No — one dimension at a time         |
| 5   | User           | Original query                                         | No — static                          |
| 6   | User/Assistant | Follow-up Q&A for **this dimension only**              | +~200 tokens per follow-up turn      |
| 7   | System         | Terminal reinforcement (only after ≥3 follow-up turns) | No — static repeat                   |

The full dialogue from prior dimensions is **not** carried forward — only its assembled output value. This keeps the token budget flat and eliminates cross-dimension noise.

### Context window budget

At the synthesis stage (the most token-heavy call), the budget looks roughly like:

| Component                                               | Approximate tokens |
| ------------------------------------------------------- | ------------------ |
| System prompts (global + user context + dimension spec) | ~2,000             |
| All completed dimension values                          | ~1,500             |
| Follow-up turns for current dimension                   | ~1,000             |
| Original query                                          | ~100               |
| **Total**                                               | **~4,600**         |

Well within the 16 K window configured for Ollama (`num_ctx=16384`) and vLLM (`--max-model-len 16384`), and far below Anthropic Claude's 200 K limit.

### Structured output strategy

Every dimension evaluation and synthesis call returns a Pydantic-validated JSON object. Two strategies are used depending on provider:

- **Anthropic / Ollama**: JSON is produced by instruction in the prompt. Occasional malformed responses are possible, particularly from smaller or under-prompted models.
- **vLLM** (`QUERY_REFINEMENT_LLM_CONSTRAINED_DECODING=true`): guided JSON decoding enforces the full Pydantic schema at the token level — structurally invalid output is impossible. This is the most reliable option for a production research study.

### Prompt caching

`QUERY_REFINEMENT_ENABLE_PROMPT_CACHING=true` (Anthropic only) tells Anthropic's servers to cache the static system messages (messages 1–2 above) across calls. This reduces cost and latency for repeated calls within a session. It has no effect on what the model sees — the same tokens are always sent regardless of caching status. This setting must be `false` for Ollama and vLLM, which do not support the Anthropic cache-control header.

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
