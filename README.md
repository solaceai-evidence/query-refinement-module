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
#   cp .env.openai-gpt-4o .env                  # OpenAI GPT-4o (cloud)
#   cp .env.ollama-qwen2.5-72b .env            # Ollama — Qwen 2.5 72B (local)
#   cp .env.vllm .env                          # vLLM (self-hosted; use ./start_vllm.sh)
# Then set LLM_API_KEY (cloud) or verify LLM_API_BASE for vLLM / non-default local hosts
poetry run alembic upgrade head
poetry run uvicorn query_refinement_module.api.main:app --reload
```

Or use the startup script, which checks the environment and launches the API with the configured Poetry environment:

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
2. Copy the production environment file that matches your LLM backend and fill in the values:

```bash
cp .env.prod .env                    # Anthropic Claude Sonnet 4.6
# or
cp .env.prod.openai-gpt-4o .env      # OpenAI GPT-4o
# or
cp .env.prod.ollama-qwen2.5-72b .env # Ollama / Qwen 2.5 72B
```

3. In `.env`, set the values that make the app safe and usable in your environment:

- `SECRET_KEY`
- `LLM_API_KEY` — required for cloud providers (Anthropic, OpenAI); leave blank for Ollama or vLLM
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

If you are deploying to production against OpenAI GPT-4o or Ollama / Qwen 2.5 72B, use `.env.prod.openai-gpt-4o` or `.env.prod.ollama-qwen2.5-72b` instead of `.env.prod`. For local development against OpenAI, Anthropic, Ollama, or vLLM, use `.env.openai-gpt-4o`, `.env.anthropic-claude-sonnet-4-6`, `.env.ollama-qwen2.5-72b`, or `.env.vllm`.

See [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md) for the full deployment guide.

## CLI usage

```bash
# List available frameworks
poetry run query-refine --list-frameworks

# Start an interactive session
poetry run query-refine --framework pico_advanced
```

## How frameworks are loaded and selected

Framework definitions are loaded from the YAML file pointed to by `REFINEMENT_FRAMEWORK_PATH`. In the provided environment templates this points to `./refinement_frameworks/frameworks.yaml` for local development and `/app/refinement_frameworks/frameworks.yaml` in Docker.

Each top-level key in that YAML file is a framework name. For example, the built-in file includes names such as `cocopop`, `mph_dissertation`, and `pico_advanced`.

How the app picks a framework at runtime depends on the entrypoint:

- Web UI: the frontend requests the list of available frameworks from the API, then the user chooses one before starting refinement. The list may be filtered by the current user's framework access.
- API clients: must send `framework_name` in the `/api/v1/refinement/start` request body. There is no API-side default if it is omitted.
- CLI: pass `--framework <name>`. If exactly one framework is loaded, the CLI will use it automatically; otherwise it will require `--framework`.

Useful commands:

```bash
# See which framework names are currently loaded
poetry run query-refine --list-frameworks

# Point the app at a different framework file for this shell session
export REFINEMENT_FRAMEWORK_PATH=./refinement_frameworks/frameworks.yaml
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

| Variable                   | Description                                                                                            |
| -------------------------- | ------------------------------------------------------------------------------------------------------ |
| `LLM_API_KEY`              | API key for cloud providers (Anthropic, OpenAI); leave blank for Ollama or vLLM                        |
| `LLM_MODEL`                | Model identifier (default: `anthropic/claude-sonnet-4-6`)                                              |
| `LLM_API_BASE`             | Optional base URL override; Ollama defaults to `http://localhost:11434`, set explicitly for vLLM       |
| `LLM_MAX_OUTPUT_TOKENS`    | Output-token ceiling for LLM calls; does not change provider-managed context windows                   |
| `LLM_CONTEXT_WINDOW`       | Optional client-side context window override for local backends that expose one; currently Ollama only |
| `LLM_CONSTRAINED_DECODING` | `true` to enable vLLM guided JSON decoding — **vLLM only**; leave `false` for all other providers      |
| `SECRET_KEY`               | Secret key for session tokens — change this in production                                              |
| `DATABASE_URL`             | Database connection string (default: SQLite for local development)                                     |
| `ALLOW_REGISTRATION`       | Set to `false` to disable self-registration                                                            |
| `ENFORCE_WORKFLOW_LIMIT`   | `true` = one workflow per user; `false` = unlimited                                                    |
| `INTEGRATION_API_KEY`      | Optional: for server-to-server API access without a user login                                         |

