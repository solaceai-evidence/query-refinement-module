# Custom Schema Guide

This guide explains how to add your own custom refinement schemas without modifying the source code.

## Overview

The query refinement module allows you to define custom schemas externally via a YAML file. This enables you to:

- Add domain-specific refinement dimensions
- Customize the refinement process for your use case
- Share schemas across teams without code changes
- Override built-in schemas with your own versions

## Quick Start

1. Create a file named `custom_schemas.yaml` (or `custom_schemas.yml`)
2. Place it in one of these locations (in order of priority):
   - Path specified in `QUERY_REFINEMENT_SCHEMAS_PATH` environment variable
   - Current working directory
   - `~/.query_refinement/custom_schemas.yaml` (in your home directory)
3. Define your schemas following the format below

## Prerequisites

Custom schemas require PyYAML:

```bash
pip install pyyaml
```

## Schema File Format

The `custom_schemas.yaml` file should contain schema definitions where each top-level key is a schema name and each value is a list of refinement dimensions:

```yaml
schema_name:
  - id: dimension_id
    name: Dimension Name
    description: Description of what this dimension refines
    analysis_prompt: |
      Multi-line prompt template with {query} placeholder.
      
      Use the pipe (|) character for multi-line strings.
      No escaping needed for special characters!
    allow_follow_up: false
    max_follow_ups: 2
    metadata:
      domain: general
      priority: high
```

### Required Fields

- **`id`** (string): Unique identifier for the dimension within the schema
- **`name`** (string): Human-readable name for the dimension
- **`description`** (string): Brief description of what this dimension refines
- **`analysis_prompt`** (string): Template for analyzing if this dimension needs refinement
  - Must include `{query}` placeholder where the user's query will be inserted
  - Should guide the LLM on how to analyze and what to ask
  - Use `|` for multi-line prompts

### Optional Fields

- **`allow_follow_up`** (boolean, default: `false`): Whether this dimension supports follow-up questions
- **`max_follow_ups`** (integer, default: `2`): Maximum number of follow-up rounds if enabled
- **`metadata`** (object, default: `{}`): Additional metadata for extensibility
  - Common fields: `domain`, `priority`, `framework`, `examples`

## Example: Simple Custom Schema

```yaml
project_scoping:
  - id: timeline
    name: Project Timeline
    description: Clarifies project deadlines and milestones
    analysis_prompt: |
      Does this project query specify a timeline?
      
      Query: {query}
      
      If not, ask about deadlines, milestones, or timeframe.
      
      Respond with:
      {
        "needs_refinement": true/false,
        "suggested_question": "..."
      }
    allow_follow_up: true
    max_follow_ups: 2
    metadata:
      domain: project_management
      priority: high

  - id: budget
    name: Budget Constraints
    description: Identifies budget limitations and resource constraints
    analysis_prompt: |
      Does this query mention budget or resource constraints?
      
      Query: {query}
      
      If not specified but relevant, ask about budget range.
      
      Respond with:
      {
        "needs_refinement": true/false,
        "suggested_question": "..."
      }
    allow_follow_up: false
    metadata:
      domain: project_management
      priority: medium
```

## Using Environment Variable

For team or production deployments, you can specify the schema file location via environment variable:

```bash
export QUERY_REFINEMENT_SCHEMAS_PATH="/path/to/your/custom_schemas.yaml"
```

Or in a `.env` file:

```
QUERY_REFINEMENT_SCHEMAS_PATH=/path/to/your/custom_schemas.yaml
```

You can also point to a directory:

```bash
export QUERY_REFINEMENT_SCHEMAS_PATH="/path/to/config/directory"
# Will look for custom_schemas.yaml or custom_schemas.yml in that directory
```

## Example: Complex Schema with Multi-line Prompts

YAML makes complex prompts easy to read and maintain:

