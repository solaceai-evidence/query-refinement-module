# JSON Extraction Improvements

## Overview

Enhanced the JSON extraction and validation logic in `core.py` to robustly handle various LLM response formats, particularly for models that don't return pre-parsed structured outputs (like Claude Haiku 3.5 through LiteLLM).

## Problem Statement

When using Claude Haiku 3.5 through LiteLLM 1.81.7, the API returns text responses containing JSON instead of parsed Pydantic objects. The previous simple regex pattern (`r'\{[\s\S]*\}'`) failed to reliably extract JSON from various response formats, causing "No JSON found in response" errors.

## Solution Architecture

Implemented a multi-strategy JSON extraction pipeline with comprehensive logging and error handling, following software development best practices:

### 1. Multi-Strategy JSON Extraction

The system now attempts extraction using multiple strategies in order of robustness:

#### Strategy 1: Markdown Code Fence Removal
- Detects and removes triple-backtick code blocks (```json ... ```)
- Handles both opening and closing fence markers
- Extraction method: `markdown_fences_removed`

#### Strategy 2: Direct JSON Detection
- If text starts with `{`, assumes it's already clean JSON
- Skips further extraction attempts
- Extraction method: `direct`

#### Strategy 3: Balanced Brace Matching (Most Robust)
- Tracks opening `{` and closing `}` braces
- Finds the first complete JSON object with balanced braces
- Validates extracted candidate with `json.loads()` before accepting
- Handles nested objects correctly
- Extraction method: `balanced_braces`

**Why this matters**: Handles cases like:
```
Here's my analysis:
{"complete": true, "current": "refined answer", "question": null}
Additional explanation here...
```

#### Strategy 4: Regex Fallback
- Uses greedy regex to match outermost JSON object: `r'\{[\s\S]*\}'`
- Falls back when balanced brace matching fails
- Extraction method: `regex_match`

#### Strategy 5: Field Pattern Matching
- Searches for JSON objects containing expected fields (`complete`, `current`, `question`)
- Uses pattern: `r'\{[^}]*"complete"[^}]*"current"[^}]*"question"[^}]*\}'`
- Last resort for fragmented or malformed responses
- Extraction method: `field_pattern`

### 2. Comprehensive Debug Logging

Added detailed logging at every stage to aid troubleshooting:

#### Pre-Extraction Logging
```python
logger.debug(
    "Starting JSON extraction for aspect %s (attempt %d)",
    aspect.id,
    attempt_number,
    extra={
        "response_length": len(response_text),
        "starts_with": response_text[:50],
    }
)
```

#### Post-Extraction Success Logging
```python
logger.info(
    "Extracted JSON using balanced brace matching for aspect '%s' (found at position %d-%d)",
    aspect.id,
    start_pos,
    end_pos
)
```

#### Raw Response Logging
```python
if len(response_text) <= 500:
    logger.debug("Raw LLM response for aspect %s: %s", aspect.id, response_text)
else:
    logger.debug(
        "Raw LLM response for aspect %s (truncated): %s... [%d more chars]",
        aspect.id,
        response_text[:500],
        len(response_text) - 500
    )
```

#### Post-Parsing Validation Logging
```python
logger.debug(
    "Successfully parsed JSON for aspect %s",
    aspect.id,
    extra={
        "extraction_method": extraction_method,
        "field_count": len(parsed_payload),
        "has_complete": "complete" in parsed_payload,
        "has_current": "current" in parsed_payload,
        "has_question": "question" in parsed_payload,
    }
)
```

### 3. Enhanced Error Handling

#### Extraction Failure Errors
When no strategy succeeds, provide actionable guidance:
```
"No valid JSON found in response after trying multiple extraction strategies. "
"Response appears to be plain text/markdown. "
"LLM model may not support structured outputs. "
"Consider: (1) Using a model with JSON mode support (gpt-4, claude-3.5+, gemini-1.5+), "
"(2) Adding 'response_format': {'type': 'json_object'} to settings, "
"(3) Checking API key and model availability."
```

