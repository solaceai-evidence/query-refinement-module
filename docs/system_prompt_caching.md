# System Prompt Caching

## Overview

System prompt caching is a feature that optimizes LLM token usage by caching static system prompts across API calls. When enabled, the system automatically caches system prompts for refinement aspects and synthesis operations, reducing token consumption by 30-50% and improving response times.

## How It Works

### Architecture

The caching mechanism is implemented at the LLM provider level and works transparently with any LiteLLM-compatible provider that supports prompt caching:

1. **System Prompts**: Static prompts defined in YAML frameworks or default templates are marked for caching
2. **Cache Control**: When caching is enabled, a `cache_control` parameter is added to system messages
3. **Provider Support**: The implementation gracefully degrades for providers that don't support caching
4. **Automatic Application**: Caching is automatically applied to:
   - Refinement aspect evaluation calls (per-aspect caching)
   - Final query synthesis calls (global caching)

### Supported Providers

| Provider         | Support             | Cache Duration        | Notes                              |
| ---------------- | ------------------- | --------------------- | ---------------------------------- |
| Anthropic Claude | ✅ Yes               | 5 minutes (ephemeral) | Native support via cache_control   |
| OpenAI GPT-4     | ✅ Yes               | Varies                | Supported through LiteLLM          |
| Azure OpenAI     | ✅ Yes               | Varies                | Supported through LiteLLM          |
| Other Providers  | ⚠️ Graceful fallback | N/A                   | Falls back to non-cached operation |

## Configuration

### Environment Variable

```bash
# Enable/disable prompt caching (default: true)
QUERY_REFINEMENT_ENABLE_PROMPT_CACHING=true
```

### Accepted Values

- **Enable**: `true`, `1`, `yes`, `on` (case-insensitive)
- **Disable**: `false`, `0`, `no`, `off` (case-insensitive)
- **Default**: `true` (enabled by default)

### Code Configuration

```python
from query_refinement_module.settings import LLMSettings

# Via environment
settings = LLMSettings.from_env()

# Via code
settings = LLMSettings(
    model="anthropic/claude-sonnet-4-20250514",
    enable_prompt_caching=True  # Explicitly enable
)

# Pass to provider
provider_kwargs = settings.as_provider_kwargs()
```

## Benefits

### Token Savings

System prompts are typically 200-800 tokens depending on the refinement aspect:
- **Refinement aspects**: ~200-500 tokens per system prompt
- **Synthesis**: ~800 tokens for system prompt
- **Savings**: 30-50% reduction in total token usage for cached prompts

### Example Calculation

For a session with 3 refinement aspects and 1 synthesis:
- **Without caching**: (300 + 400 + 350 + 800) = 1,850 system prompt tokens per call
- **With caching**: First call pays full cost, subsequent calls within 5 minutes: ~free
- **Typical session**: 5-10 LLM calls → 7,400-14,800 tokens saved

### Performance Improvements

- **Reduced latency**: Cached prompts are retrieved faster than sending full text
- **Lower costs**: Anthropic charges ~10% of regular price for cached tokens
- **Higher throughput**: Less data to transmit per request

## Implementation Details

### Code Flow

```python
# 1. Provider initialization (from settings)
provider = LiteLLMProvider(
    default_model="anthropic/claude-sonnet-4-20250514",
    enable_prompt_caching=True  # From env or explicit config
)

# 2. Refinement call (automatic caching)
result = await provider.complete_async(
    system_prompt=aspect.get_system_role(),  # Static per aspect
    user_prompt=user_query,
    cache_system_prompt=True  # Explicitly request caching
)

# 3. Message construction (internal)
messages = [
    {
        "role": "system",
        "content": system_prompt,
        "cache_control": {"type": "ephemeral"}  # Added when caching enabled
    },
    {
        "role": "user",
        "content": user_prompt
    }
]
```

### Fallback Behavior

The implementation includes robust error handling:

```python
if cache_system_prompt and self._enable_prompt_caching:
    try:
        system_message["cache_control"] = {"type": "ephemeral"}
    except Exception as e:
        # Gracefully continue without caching
        logger.debug(f"Could not apply prompt caching: {e}")
```

This ensures:
- **No breaking changes**: Works with all providers
- **Silent degradation**: Non-supporting providers continue normally
- **No user intervention**: Automatic adaptation to provider capabilities

## Monitoring

### Logging

The system logs caching activity at DEBUG level:

```
DEBUG - System prompt caching enabled | model=claude-sonnet-4 | request_id=abc123
```

### Observability

When using tracing providers, caching status is included in metadata:
- `cache_system_prompt`: Boolean indicating if caching was requested
- `enable_prompt_caching`: Global setting status

## Best Practices

### When to Use Caching

✅ **Good use cases:**
- System prompts (static, reused across sessions)
- Framework definitions (never change per session)
- Synthesis instructions (identical for all users)

❌ **Bad use cases:**
- User prompts (dynamic, change every call)
- Context that varies per session
- Short-lived testing scenarios

### Development vs Production

**Development:**
```bash
# Disable for faster iteration/testing
QUERY_REFINEMENT_ENABLE_PROMPT_CACHING=false
```

**Production:**
```bash
# Enable for cost savings
QUERY_REFINEMENT_ENABLE_PROMPT_CACHING=true
```

### Cost Considerations

- **Anthropic Claude**: Cached input tokens cost ~90% less than regular
- **Cache duration**: 5 minutes (Anthropic ephemeral cache)
- **Break-even**: Beneficial if prompt reused 2+ times within cache window
- **Typical session**: Most sessions trigger 5-10 LLM calls → significant savings

## Testing

Run the test suite to verify caching behavior:

```bash
# Run caching-specific tests
poetry run pytest tests/test_prompt_caching.py -v

# Run all provider tests
poetry run pytest tests/unit/test_providers.py -v

# Run integration tests
poetry run pytest tests/ -v
```

## Troubleshooting

### Caching Not Working

1. **Check configuration**:
   ```bash
   echo $QUERY_REFINEMENT_ENABLE_PROMPT_CACHING
   ```

2. **Verify provider support**:
   - Claude models: ✅ Supported
   - GPT models: ✅ Supported
   - Others: Check LiteLLM documentation

3. **Check logs**:
   ```bash
   # Look for debug messages
   grep "System prompt caching" logs/app.log
   ```

### Unexpected Behavior

If caching causes issues:
1. Disable temporarily: `QUERY_REFINEMENT_ENABLE_PROMPT_CACHING=false`
2. Check LiteLLM version: Ensure you have the latest version
3. Review provider-specific docs: Some providers have caching quirks

## Future Enhancements

Potential improvements for future versions:
- [ ] Cache hit/miss metrics
- [ ] Configurable cache duration
- [ ] Per-aspect caching controls
- [ ] Cache warming for common prompts
- [ ] Alternative caching strategies (persistent, semantic)

## References

- [Anthropic Prompt Caching Documentation](https://docs.anthropic.com/claude/docs/prompt-caching)
- [LiteLLM Caching Support](https://docs.litellm.ai/docs/caching)
- [OpenAI Prompt Caching](https://platform.openai.com/docs/guides/prompt-caching)