```yaml
legal_research:
  - id: source_type
    name: Legal Source Type
    description: Identifies the type of legal source needed
    analysis_prompt: |
      The query doesn't specify the type of legal source needed.
      
      Current query: {query}
      
      What type of legal source are you looking for? Please consider:
      - Case law (judicial opinions)?
        * Federal courts (District, Circuit, Supreme Court)
        * State courts (various levels)
        * Administrative decisions
      - Statutes or regulations?
        * Federal (U.S.C., C.F.R.)
        * State statutes
        * Local ordinances
      - Secondary sources (law review articles, treatises)?
        * Peer-reviewed journals
        * Legal encyclopedias
        * Practice guides
      - Legislative history?
        * Committee reports
        * Floor debates
        * Bill analyses
      
      IMPORTANT NOTES:
      - Multiple source types may be relevant
      - "Recent" in law might mean last 5-10 years
      - Consider jurisdiction-specific sources
      
      Generate ONE concise question to clarify the source type.
      
      Format your response as JSON:
      {
        "needs_refinement": true/false,
        "primary_concern": "brief explanation",
        "suggested_question": "your question here"
      }
    allow_follow_up: true
    max_follow_ups: 2
    metadata:
      domain: legal_research
      priority: high
      related_dimensions:
        - jurisdiction
        - temporal_scope
      examples:
        - What type of legal authority do you need?
        - Are you looking for case law or statutes?

  - id: jurisdiction
    name: Jurisdiction
    description: Clarifies the legal jurisdiction
    analysis_prompt: |
      Analyze the query for jurisdiction clarity:
      
      Query: {query}
      
      Jurisdiction considerations:
      1. Is the jurisdiction explicitly stated?
         - Federal vs. State vs. International
         - Specific circuit or state
         - Local/municipal level
      
      2. Are there conflicts of law issues?
         - Multiple jurisdictions involved
         - Choice of law considerations
      
      3. Is jurisdiction implied by context?
         - Specific statutes (e.g., "ADA" = federal US law)
         - Geographic references
      
      If jurisdiction is unclear, ask for clarification.
      
      Respond in JSON format:
      {
        "needs_refinement": true/false,
        "reason": "Brief explanation",
        "suggested_question": "Question if needed"
      }
    allow_follow_up: true
    max_follow_ups: 2
    metadata:
      domain: legal_research
      priority: high
```

See `examples/custom_schemas.yaml` for a complete, working example.

- Proper prompt engineering
- Multiple dimensions per schema
- Different priority levels
- Domain-specific considerations
- Follow-up configurations

## YAML Tips & Best Practices

### Multi-line Strings

Use `|` for literal blocks (preserves newlines):

```yaml
analysis_prompt: |
  Line 1
  Line 2
  Line 3
```

Use `>` for folded blocks (joins lines):

```yaml
description: >
  This is a long description
  that will be joined into
  a single line.
```

### Special Characters

No escaping needed in YAML! These all work naturally:

```yaml
analysis_prompt: |
  Use "quotes" freely
  Include JSON: {"key": "value"}
  Special chars: @#$%^&*()
  Paths: C:\Users\file.txt
  Placeholders: {query}
```

### Comments

Add documentation with `#`:

```yaml
my_schema:
  # This dimension handles temporal aspects
  - id: temporal_scope
    name: Temporal Scope
    # The analysis prompt should cover multiple scenarios
    analysis_prompt: |
      ...
```

### Lists and Nested Data

```yaml
metadata:
  domain: legal_research
  priority: high
  frameworks:
    - IRAC
    - Legal Research Methodology
  examples:
    - Question 1?
    - Question 2?
  related_dimensions:
    - jurisdiction
    - temporal_scope
```

## Best Practices for Prompts

When creating `analysis_prompt` templates, consider:

1. **Clear Instructions**: Specify what the LLM should analyze and how
2. **Expected Format**: Define the JSON response structure
3. **Examples**: Include 3-5 concrete examples in your prompt
4. **Edge Cases**: Address ambiguous terms and boundary conditions
5. **Domain Context**: Include domain-specific guidance where relevant

Example structure:

```yaml
analysis_prompt: |
  Analyze the query for [dimension]:
  
  Query: {query}
  
  Consider:
  1. [First consideration]
  2. [Second consideration]
  3. [Third consideration]
  
  EDGE CASES:
  - [Edge case 1]
  - [Edge case 2]
  
  Respond in JSON format:
  {
    "needs_refinement": true/false,
    "reason": "Brief explanation",
    "suggested_question": "Question to ask user"
  }
```