For the built-in templates, most provider-specific knobs are now internal defaults:
- Anthropic defaults prompt caching on and keeps the production prompt variant.
- OpenAI defaults prompt caching off and uses the standard cloud path with no local API base.
- Ollama defaults the API base to `http://localhost:11434`, the prompt variant to `open_llm`, the context window to `num_ctx=16384`, and the local request timeout to `timeout=1800.0` for long structured-output runs.
- OpenAI-compatible self-hosted endpoints such as vLLM still need an explicit API base and should keep constrained decoding enabled when using vLLM.
- Rate-limit values in the templates are prefilled starting points, not required blanks to complete. Only change them if your provider tier or deployment load differs.

Configuration ownership is intentionally split:
- `query_refinement_module/api/config.py` owns API/web settings such as auth, CORS, sessions, Redis, and HTTP ingress throttling.
- `query_refinement_module/settings.py` owns outbound LLM runtime settings such as model, API base, prompt caching, context window, constrained decoding, and provider-side throttling.

The canonical throughput variables are now separated by layer:
- `API_RATE_LIMIT_RPM` and `API_RATE_LIMIT_PER_USER_RPM` apply to HTTP ingress throttling only.
- `LLM_PROVIDER_RATE_LIMIT_RPM`, `LLM_PROVIDER_RATE_LIMIT_TPM`, and `LLM_PROVIDER_MAX_CONCURRENT` apply to outbound provider throttling only.
- Legacy shared names are still accepted for compatibility, but new configs should use the explicit API and provider names.

`LLM_CONTEXT_WINDOW` is only for backends that support a client-side context-size parameter. Today that means Ollama via `num_ctx`. It does not change the provider-managed context window for Anthropic or OpenAI.

For external systems calling the API without a user login, also set:
- `INTEGRATION_API_KEY` — shared key sent via the `X-API-Key` header
- `INTEGRATION_SERVICE_USERNAME` — optional identity label (defaults to `api_integration_service`)

Browser logins use an httpOnly auth cookie by default. Non-browser clients and automated tests can still send the same JWT as `Authorization: Bearer <token>` after extracting it from that cookie.

The integration service user is a normal account, not a superuser. It must be granted framework access explicitly before `/api/v1/refinement/start` will succeed.

After changing these values, restart the API process or container.

### LLM provider backends

Seven pre-filled environment templates are provided:

| File                               | Provider                                 | Constrained decoding |
| ---------------------------------- | ---------------------------------------- | -------------------- |
| `.env.anthropic-claude-sonnet-4-6` | Anthropic Claude Sonnet 4.6              | off                  |
| `.env.openai-gpt-4o`               | OpenAI GPT-4o                            | off                  |
| `.env.prod`                        | Anthropic Claude Sonnet 4.6 (production) | off                  |
| `.env.prod.openai-gpt-4o`          | OpenAI GPT-4o (production)               | off                  |
| `.env.prod.ollama-qwen2.5-72b`     | Ollama — Qwen 2.5 72B (production)       | off                  |
| `.env.ollama-qwen2.5-72b`          | Ollama — Qwen 2.5 72B (local)            | off                  |
| `.env.vllm`                        | vLLM — Llama 3.1 8B                      | **on**               |

To switch to vLLM:

```bash
cp .env.vllm .env
# Local default:
./start_vllm.sh
# Explicit model example:
# ./start_vllm.sh meta-llama/Llama-3.1-8B-Instruct
# Edit LLM_API_BASE to point at your vLLM server
# Edit LLM_MODEL to match the model loaded on the server
```

When `LLM_CONSTRAINED_DECODING=true` the provider sends
`guided_json` (the full Pydantic JSON Schema) in every structured LLM call,
enforcing schema-conformant output at the token level.  This option must only
be set when `LLM_API_BASE` points at a vLLM server — it
will break structured output for Anthropic, OpenAI, and Ollama.

