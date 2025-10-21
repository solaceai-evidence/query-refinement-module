# Custom Schema Guide

This guide explains how to create custom refinement schemas using YAML configuration files.

## Overview

The query refinement module uses custom schemas defined in YAML format. This enables you to:

- Define domain-specific refinement dimensions
- Customize the refinement process for your use case
- Share schemas across teams without code changes
- Create reusable templates for different research domains
- Maintain clear, readable prompt engineering

## Quick Start

1. Create a YAML file with your custom schemas (e.g., `custom_schemas.yaml`)
2. Set the `CUSTOM_SCHEMAS_PATH` environment variable to point to your file:
   ```bash
   export CUSTOM_SCHEMAS_PATH=/path/to/your/custom_schemas.yaml
   ```
3. Define your schemas following the `RefinementDimension` format below

## Prerequisites

Custom schemas require PyYAML:

```bash
pip install pyyaml
```

## Schema File Format

Custom schemas are defined in YAML format. Each top-level key is a schema name, and each value is a list of `RefinementDimension` objects.

**Basic structure:**

```yaml
schema_name:
  - id: dimension_id
    name: Dimension Name
    description: Description of what this dimension refines
    analysis_prompt: |
      Multi-line prompt template with {query} placeholder.
      
      Use the pipe (|) character for multi-line strings.
      No escaping needed for special characters!
    
    # Optional: Define response format for structured outputs
    response_format:
      additional_fields:
        field_name: field_type  # e.g., priority: string, confidence: float
      field_descriptions:
        field_name: "Description of what this field contains"
    
    allow_follow_up: false
    max_follow_ups: 2
    metadata:
      domain: general
      priority: high
```

### Required Fields

Every dimension must have:

- **`id`** (string): Unique identifier for the dimension within the schema
- **`name`** (string): Human-readable name for the dimension
- **`description`** (string): Brief description of what this dimension refines
- **`analysis_prompt`** (string): Template for analyzing if this dimension needs refinement
  - **Must include `{query}` placeholder** where the user's query will be inserted
  - Should guide the LLM on how to analyze and what to ask
  - Use `|` for multi-line prompts (highly recommended for readability)

### Optional Fields

- **`response_format`** (object): Defines expected response structure
  - `additional_fields`: Dict mapping field names to types (string, boolean, integer, float, array, object)
  - `field_descriptions`: Dict providing descriptions for custom fields
  - Base fields (needs_refinement, reason, suggested_question) are always included automatically
  
- **`allow_follow_up`** (boolean, default: `false`): Whether this dimension supports follow-up questions

- **`max_follow_ups`** (integer, default: `2`): Maximum number of follow-up rounds if enabled

- **`metadata`** (object, default: `{}`): Additional metadata for extensibility
  - Common fields: `domain`, `priority`, `framework`, `examples`, `medical_specialty`

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

## Setting Up Custom Schemas

### Environment Variable (Required)

You **must** set the `CUSTOM_SCHEMAS_PATH` environment variable to point to your YAML schema file:

**Linux/macOS:**
```bash
export CUSTOM_SCHEMAS_PATH=/path/to/your/custom_schemas.yaml
```

**Windows (PowerShell):**
```powershell
$env:CUSTOM_SCHEMAS_PATH="C:\path\to\your\custom_schemas.yaml"
```

**Using a `.env` file:**
```env
CUSTOM_SCHEMAS_PATH=/path/to/your/custom_schemas.yaml
```

**Important:** The path must point to a **file**, not a directory. The module will only load schemas from this single file.

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


## Designing Effective Dimensions: When to Split vs. Combine

### The Subdimension Strategy

When designing schemas, you may face the question: should a broad concept be one dimension or split into multiple subdimensions?

**Example:** In the PICO framework, "Population" could be:
- **Option A**: One comprehensive dimension covering all population aspects
- **Option B**: Multiple focused subdimensions (Demographics, Clinical Condition, Comorbidities, Eligibility Criteria, Special Populations)

### Benefits of Splitting into Subdimensions

Splitting a high-level dimension into focused subdimensions provides several advantages:

1. **More Focused Prompts**
   - Each subdimension has a clearer, more specific task
   - Easier for the LLM to analyze one aspect deeply without getting overwhelmed
   - Reduces cognitive load and improves response quality

2. **Better Granularity and Control**
   - Users can be asked about demographics separately from clinical characteristics
   - Different follow-up strategies for each subdimension
   - Some aspects may not need refinement while others do
   - Skip irrelevant subdimensions entirely (e.g., "Special Populations" may not apply to all studies)

3. **Improved Validation and Tracking**
   - Custom response fields more relevant to each subdimension
   - Easier to track which specific aspect needs clarification
   - Better metrics (e.g., "age_clarity_score" vs. generic "population_score")
   - More actionable analytics on where queries commonly need refinement

