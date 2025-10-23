# Custom Schemas Quick Reference

## File Format

**File name:** `custom_schemas.yaml` or `custom_schemas.yml`

**Location (in order of priority):**
1. `$CUSTOM_SCHEMAS_PATH` (env variable)
2. `./custom_schemas.yaml` (current directory)
3. `~/.query_refinement/custom_schemas.yaml` (home directory)

## Minimal Example

```yaml
my_schema:
  - id: my_dimension
    name: My Dimension
    description: Brief description
    analysis_prompt: |
      Analyze: {query}
      
      Ask if needs refinement.
```

## Full Example

```yaml
schema_name:
  - id: dimension_id                    # Required: unique ID
    name: Dimension Name                # Required: display name
    description: What this refines      # Required: brief description
    
    depends_on: []                      # Optional: list of dimension IDs this depends on
                                        # Default: [] (no dependencies)
                                        # Example: [population, intervention]
    
    analysis_prompt: |                  # Required: must include {query}
      Analyze the query: {query}
      
      Consider:
      1. First point
      2. Second point
      
      Respond in JSON:
      {
        "needs_refinement": true/false,
        "suggested_question": "..."
      }
    allow_follow_up: true              # Optional: default false
    max_follow_ups: 2                  # Optional: default 2
    metadata:                          # Optional: any data
      domain: your_domain
      priority: high
      examples:
        - Example 1
        - Example 2
```

## YAML Quick Tips

### Multi-line Strings

```yaml
# Literal block (preserves newlines)
prompt: |
  Line 1
  Line 2
  Line 3

# Folded block (joins lines)
description: >
  This long description
  will be a single line.
```

### Lists

```yaml
# Inline
examples: [item1, item2, item3]

# Block
examples:
  - item1
  - item2
  - item3
```

### Nested Objects

```yaml
metadata:
  domain: research
  priority: high
  tags:
    - tag1
    - tag2
  config:
    option1: value1
    option2: value2
```

### Special Characters

No escaping needed! All work naturally:

```yaml
text: |
  Use "quotes" freely
  Include {placeholders}
  Special chars: @#$%^&*()
  Paths: C:\Users\file.txt
```

### Comments

```yaml
# This is a comment
schema_name:  # Inline comment
  - id: dim1  # Another comment
```

## Common Patterns

### JSON Response Format

```yaml
analysis_prompt: |
  Analyze: {query}
  
  Respond in JSON:
  {
    "needs_refinement": true/false,
    "reason": "explanation",
    "suggested_question": "question"
  }
```

### With Examples

```yaml
analysis_prompt: |
  Analyze: {query}
  
  Examples:
  - Good: "Effect of X on Y in population Z"
  - Bad: "Effect of X on Y"
  - Edge case: "Effect of X" (too vague)
  
  Ask if clarification needed.
```

### Conditional Logic in Prompt

```yaml
analysis_prompt: |
  Analyze: {query}
  
  If query mentions:
  - Time period → No refinement needed
  - "Recent" → Ask for specific timeframe
  - Nothing → Ask about temporal scope
  
  Be specific in your question.
```

## Requirements

```bash
pip install pyyaml
```

## Usage in Code

```python
from query_refinement.schemas import get_schema, list_schemas

# List all schemas
all_schemas = list_schemas()

# Get specific schema
my_schema = get_schema("schema_name")

# Use in refinement
refiner = QueryRefiner(dimensions=my_schema)
```

## Validation Errors

If a dimension is skipped, check:

- ✅ All required fields present (`id`, `name`, `description`, `analysis_prompt`)
- ✅ `{query}` placeholder in `analysis_prompt`
- ✅ Valid YAML syntax (proper indentation)
- ✅ Correct data types (booleans are `true/false`, not `True/False`)

## Troubleshooting

**Schema not loading?**
```bash
# Check file exists
ls -la custom_schemas.yaml

# Validate YAML syntax online
# https://www.yamllint.com/

# Check logs for errors
# (Look for "Loading custom schemas from..." messages)
```

**Wrong indentation?**
- Use spaces, not tabs
- Be consistent (2 or 4 spaces)
- Lists items need `-` with space

**YAML vs Python booleans:**
```yaml
# ✅ Correct
allow_follow_up: true
allow_follow_up: false

# ❌ Wrong
allow_follow_up: True   # Python syntax
allow_follow_up: FALSE  # All caps
```

## Examples

See `examples/custom_schemas.yaml` for complete working examples.

## Documentation

- Full guide: `docs/custom_schemas.md`
- Migration from JSON: `MIGRATION.md`
- README: `README.md`
