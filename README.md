# query-refinement-module

This module is designed to be independent from the Solace-AI system while providing seamless integration when used with it. It can be published as a standalone package for any scientific query refinement use case.

## Installation

```bash
pip install query-refinement-module
```

## Features

- 🎯 **Structured Query Refinement**: Multi-dimensional analysis of queries
- 🔧 **Custom Schemas**: Define your own refinement dimensions via YAML
- 🔄 **Follow-up Support**: Iterative refinement with configurable depth
- 🌐 **Domain Agnostic**: Works across research, legal, business, and other domains
- 🎨 **Extensible**: Rich metadata support for custom behaviors

## Quick Start

```python
from query_refinement import QueryRefiner
from query_refinement.schemas import get_schema

# Load your custom schema
my_schema = get_schema("my_custom_schema")
refiner = QueryRefiner(dimensions=my_schema)

# Refine a query
result = refiner.refine(
    "What are the effects of aspirin on heart disease?"
)

print(result.refined_query)
print(result.suggested_questions)
```

## Custom Schemas

Custom schemas are **required** and must be defined in a YAML file. Set the `CUSTOM_SCHEMAS_PATH` environment variable to point to your schema file:

```bash
export CUSTOM_SCHEMAS_PATH=/path/to/your/custom_schemas.yaml
```

```yaml
my_schema:
  - id: dimension_id
    name: Dimension Name
    description: What this dimension refines
    analysis_prompt: |
      Analyze: {query}
      
      Consider:
      1. First consideration
      2. Second consideration
      
      Ask if clarification needed.
    allow_follow_up: true
    max_follow_ups: 2
    metadata:
      priority: high
```

Then use your schema:

```python
from query_refinement.schemas import get_schema

my_schema = get_schema("my_schema")
refiner = QueryRefiner(dimensions=my_schema)
```

**Requirements:** 
- `pip install pyyaml`
- Set `CUSTOM_SCHEMAS_PATH` environment variable

📖 **Full guide**: See [docs/custom_schemas.md](docs/custom_schemas.md) and [YAML_REFERENCE.md](YAML_REFERENCE.md) for detailed instructions and examples.

## Usage

### Environment Setup

```bash
# Set the path to your custom schemas file
export CUSTOM_SCHEMAS_PATH=/path/to/your/custom_schemas.yaml

# Or add to your .env file
echo "CUSTOM_SCHEMAS_PATH=/path/to/custom_schemas.yaml" >> .env
```

### List Available Schemas

```python
from query_refinement.schemas import list_schemas, describe_schema

# See all available schemas from your custom file
print(list_schemas())  # ['my_schema', 'legal_research', ...]

# Get detailed information about a schema
info = describe_schema("my_schema")
print(f"Framework: {info['framework']}")
print(f"Dimensions: {info['num_dimensions']}")
```

### Using Different Schemas

Define multiple schemas in your YAML file:

```yaml
# custom_schemas.yaml
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
from query_refinement.schemas import get_schema

# Medical research
pico = get_schema("medical_pico")

# Legal research
legal = get_schema("legal_research")

# Business analysis
business = get_schema("business_analysis")
```

## Documentation

- [Custom Schema Guide](docs/custom_schemas.md) - How to create and use custom schemas
- [API Reference](docs/api.md) - Complete API documentation
- [Examples](examples/) - Sample schemas and usage patterns

