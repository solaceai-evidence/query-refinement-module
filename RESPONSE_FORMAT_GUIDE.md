# Response Format Guide

## Overview

The `response_format` feature allows you to define **consistent, structured responses** for your refinement dimensions. It ensures that all dimensions return a standardized JSON structure while allowing domain-specific customization.

**All fields (base and custom) are automatically validated** to ensure type correctness and completeness.

## Base Response Structure

Every response **automatically includes** these three required fields:

```json
{
  "needs_refinement": true/false,
  "reason": "Brief explanation",
  "suggested_question": "Question to ask user"
}
```

These base fields are **always validated** and must be present in every response.

## Adding Custom Fields

You can add **domain-specific fields** using the `additional_fields` property:

```yaml
response_format:
  type: json
  additional_fields:
    custom_field_name: type
    another_field: type
  field_descriptions:
    custom_field_name: "Description of what this field contains"
    another_field: "Description of this field"
```

## Field Types

Supported types for fields (all automatically validated):

- `string`: Text values
- `boolean`: true/false (strict - won't accept 1/0)
- `integer`: Whole numbers (won't accept floats or booleans)
- `float`: Decimal numbers (accepts integers but not booleans)
- `array`: Lists of values
- `object`: Nested structures (dictionaries)

## Automatic Validation

The system provides **two levels of validation**:

### 1. Standard Validation (`validate_response`)

Checks that:
- All base fields are present (`needs_refinement`, `reason`, `suggested_question`)
- Base fields have correct types
- Custom fields (if present) have correct types
- Allows extra fields not defined in schema

```python
# Example usage
dimension = RefinementDimension(...)
response = {
    "needs_refinement": True,
    "reason": "Needs clarification",
    "suggested_question": "What time period?",
    "priority": "high"
}

is_valid, error = dimension.validate_response(response)
if not is_valid:
    print(f"Validation error: {error}")
```

### 2. Strict Validation (`validate_response_strict`)

Checks everything in standard validation plus:
- good: Warns about unexpected fields not defined in schema
- good: Returns list of warnings for review

```python
# Example usage
is_valid, error, warnings = dimension.validate_response_strict(response)
if not is_valid:
    print(f"Validation error: {error}")
if warnings:
    print(f"Warnings: {warnings}")
```

## Validation Examples

### good: Valid Response

```yaml
# Schema definition
response_format:
  type: json
  additional_fields:
    priority: string
    confidence: float
```

```json
// Valid response
{
  "needs_refinement": true,
  "reason": "Time period unclear",
  "suggested_question": "What time range?",
  "priority": "high",
  "confidence": 0.85
}
```

### bad: Invalid Responses

```json
// Missing base field
{
  "needs_refinement": true,
  "reason": "Time period unclear"
  // ERROR: Missing 'suggested_question'
}
```

```json
// Wrong type for base field
{
  "needs_refinement": "yes",  // ERROR: Must be boolean, not string
  "reason": "Time period unclear",
  "suggested_question": "What time range?"
}
```

```json
// Wrong type for custom field
{
  "needs_refinement": true,
  "reason": "Time period unclear",
  "suggested_question": "What time range?",
  "priority": "high",
  "confidence": "high"  // ERROR: Must be float, not string
}
```

```json
// Boolean disguised as number (rejected for integer/float)
{
  "needs_refinement": true,
  "reason": "Needs clarification",
  "suggested_question": "Clarify scope",
  "count": true  // ERROR: Must be integer, not boolean
}
```

### ⚠️ Warnings (Strict Mode Only)

```json
// Extra field not in schema
{
  "needs_refinement": true,
  "reason": "Time period unclear",
  "suggested_question": "What time range?",
  "priority": "high",
  "extra_field": "something"  // WARNING: Unexpected field
}
```

## Examples by Complexity

### Level 1: Basic (Base Fields Only)

No `response_format` needed - uses defaults:

```yaml
- id: simple_dimension
  name: Simple Check
  description: Basic yes/no check
  analysis_prompt: |
    Check if the query mentions time period: {query}
```

**Validation:** Only base fields validated.

Response will be:
```json
{
  "needs_refinement": false,
  "reason": "Query includes specific dates",
  "suggested_question": ""
}
```

### Level 2: Simple Addition (1-2 Custom Fields)

Add a priority or confidence score:

```yaml
- id: temporal_scope
  name: Temporal Scope
  description: Time period clarification
  analysis_prompt: |
    Analyze temporal clarity: {query}
  
  response_format:
    type: json
    additional_fields:
      priority: string
    field_descriptions:
      priority: "Urgency level: high, medium, low"
```

**Validation:** Base fields + `priority` (must be string).

Response will be:
```json
{
  "needs_refinement": true,
  "reason": "Time period is ambiguous",
  "suggested_question": "What time period are you interested in?",
  "priority": "high"
}
```

### Level 3: Moderate (3-5 Custom Fields)

Add multiple context-specific fields:

```yaml
- id: geographic_scope
  name: Geographic Scope
  description: Location clarification
  analysis_prompt: |
    Analyze geographic clarity: {query}
  
  response_format:
    type: json
    additional_fields:
      priority: string
      detected_locations: array
      scope_level: string
    field_descriptions:
      priority: "Urgency: high, medium, low"
      detected_locations: "Locations found in query"
      scope_level: "Geographic level: global, national, regional, local"
```

**Validation:** Base fields + `priority` (string), `detected_locations` (array), `scope_level` (string).

Response will be:
```json
{
  "needs_refinement": true,
  "reason": "Location mentioned but scope unclear",
  "suggested_question": "Are you interested in city-level or national-level data?",
  "priority": "medium",
  "detected_locations": ["United States"],
  "scope_level": "national"
}
```

### Level 4: Advanced (6+ Custom Fields)

Full domain-specific analysis:

```yaml
- id: study_design
  name: Study Design
  description: Research methodology
  analysis_prompt: |
    Analyze methodology: {query}
  
  response_format:
    type: json
    additional_fields:
      confidence_score: float
      detected_methodologies: array
      recommended_methodologies: array
      complexity_level: string
      data_type_requirements: array
      sample_size_mentioned: boolean
    field_descriptions:
      confidence_score: "Confidence 0.0-1.0"
      detected_methodologies: "Methodologies found"
      recommended_methodologies: "Suggested methods"
      complexity_level: "simple/moderate/complex"
      data_type_requirements: "Required data types"
      sample_size_mentioned: "Was sample size specified?"
```

**Validation:** All fields validated with correct types (float, array, string, boolean).

Response will be:
```json
{
  "needs_refinement": true,
  "reason": "Methodology not specified, multiple approaches possible",
  "suggested_question": "What research methodology: RCT, cohort study, or meta-analysis?",
  "confidence_score": 0.7,
  "detected_methodologies": [],
  "recommended_methodologies": ["RCT", "cohort study"],
  "complexity_level": "moderate",
  "data_type_requirements": ["quantitative", "clinical outcomes"],
  "sample_size_mentioned": false
}
```

## Type Validation Details

### String Validation
```python
good: "hello"
good: ""
good: "123"
bad: 123        # number
bad: true       # boolean
bad: ["text"]   # array
```

### Boolean Validation (Strict)
```python
good: true
good: false
bad: "true"     # string
bad: 1          # number (even though Python treats bool as int subclass)
bad: 0          # number
```

### Integer Validation
```python
good: 42
good: 0
good: -10
bad: 42.5       # float
bad: "42"       # string
bad: true       # boolean (rejected even though bool is int subclass)
```

### Float Validation
```python
good: 42.5
good: 0.0
good: -10.5
good: 42         # integers accepted for float fields
bad: "42.5"     # string
bad: true       # boolean (explicitly rejected)
```

### Array Validation
```python
good: []
good: ["item1", "item2"]
good: [1, 2, 3]
bad: "[]"       # string
bad: {}         # object
```

### Object Validation
```python
good: {}
good: {"key": "value"}
good: {"nested": {"data": 123}}
bad: "{}"       # string
bad: []         # array
```

## Best Practices

### 1. Keep It Consistent Across Your Schema

If you add `priority` to one dimension, consider adding it to all dimensions in that schema:

```yaml
my_schema:
  - id: dimension_1
    response_format:
      additional_fields:
        priority: string
        confidence: float
  
  - id: dimension_2
    response_format:
      additional_fields:
        priority: string
        confidence: float
```

### 2. Use Meaningful Field Names

Good:
- `detected_methodologies`
- `confidence_score`
- `recommended_options`

Avoid:
- `data`
- `info`
- `field1`

### 3. Document Your Fields

Always provide `field_descriptions`:

```yaml
field_descriptions:
  confidence_score: "Confidence in the analysis (0.0 = low, 1.0 = high)"
  detected_items: "Items explicitly mentioned in the query"
```

### 4. Choose Appropriate Types

```yaml
# Use specific types
priority: string              # "high", "medium", "low"
confidence: float             # 0.0 to 1.0
count: integer               # whole numbers
items: array                 # lists
is_valid: boolean            # true/false (strict)
details: object              # nested structure
```

### 5. Test Your Schemas

Always test with sample responses:

```python
from src.schemas import get_schema, RefinementDimension

# Load your schema
schema = get_schema("my_schema")
dimension = schema[0]

# Test with sample response
test_response = {
    "needs_refinement": True,
    "reason": "Test reason",
    "suggested_question": "Test question?",
    "priority": "high",
    "confidence": 0.8
}

# Validate
is_valid, error = dimension.validate_response(test_response)
print(f"Valid: {is_valid}")
if not is_valid:
    print(f"Error: {error}")

# Strict validation
is_valid, error, warnings = dimension.validate_response_strict(test_response)
if warnings:
    print(f"Warnings: {warnings}")
```

## Common Patterns

### Pattern 1: Confidence Scoring

```yaml
additional_fields:
  confidence_score: float
field_descriptions:
  confidence_score: "Analysis confidence (0.0-1.0)"
```

**Validation:** Must be float (integers accepted, but booleans rejected).

### Pattern 2: Priority Levels

```yaml
additional_fields:
  priority: string
field_descriptions:
  priority: "Refinement urgency: critical, high, medium, low"
```

**Validation:** Must be string.

### Pattern 3: Detection + Recommendation

```yaml
additional_fields:
  detected_items: array
  recommended_items: array
field_descriptions:
  detected_items: "Items found in the query"
  recommended_items: "Suggested items based on context"
```

**Validation:** Both must be arrays (lists).

### Pattern 4: Multi-Dimensional Assessment

```yaml
additional_fields:
  completeness_score: float
  clarity_score: float
  specificity_score: float
  overall_quality: string
field_descriptions:
  completeness_score: "How complete the query is (0.0-1.0)"
  clarity_score: "How clear the query is (0.0-1.0)"
  specificity_score: "How specific the query is (0.0-1.0)"
  overall_quality: "Overall assessment: excellent, good, fair, poor"
```

**Validation:** Three floats + one string, all type-checked.

## Error Handling

When validation fails, you'll get clear error messages:

```python
# Missing field error
"Missing required base fields: suggested_question"

# Type mismatch errors
"'needs_refinement' must be a boolean"
"Field 'priority' must be string (got integer)"
"Field 'confidence' must be float (got boolean)"

# Multiple errors combined
"'needs_refinement' must be a boolean; Field 'priority' must be string (got integer)"
```

## Migration from Inline Format

### Before (format in prompt):
```yaml
analysis_prompt: |
  Analyze: {query}
  
  Respond in JSON:
  {
    "needs_refinement": true/false,
    "reason": "explanation",
    "suggested_question": "question",
    "priority": "high/medium/low"
  }
```

### After (separate response_format):
```yaml
analysis_prompt: |
  Analyze: {query}

response_format:
  type: json
  additional_fields:
    priority: string
  field_descriptions:
    priority: "Urgency: high, medium, low"
```