4. **Flexible Workflows**
   - Process subdimensions in a logical order (demographics first, then clinical details)
   - Parallel processing of independent subdimensions
   - Better alignment with how domain experts actually think about the problem

5. **Cleaner Maintenance**
   - Easier to update one focused prompt than one massive prompt
   - Each subdimension can have specific priority levels
   - More precise metadata and domain expert assignments

### When to Split

Consider splitting when:
- ✅ The dimension covers multiple distinct categories
- ✅ Each subdimension has its own set of considerations and edge cases
- ✅ Users may need different levels of detail for different aspects
- ✅ The prompt becomes too long (>100 lines) or complex
- ✅ Different subdimensions have different follow-up needs

### When to Keep Combined

Keep dimensions combined when:
- ✅ The aspects are highly interconnected and can't be considered separately
- ✅ Splitting would create artificial boundaries
- ✅ The dimension is already focused and specific
- ✅ Users need to consider all aspects together to make sense

### Implementation Example

```yaml
# Instead of one large "population" dimension:
pico_clinical:
  - id: population_demographics
    name: Demographics
    # Focused prompt on age, gender, ethnicity...
    metadata:
      subdimension: Demographics
      typical_order: 1
  
  - id: population_clinical_condition
    name: Clinical Condition
    # Focused prompt on diagnosis, disease stage...
    metadata:
      subdimension: Clinical_Condition
      typical_order: 2
  
  # More subdimensions...
```

See `examples/pico_template.yaml` for a complete subdimension example.

## Using Custom Schemas in Code

Once defined, your custom schemas are automatically loaded when the module initializes:

```python
from query_refinement.schemas import get_schema, list_schemas

# List all available schemas
all_schemas = list_schemas()
print(all_schemas)  # ['my_custom_schema', 'pico_clinical', ...]

# Get your custom schema
my_schema = get_schema("my_custom_schema")

# Use it in refinement
refiner = QueryRefiner(dimensions=my_schema)
result = refiner.refine("My query about...")
```

## Validation

The module validates custom schemas on load:

- **Required fields**: All required fields (`id`, `name`, `description`, `analysis_prompt`) must be present
- **Placeholder validation**: `analysis_prompt` must include `{query}` placeholder
- **Response format validation**: If `response_format` is provided:
  - `additional_fields` types must be valid (string, boolean, integer, float, array, object)
  - Field descriptions are checked for consistency
- **Type checking**: Fields must match expected types
- **Error logging**: Invalid dimensions are logged and skipped

If a dimension fails validation, it will be logged and skipped, but other valid dimensions will still load.

## Troubleshooting

### Schema Not Loading

If your schema doesn't appear in `list_schemas()`:

1. **Check environment variable**: Ensure `CUSTOM_SCHEMAS_PATH` is set correctly
2. **Verify file path**: The path must point to an existing **file**, not a directory
3. **YAML syntax**: Validate your YAML syntax using an online validator
4. **File permissions**: Ensure the file is readable
5. **PyYAML installed**: Run `pip install pyyaml`
6. **Check logs**: Look for error messages in application logs

### YAML Syntax Errors

Common YAML issues:

- **Indentation**: Use spaces (not tabs); be consistent (2 or 4 spaces)
- **Missing colons**: Keys need `:` after them
- **List items**: Must start with `- ` (dash and space)
- **Quotes**: Usually not needed, but use for strings with special chars

Use an online YAML validator to check syntax.

### Dimension Skipped

If a dimension is skipped during loading, check logs for:

- Missing required fields (`id`, `name`, `description`, `analysis_prompt`)
- Invalid field types
- Missing `{query}` placeholder in `analysis_prompt`
- Invalid response format field types

### Schema Not Found at Runtime

If you get "Unknown schema" errors:

```python
from query_refinement.schemas import list_schemas
print(list_schemas())  # See what's actually loaded
```

Make sure the schema name you're requesting matches exactly (case-sensitive).

## Complete Example Files

See the `examples/` directory for complete, working examples:

- **`custom_schemas.yaml`**: Multiple schemas demonstrating various patterns
- **`pico_template.yaml`**: Comprehensive PICO framework with best practices
- **`custom_schemas_with_response_format.yaml`**: Examples using response_format feature

Each example demonstrates:

- Proper prompt engineering
- Multiple dimensions per schema
- Different priority levels
- Domain-specific considerations
- Follow-up configurations
- Response format specifications

## Additional Resources

- [YAML Syntax Guide](https://yaml.org/spec/1.2/spec.html)
- [Online YAML Validator](https://www.yamllint.com/)
- [Response Format Guide](./response_format_guide.md)
- [YAML Reference](../YAML_REFERENCE.md)
