# query-refinement-module

Standalone query refinement engine for orchestrating multi-step, refinement-framework–driven conversations. Framework definitions live in YAML so this package stays reusable across Solace-AI and external deployments.

## Installation

```bash
pip install query-refinement-module
```

## Features

- Dependency-aware refinement across user-defined aspects
- YAML frameworks loaded via `REFINEMENT_FRAMEWORK_PATH`
- Structured-response validation with automated retries
- Built-in follow-up history, summaries, and conversation exports
- Tracing hooks through `TraceEventEmitter` and providers
- Session storage adapters (in-memory, Redis) for quick persistence choices
- Local CLI wired to the same LLM/analyzer stack as remote deployments
- Parallel execution with automatic rate limiting and dependency resolution
- Concurrent session storage with built-in race condition protection

## Quick Start

1. Install and configure the project:

  ```bash
  poetry install
  cp .env_example .env
  ```

1. Edit `.env` with your refinement framework path and LLM settings (see [LLM Configuration](#llm-configuration)).
1. Inspect available frameworks and launch the CLI:

  ```bash
  poetry run query-refine --list-frameworks
  poetry run query-refine --framework pico_advanced
  ```

For programmatic use, build the manager from the environment-driven helpers so the CLI and service share the same configuration:

```python
from query_refinement_module import build_manager_from_env, registry

framework = registry.get_framework("pico_advanced")
manager = build_manager_from_env()

session = manager.initialize(
    original_query="Evaluate whether low-dose aspirin helps prevent recurrent myocardial infarction.",
    refinement_framework=framework,
)
print(manager.get_initialization_summary(session))
```

## Custom Refinement Frameworks

Refinement frameworks are required and must be defined in a YAML file. Set the `REFINEMENT_FRAMEWORK_PATH` environment variable to point to your framework file:

```bash
export REFINEMENT_FRAMEWORK_PATH=/path/to/your/custom_schemas.yaml
```

```yaml
my_framework:
  - id: dimension_id
    name: Dimension Name
    description: What this dimension refines
    analysis_prompt: |
      Analyze the query: {query}
      Focus on the considerations relevant to this dimension.
    response_format:
      additional_fields:
        confidence: float
      field_descriptions:
        needs_refinement: "Whether this dimension needs clarification"
        explanation: "Brief rationale"
        suggested_question: "Single follow-up to resolve the gap"
        confidence: "Confidence score 0.0-1.0 (optional)"
    allow_follow_up: true
    max_follow_ups: 2
    metadata:
      priority: high
```

Then load it via the registry:

```python
from query_refinement_module.schema import registry

framework = registry.get_framework("my_framework")
```

### Requirements

- `pip install pyyaml`
- Set the `REFINEMENT_FRAMEWORK_PATH` environment variable

See [docs/custom_schemas.md](docs/custom_schemas.md) for end-to-end guidance on authoring refinement frameworks.

## Usage

### Environment Setup

```bash
# Set the path to your refinement framework file
export REFINEMENT_FRAMEWORK_PATH=/path/to/your/custom_frameworks.yaml

# Or add to your .env file
echo "REFINEMENT_FRAMEWORK_PATH=/path/to/custom_frameworks.yaml" >> .env
```

### List Available Frameworks

```python
from query_refinement_module.schema import registry

print(registry.list_frameworks())  # ['my_framework', 'legal_research', ...]
summary = registry.describe_framework("my_framework")
print(summary["name"], summary["num_dimensions"])
```

### Using Different Frameworks

Define multiple frameworks in your YAML file:

```yaml
# custom_frameworks.yaml
medical_pico_advanced:
  - id: population
    name: Population
    # ... dimensions ...

legal_research:
  - id: jurisdiction
    name: Jurisdiction
    # ... dimensions ...

business_analysis:
  - id: market
    name: Market Scope
    # ... dimensions ...
```

Then use them:

```python
from query_refinement_module.schema import registry

pico_advanced = registry.get_framework("medical_pico_advanced")
legal = registry.get_framework("legal_research")
business = registry.get_framework("business_analysis")
```

## Testing

The project uses a structured testing approach with three test categories:

```bash
# Run all tests
poetry run pytest tests/

# Unit tests (fast, isolated)
poetry run pytest tests/unit/

# Integration tests (database, workflows)
poetry run pytest tests/integration/

# API tests (requires running server)
cd tests/api && ./run_api_tests.sh
```

See [tests/README.md](tests/README.md) for complete testing guidelines, examples, and CI/CD setup.

## Documentation

- [docs/custom_schemas.md](docs/custom_schemas.md) — authoring and loading refinement frameworks
- [docs/response_format_guide.md](docs/response_format_guide.md) — enforcing structured output
- [docs/examples_field_reference.md](docs/examples_field_reference.md) — managing few-shot examples
- [docs/dependencies.md](docs/dependencies.md) — handling aspect ordering and validation
- [docs/api_integration_guide.md](docs/api_integration_guide.md) — wiring providers, analyzers, and tracing
- [docs/user_commands.md](docs/user_commands.md) — interactive command reference
- [docs/api_service.md](docs/api_service.md) — REST API documentation (see also [API_README.md](API_README.md))
- [examples/](examples/) — sample frameworks and YAML snippets

## Session Storage Options

```python
from query_refinement_module import (
  QueryRefinementService,
  InMemorySessionStorage,
  RedisSessionStorage,
)
```

- `InMemorySessionStorage`: ideal for unit tests or single-process deployments.
- `RedisSessionStorage`: requires `redis` (Python library) and a running Redis instance.

Spin up Redis quickly with Docker:

```bash
docker run --name refinement-redis -p 6379:6379 -d redis:7-alpine
```

Then configure the service:

```python
import redis

redis_client = redis.Redis(host="localhost", port=6379)
storage = RedisSessionStorage(redis_client)
service = QueryRefinementService(manager, storage)
```

When Redis is unavailable, substitute `InMemorySessionStorage()`, understanding sessions reset on process restart.

## CLI Playground

Explore the refinement flow locally without wiring an API:

```bash
poetry run query-refine --list-frameworks                   # Inspect available schemas
poetry run query-refine --framework pico_advanced  # Launch interactive session
```

Set `REFINEMENT_FRAMEWORK_PATH` (or populate it in your `.env`) before running so the CLI can load your YAML definitions. During a session you can use commands such as `/help`, `/status`, `/back`, and `/goto 2` to navigate. If you want to stop early and synthesize with the clarifications gathered so far, issue `/submit` (or `/end`).

When every aspect is processed the CLI prints the full conversation along with a synthesized refined query that merges the original question with any clarifications you provided.

### LLM Configuration

The CLI and API service now read the same environment-driven configuration via `LLMSettings`. Declare the following variables (see `.env_example` for defaults):

- `QUERY_REFINEMENT_LLM_MODEL` (required model id understood by litellm)
- `QUERY_REFINEMENT_LLM_API_KEY`
- `QUERY_REFINEMENT_LLM_API_BASE`
- `QUERY_REFINEMENT_LLM_TEMPERATURE`
- `QUERY_REFINEMENT_LLM_MAX_TOKENS`
- `QUERY_REFINEMENT_LLM_COMPLETION_KWARGS` (JSON object for extra kwargs)

Provider-specific secrets such as `OPENAI_API_KEY` or `ANTHROPIC_API_KEY` remain supported by [litellm](https://github.com/BerriAI/litellm). Once the environment is configured, simply run:

```bash
poetry run query-refine --framework pico_advanced
```

No additional model flags are required—the CLI automatically reuses the configured LLM stack.

