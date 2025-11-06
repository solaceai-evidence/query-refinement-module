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

## Quick Start

```python
from query_refinement_module.core import QueryRefinementManager
from query_refinement_module.providers import ConsoleTracing
from query_refinement_module.schema import registry

# Supply concrete implementations in your application
llm_provider = MyLLMProvider()
query_analyzer = MyQueryAnalyzer()

framework = registry.get_framework("pico_enhanced")
manager = QueryRefinementManager(
  llm_provider=llm_provider,
  query_analyzer=query_analyzer,
  tracing_provider=ConsoleTracing(),
)

session = manager.initialize(
  original_query="What are the effects of aspirin on heart disease?",
  refinement_framework=framework,
)

while not session.is_complete():
  step = manager.process_next_step(session)
  if not step:
    break
  print(step["aspect_name"], step.get("structured_payload"))

print(session.get_step_summary())
print(session.get_full_conversation())
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
medical_pico:
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

pico = registry.get_framework("medical_pico")
legal = registry.get_framework("legal_research")
business = registry.get_framework("business_analysis")
```

## Documentation

- [docs/custom_schemas.md](docs/custom_schemas.md) — authoring and loading refinement frameworks
- [docs/response_format_guide.md](docs/response_format_guide.md) — enforcing structured output
- [docs/examples_field_reference.md](docs/examples_field_reference.md) — managing few-shot examples
- [docs/dependencies.md](docs/dependencies.md) — handling aspect ordering and validation
- [docs/api_integration_guide.md](docs/api_integration_guide.md) — wiring providers, analyzers, and tracing
- [docs/user_commands.md](docs/user_commands.md) — interactive command reference
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
poetry run query-refine --framework pico_clinical_research  # Launch interactive session
```

Set `REFINEMENT_FRAMEWORK_PATH` (or populate it in your `.env`) before running so the CLI can load your YAML definitions. During a session you can use commands such as `/help`, `/status`, `/back`, and `/goto 2` to navigate.

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
poetry run query-refine --framework pico_clinical_research
```

No additional model flags are required—the CLI automatically reuses the configured LLM stack.