## Overriding Built-in Schemas

You can override the built-in schemas (`pico`, `spider`, `climate_humanitarian`, `legal`) by using the same schema name in your custom file:

```yaml
pico:
  - id: custom_population
    name: Population (Custom)
    description: My custom population dimension
    analysis_prompt: |
      Custom analysis for population...
      
      Query: {query}
      
      ...
```

When a custom schema has the same name as a built-in schema, the custom version takes precedence.

## Using Custom Schemas in Code

Once defined, custom schemas work exactly like built-in ones:

```python
from query_refinement.schemas import get_schema, list_schemas

# List all available schemas (including custom ones)
all_schemas = list_schemas()
print(all_schemas)  # ['pico', 'spider', 'my_custom_schema', ...]

# Get your custom schema
my_schema = get_schema("my_custom_schema")

# Use it in refinement
refiner = QueryRefiner(dimensions=my_schema)
result = refiner.refine("My query about...")
```

## Validation

The module validates custom schemas on load:

- **Required fields**: All required fields must be present
- **Placeholder validation**: `analysis_prompt` must include `{query}`
- **Type checking**: Fields must match expected types
- **Error logging**: Invalid dimensions are logged and skipped

## Troubleshooting

### Schema Not Loading

1. Check file location matches one of the search paths
2. Verify YAML syntax is valid (use a YAML validator or linter)
3. Check application logs for error messages
4. Ensure file permissions allow reading
5. Ensure PyYAML is installed: `pip install pyyaml`

### YAML Syntax Errors

Common issues:

- **Indentation**: YAML uses spaces (not tabs) for indentation
- **Missing colons**: Keys need `:` after them
- **Inconsistent indentation**: Use 2 or 4 spaces consistently
- **List items**: Start with `-` and a space

Use an online YAML validator to check your syntax.

### Dimension Skipped

Check logs for validation errors:

- Missing required fields
- Invalid field types
- Missing `{query}` placeholder in prompt

### Schema Not Found

Use `list_schemas()` to see what's actually loaded:

```python
from query_refinement.schemas import list_schemas
print(list_schemas())
```

## Complete Example File

See `examples/custom_schemas.yaml` for a complete, working example with:

## Using Custom Schemas in Code

Once defined, custom schemas work exactly like built-in ones:

```python
from query_refinement.schemas import get_schema, list_schemas

# List all available schemas (including custom ones)
all_schemas = list_schemas()
print(all_schemas)  # ['pico', 'spider', 'my_custom_schema', ...]

# Get your custom schema
my_schema = get_schema("my_custom_schema")

# Use it in refinement
refiner = QueryRefiner(dimensions=my_schema)
result = refiner.refine("My query about...")
```

## Validation

The module validates custom schemas on load:

- **Required fields**: All required fields must be present
- **Placeholder validation**: `analysis_prompt` must include `{query}`
- **Type checking**: Fields must match expected types
- **Error logging**: Invalid dimensions are logged and skipped

## Troubleshooting

### Schema Not Loading

1. Check file location matches one of the search paths
2. Verify JSON syntax is valid (use a JSON validator)
3. Check application logs for error messages
4. Ensure file permissions allow reading

### Dimension Skipped

Check logs for validation errors:
- Missing required fields
- Invalid field types
- Missing `{query}` placeholder in prompt

### Schema Not Found

Use `list_schemas()` to see what's actually loaded:
```python
from query_refinement.schemas import list_schemas
print(list_schemas())
```

## Complete Example File

See `examples/custom_schemas.json` for a complete, working example with:
- Multiple schemas
- Various dimension types
- Different follow-up configurations
- Rich metadata
- Well-crafted prompts
- Complex multi-line analysis prompts

## Additional Resources

- [YAML Syntax Guide](https://yaml.org/spec/1.2/spec.html)
- [Online YAML Validator](https://www.yamllint.com/)
- [Prompt Engineering Guide](./prompt_engineering.md)
- [API Documentation](./api.md)
