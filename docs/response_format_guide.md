# Response Format Specification Guide

## Overview

The enhanced schema design allows you to **separate response format from analysis logic** in your prompts. This creates more maintainable, consistent, and testable refinement dimensions.

## The Problem

Previously, response format instructions were embedded directly in the prompt:

```yaml
analysis_prompt: |
  Analyze the query: {query}
  
  Consider temporal scope...
  
  Respond in JSON format:
  {
    "needs_refinement": true/false,
    "reason": "...",
    "suggested_question": "..."
  }
```

**Issues:**
- 🔴 Response format mixed with analysis logic
- 🔴 Inconsistent formats across dimensions
- 🔴 Hard to validate responses
- 🔴 Difficult to update format globally
- 🔴 Prompts become cluttered

## The Solution

Use the `response_format` field to specify expected responses **separately**:

```yaml
my_schema:
  - id: temporal_scope
    name: Temporal Scope
    description: Clarifies time period
    
    # Prompt focuses ONLY on analysis logic
    analysis_prompt: |
      Analyze temporal clarity in: {query}
      
      Check for:
      1. Specific time periods mentioned
      2. Ambiguous temporal terms
      3. Implied timeframes
      
      Determine if clarification is needed.
    
    # Response format specified separately
    response_format:
      type: json
      schema:
        needs_refinement: boolean
        reason: string
        suggested_question: string
      field_descriptions:
        needs_refinement: Whether this dimension needs clarification
        reason: Brief explanation of the analysis
        suggested_question: Question to ask user (null if not needed)
    
    allow_follow_up: true
    metadata:
      domain: general
```

## Benefits

✅ **Separation of Concerns**: Analysis logic separate from format  
✅ **Consistency**: All dimensions use the same response structure  
✅ **Validation**: Can validate LLM responses against schema  
✅ **Maintainability**: Update format in one place  
✅ **Clarity**: Cleaner, more focused prompts  
✅ **Type Safety**: Clear field types and requirements  
✅ **Documentation**: Field descriptions explain expected values  
✅ **Testability**: Easy to test format compliance  

## Response Format Structure

### Type: JSON (Recommended)

```yaml
response_format:
  type: json
  schema:
    # Define expected fields and example values
    needs_refinement: true
    reason: "string"
    suggested_question: "string"
    confidence: 0.85
    additional_data: {}
  
  # Optional: Describe each field
  field_descriptions:
    needs_refinement: "Boolean indicating if refinement is needed"
    reason: "Explanation of why refinement is/isn't needed"
    suggested_question: "Question for the user (null if not needed)"
    confidence: "Confidence score 0.0-1.0 (optional)"
    additional_data: "Any additional context (optional)"
```

**The system automatically generates** this instruction and appends it to your prompt:

```
Respond in the following format:

```json
{
  "needs_refinement": true,
  "reason": "string",
  "suggested_question": "string",
  "confidence": 0.85,
  "additional_data": {}
}
```

Field descriptions:
- needs_refinement: Boolean indicating if refinement is needed
- reason: Explanation of why refinement is/isn't needed
- suggested_question: Question for the user (null if not needed)
- confidence: Confidence score 0.0-1.0 (optional)
- additional_data: Any additional context (optional)
```

### Type: Structured

For more detailed field specifications:

```yaml
response_format:
  type: structured
  fields:
    - name: needs_refinement
      type: boolean
      required: true
      description: "Whether this dimension needs clarification"
    
    - name: reason
      type: string
      required: true
      description: "Explanation of the analysis"
    
    - name: suggested_question
      type: string
      required: false  # Optional field
      description: "Question to ask (null if no refinement needed)"
    
    - name: identified_terms
      type: list
      required: false
      description: "List of relevant terms found in query"
```

## Standard Response Format

We recommend using this **standard format** across all your dimensions:

```yaml
response_format:
  type: json
  schema:
    needs_refinement: boolean
    reason: string
    suggested_question: string or null
    confidence: number  # 0.0 to 1.0
  field_descriptions:
    needs_refinement: "Whether this dimension needs user clarification"
    reason: "Brief explanation of why refinement is or isn't needed"
    suggested_question: "Specific question to ask the user (null if needs_refinement is false)"
    confidence: "Confidence score for the analysis (0.0 = low, 1.0 = high)"
```

### Why This Format?

- **`needs_refinement`**: Clear boolean decision
- **`reason`**: Explains the analysis (useful for debugging)
- **`suggested_question`**: The actual refinement question
- **`confidence`**: Helps prioritize which dimensions to ask about first

## Extended Response Format

For more complex analyses, add domain-specific fields:

```yaml
response_format:
  type: json
  schema:
    needs_refinement: boolean
    reason: string
    suggested_question: string
    confidence: number
    
    # Domain-specific additions
    status: "CLEAR"  # or AMBIGUOUS, MISSING
    identified_terms: []
    suggested_options: []
    priority: "high"
  
  field_descriptions:
    needs_refinement: "Whether clarification is needed"
    reason: "Analysis explanation"
    suggested_question: "Question for the user"
    confidence: "Confidence score 0.0-1.0"
    status: "One of: CLEAR, AMBIGUOUS, MISSING"
    identified_terms: "Terms from query relevant to this dimension"
    suggested_options: "Options to present to the user"
    priority: "Priority level: low, medium, high, critical"
```