### Agent setup

If you are using this repository in Agent mode, pick one of these local model
backends and copy the matching environment file to `.env`.

#### Option 1: Ollama

Use this if you already have Ollama installed and want a simple local setup.

**Recommended for synthesis quality** — Qwen 2.5 72B (large-memory local setup):

```bash
ollama pull qwen2.5:72b
cp .env.ollama-qwen2.5-72b .env
```

The template already assumes Ollama's default endpoint, `num_ctx=16384`, and a `timeout=1800.0` request cap for long local calls. Only add overrides if your Ollama server is remote, memory-constrained, or needs a different timeout:

```dotenv
LLM_API_BASE=http://localhost:11434
LLM_API_KEY=
LLM_CONSTRAINED_DECODING=false
LLM_COMPLETION_KWARGS={"num_ctx": 8192, "timeout": 2400.0}
```

#### Option 2: vLLM

Use this if you have GPU resources and want the OpenAI-compatible vLLM server.
On macOS, vLLM runs CPU-only, so keep local testing on the default 8B model or use Ollama instead.

Note: `meta-llama/Llama-3.1-8B-Instruct` is a gated Hugging Face model. You
must log in with Hugging Face access before vLLM can download it, or point
vLLM at a local Hugging Face-compatible model directory that already contains
the weights and tokenizer files.

If you do not already have access to the model, first request access on the
model page at Hugging Face, then authenticate locally:

```bash
hf auth login
```

If you prefer to pre-download the model instead of letting vLLM fetch it on
startup, download it into a Hugging Face-compatible directory and serve that
path:

```bash
hf download meta-llama/Llama-3.1-8B-Instruct \
  --local-dir /path/to/llama-3.1-8b
vllm serve /path/to/llama-3.1-8b --port 8000 --dtype bfloat16 --max-model-len 16384
```

If you have already authenticated with Hugging Face, you can also let vLLM
pull the model directly on startup:

```bash
export HF_TOKEN=your-hf-token
pip install vllm
vllm serve meta-llama/Llama-3.1-8B-Instruct \
  --port 8000 --dtype bfloat16 --max-model-len 16384
cp .env.vllm .env
```

Then point the app at the vLLM server:

```dotenv
LLM_MODEL=openai/meta-llama/Llama-3.1-8B-Instruct
LLM_API_BASE=http://localhost:8000/v1
LLM_API_KEY=EMPTY
HF_TOKEN=your-hf-token
LLM_CONSTRAINED_DECODING=true
```

Verify the server before starting the app:

```bash
curl http://localhost:8000/v1/models
```

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
- **vLLM** (`LLM_CONSTRAINED_DECODING=true`): guided JSON decoding enforces the full Pydantic schema at the token level — structurally invalid output is impossible. This is the most reliable option for a production research study.

### Prompt caching

`LLM_ENABLE_PROMPT_CACHING=true` (Anthropic only) tells Anthropic's servers to cache the static system messages (messages 1–2 above) across calls. This reduces cost and latency for repeated calls within a session. It has no effect on what the model sees — the same tokens are always sent regardless of caching status. This setting must be `false` for Ollama and vLLM, which do not support the Anthropic cache-control header.

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

# Grant an existing user access to additional frameworks
poetry run python scripts/create_user.py --username alice --framework pico_advanced --framework cocopop
```

### Framework access

Non-superuser accounts can only start a refinement workflow for frameworks they've been explicitly granted access to (`POST /api/v1/refinement/start` returns `403 You are not authorized to use framework '<name>'` otherwise). Grant access with the `--framework` flag above, or via the admin API (`POST /api/admin/frameworks/users/{user_id}/access`).

This also applies to the built-in `api_integration_service` account used for direct API/integration calls — it is created automatically on first use but starts with **no** framework access and must be granted access the same way.

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
- [docs/DATA_RECOVERY.md](docs/DATA_RECOVERY.md) — Database and cache export/recovery procedures for hosted deployments

## License

See [LICENSE](LICENSE) file.