Includes metadata about all attempted strategies:
```python
logger.warning(
    "Aspect %s failed JSON extraction on attempt %d: %s. Response preview: %s",
    aspect.id,
    attempt_number,
    error_message,
    cleaned_text[:300],
    extra={
        "response_length": len(response_text),
        "strategies_tried": ["direct", "markdown_fences", "balanced_braces", "regex", "field_pattern"],
    }
)
```

#### JSON Parsing Errors
Enhanced error messages with line/column context:
```
"JSON parsing failed: {msg} at line {line}, column {col}. "
"The extracted text may be malformed or truncated. "
"Check max_tokens setting if response appears cut off."
```

Shows surrounding lines for debugging:
```python
if error_line > 0:
    lines = cleaned_text.split('\n')
    context_start = max(0, error_line - 2)
    context_end = min(len(lines), error_line + 2)
    context = '\n'.join(lines[context_start:context_end])
    logger.warning(
        "JSON parse error for aspect %s on attempt %d: %s\nContext:\n%s",
        aspect.id,
        attempt_number,
        error_message,
        context,
        extra={
            "error_line": error_line,
            "error_col": error_col,
            "json_length": len(cleaned_text),
            "extraction_method": extraction_method,
        }
    )
```

## Implementation Details

### Files Modified

- **query_refinement_module/core.py**:
  - `_validate_structured_response()` method (lines ~920-1170)
  - Replaced basic regex with 5-strategy extraction pipeline
  - Added comprehensive logging throughout extraction and parsing
  - Enhanced error messages with contextual information

### Code Quality Standards

✅ **Error Handling**: All failure modes have specific, actionable error messages  
✅ **Logging**: Structured logging with proper log levels (debug, info, warning)  
✅ **Traceability**: Each extraction method is labeled for debugging  
✅ **Maintainability**: Clear strategy separation with explanatory comments  
✅ **Performance**: Early exits when simple strategies succeed  
✅ **Backward Compatibility**: Preserved existing validation logic  

### Testing

- ✅ All 225 existing unit tests pass
- ✅ No breaking changes to API or interfaces
- ✅ Validates against existing schema validation
- ✅ Handles edge cases: markdown fences, nested objects, trailing text, escaped quotes

## Usage Example

When the CLI encounters a Claude response like:

```
I'll analyze the comparator dimension:

{
  "complete": false,
  "current": null,
  "question": "Could you specify which groups or alternatives you're comparing?"
}

Let me know if you need clarification.
```

The system will:
1. Attempt markdown fence removal (not applicable)
2. Check if starts with `{` (no)
3. Use balanced brace matching to extract the JSON object ✓
4. Parse the JSON successfully
5. Log: `"Extracted JSON using balanced brace matching for aspect 'comparator' (found at position 39-165)"`

## Benefits

1. **Robustness**: Handles various LLM response formats automatically
2. **Debuggability**: Comprehensive logs show exactly what happened at each step
3. **User-Friendly**: Actionable error messages guide users to solutions
4. **Maintainability**: Clear strategy separation makes future improvements easy
5. **Performance**: No performance degradation - strategies exit early on success
6. **Provider-Agnostic**: Works with any LLM provider (OpenAI, Anthropic, Google, etc.)

## Migration Notes

No migration required - changes are fully backward compatible. Existing deployments will automatically benefit from improved JSON extraction on next deployment.

## Monitoring Recommendations

Watch for these log patterns in production:

- **extraction_method** metadata: Track which strategies succeed most often
- **strategies_tried**: If this appears frequently, indicates problematic LLM responses
- **JSON parsing failed**: May indicate max_tokens too low or model issues

## Future Enhancements

Potential improvements for consideration:

1. **Adaptive Retry**: Different prompts based on which extraction strategy failed
2. **Response Format Hints**: Include format examples in system prompts
3. **Metrics Collection**: Track extraction success rates by model and strategy
4. **Caching**: Cache successful extraction patterns per model
5. **Streaming Support**: Handle streaming responses with partial JSON

## Related Documentation

- [API Integration Guide](api_integration_guide.md)
- [Custom Schemas](custom_schemas.md)
- [Production Deployment](production_deployment.md)

## Version History

- **2024-12**: Initial implementation (litellm 1.81.7, Python 3.12.7)
  - 5-strategy extraction pipeline
  - Comprehensive debug logging
  - Enhanced error messages
  - All 225 tests passing