## Complete Example

Here's a complete dimension with response format:

```yaml
legal_research:
  - id: jurisdiction
    name: Jurisdiction
    description: Clarifies the legal jurisdiction
    
    # Focused analysis prompt (no format instructions)
    analysis_prompt: |
      Analyze jurisdiction in the legal query:
      
      Query: {query}
      
      **Check for:**
      1. Explicit jurisdiction mentions (federal, state, international)
      2. Implied jurisdiction from statute citations or court names
      3. Geographic references that indicate jurisdiction
      4. Ambiguous terms that could apply to multiple jurisdictions
      
      **Inference Rules:**
      - U.S.C. or C.F.R. citations → Federal jurisdiction
      - State names → State jurisdiction
      - "Supreme Court" without qualifier → Ask which one
      - International treaties → International law
      
      **Decision Logic:**
      - If jurisdiction is clear: needs_refinement = false
      - If ambiguous or missing: needs_refinement = true
      - Provide confidence based on inference strength
      
      **Question Generation:**
      - Be specific about why jurisdiction matters
      - Offer relevant options based on query context
      - Explain briefly if needed
    
    # Clean, separate response format
    response_format:
      type: json
      schema:
        needs_refinement: true
        reason: "string"
        suggested_question: "string"
        identified_jurisdiction: null
        jurisdiction_level: "unspecified"
        confidence: 0.7
      field_descriptions:
        needs_refinement: "Whether jurisdiction needs user clarification"
        reason: "Explanation of jurisdiction analysis"
        suggested_question: "Question about jurisdiction with context"
        identified_jurisdiction: "Jurisdiction inferred from query (if any)"
        jurisdiction_level: "One of: federal, state, local, international, unspecified"
        confidence: "Confidence in analysis (0.0-1.0)"
    
    allow_follow_up: true
    max_follow_ups: 2
    metadata:
      domain: legal
      priority: critical
      examples:
        - Which jurisdiction's law are you interested in?
        - Is this federal or state law?
```

## Using Response Format in Code

The `RefinementDimension` class automatically handles response format:

```python
from query_refinement.schemas import get_schema

# Load schema
schema = get_schema("my_schema")
dimension = schema[0]

# Get the complete prompt (includes response format)
full_prompt = dimension.get_full_prompt("What are the effects of aspirin?")

print(full_prompt)
# Output includes:
# 1. Your analysis prompt with {query} filled in
# 2. Automatically generated response format instructions
```

### Example Output:

```
Analyze temporal clarity in: What are the effects of aspirin?

Check for:
1. Specific time periods mentioned
2. Ambiguous temporal terms
3. Implied timeframes

Determine if clarification is needed.

Respond in the following format:

```json
{
  "needs_refinement": true,
  "reason": "string",
  "suggested_question": "string"
}
```

Field descriptions:
- needs_refinement: Whether this dimension needs clarification
- reason: Brief explanation of the analysis
- suggested_question: Question to ask user (null if not needed)
```

## Migration Guide

### Before (Embedded Format):

```yaml
analysis_prompt: |
  Analyze: {query}
  
  Check temporal scope...
  
  Respond in JSON:
  {
    "needs_refinement": true/false,
    "reason": "...",
    "question": "..."
  }
```

### After (Separate Format):

```yaml
analysis_prompt: |
  Analyze: {query}
  
  Check temporal scope...

response_format:
  type: json
  schema:
    needs_refinement: boolean
    reason: string
    question: string
  field_descriptions:
    needs_refinement: "Whether refinement needed"
    reason: "Analysis explanation"
    question: "Question for user"
```

## Best Practices

1. **Use Standard Format**: Adopt the recommended standard format for consistency
2. **Clear Field Names**: Use descriptive, consistent field names
3. **Document Fields**: Always include `field_descriptions`
4. **Optional Fields**: Mark optional fields in descriptions (e.g., "... (optional)")
5. **Type Hints**: Include example values showing expected types
6. **Keep It Simple**: Start with basic format, add fields only when needed
7. **Consistent Across Schema**: Use same format for all dimensions in a schema

## Validation

With structured response format, you can validate LLM responses:

```python
import json

def validate_response(response_text, expected_format):
    """Validate LLM response against expected format."""
    try:
        response = json.loads(response_text)
        schema = expected_format.get("schema", {})
        
        # Check required fields
        for field in schema:
            if field not in response:
                return False, f"Missing field: {field}"
        
        # Check types
        # ... type validation logic ...
        
        return True, "Valid"
    except json.JSONDecodeError:
        return False, "Invalid JSON"
```

## Examples

See `examples/custom_schemas_with_response_format.yaml` for complete working examples demonstrating:

- Standard JSON response format
- Extended response format with domain-specific fields
- Structured response format
- PICO schema with response formats
- Legal research schema with response formats

## Summary

The `response_format` field provides:

- **Better Structure**: Separation of analysis logic and output format
- **Consistency**: Uniform responses across all dimensions
- **Validation**: Machine-readable format specifications
- **Maintainability**: Update format without touching prompts
- **Clarity**: Cleaner, more focused prompts

This is the **recommended approach** for creating professional, maintainable refinement schemas.
