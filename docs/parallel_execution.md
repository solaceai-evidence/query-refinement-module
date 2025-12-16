# Parallel Execution Guide

This guide explains how to configure and use parallel processing for query refinement, including rate limiting, dependency management, and performance optimization.

## Overview

The query refinement system can process multiple refinement aspects simultaneously when they have no dependencies on each other. This parallel execution capability significantly improves performance for frameworks with many independent dimensions while maintaining correctness through automatic dependency resolution.

### Key Benefits

- **Faster Processing**: Independent aspects are analyzed at the same time rather than one after another
- **Automatic Optimization**: The system determines the best execution order based on dependencies
- **Built-in Safety**: Rate limiting prevents exceeding API provider quotas
- **Concurrent Access Protection**: Session storage includes safeguards against data corruption
- **Graceful Degradation**: Automatically falls back to sequential processing when needed

## How Parallel Execution Works

### Dependency Analysis

When parallel execution is enabled, the system analyzes the refinement framework to understand which aspects depend on others. It then organizes aspects into levels:

**Level 0**: Aspects with no dependencies. These can all run at the same time.

**Level 1**: Aspects that depend only on Level 0 aspects. These wait for Level 0 to complete, then run simultaneously.

**Level 2 and beyond**: Each level depends on previous levels and waits for them to finish before starting.

### Example Framework

Consider a medical research framework:

```yaml
medical_research:
  - id: population
    name: Population
    refinement_instructions: "What population is being studied?"
  
  - id: intervention
    name: Intervention
    refinement_instructions: "What intervention is being tested?"
  
  - id: comparison
    name: Comparison
    refinement_instructions: "What is the comparison group?"
    depends_on: [population]
  
  - id: outcome
    name: Outcome
    refinement_instructions: "What outcomes are measured?"
    depends_on: [population, intervention, comparison]
```

**Execution Order:**

- **Level 0** (parallel): `population` and `intervention` run simultaneously
- **Level 1** (after Level 0): `comparison` runs once `population` completes
- **Level 2** (after Level 1): `outcome` runs once all dependencies are ready

This approach ensures each aspect has access to the information it needs while maximizing parallel processing.

## Configuration

### CLI Configuration

The command-line interface supports parallel execution through flags and environment variables.

**Using command-line flags:**

```bash
# Enable parallel execution
poetry run query-refine --framework pico_advanced --parallel

# Disable parallel execution (use sequential processing)
poetry run query-refine --framework pico_advanced --no-parallel
```

**Using environment variable:**

```bash
# Set default mode
export QUERY_REFINEMENT_PARALLEL_MODE=true
poetry run query-refine --framework pico_advanced
```

The command-line flag takes precedence over the environment variable. When parallel mode is active, the CLI displays the configuration at startup:

```text
[Parallel Mode] max_concurrent=8, rate_limiter=enabled
```

### API Configuration

The API service reads parallel execution settings from environment variables. Add these to your `.env` file:

```env
# Enable parallel execution for API requests
PARALLEL_EXECUTION_ENABLED=true

# Concurrency limits
PARALLEL_MAX_CONCURRENT=8
RATE_LIMIT_MAX_CONCURRENT_REQUESTS=10

# Rate limits
RATE_LIMIT_REQUESTS_PER_MINUTE=60
RATE_LIMIT_TOKENS_PER_MINUTE=90000

# Advanced settings (optional)
RATE_LIMIT_ADAPTIVE_BACKOFF=true
RATE_LIMIT_ADAPTIVE_DECREASE_FACTOR=0.8
RATE_LIMIT_ADAPTIVE_INCREASE_FACTOR=1.05
```

### Configuration Parameters

**Parallel Execution:**

- `PARALLEL_EXECUTION_ENABLED` (boolean): Turn parallel processing on or off. Default: `false`
- `PARALLEL_MAX_CONCURRENT` (integer): Maximum aspects to process at once. Default: `8`

**Rate Limiting:**

- `RATE_LIMIT_REQUESTS_PER_MINUTE` (integer): Maximum API calls per minute. Default: `60`
- `RATE_LIMIT_TOKENS_PER_MINUTE` (integer): Maximum tokens per minute. Default: `90000`
- `RATE_LIMIT_MAX_CONCURRENT_REQUESTS` (integer): Maximum concurrent requests. Default: `10`

**Adaptive Rate Limiting (Advanced):**

- `RATE_LIMIT_ADAPTIVE_BACKOFF` (boolean): Automatically adjust limits based on errors. Default: `false`
- `RATE_LIMIT_ADAPTIVE_DECREASE_FACTOR` (float): Reduce limits by this factor on rate limit errors. Default: `0.8`
- `RATE_LIMIT_ADAPTIVE_INCREASE_FACTOR` (float): Gradually increase limits during recovery. Default: `1.05`

## Rate Limiting

### Why Rate Limiting Matters

API providers impose limits on how many requests you can make. Exceeding these limits results in errors that slow down your application. The built-in rate limiter helps you stay within these boundaries.

### How Rate Limiting Works

The system tracks three types of limits:

1. **Request Rate**: Number of API calls per minute
2. **Token Usage**: Total tokens consumed per minute
3. **Concurrent Requests**: How many requests can run at the same time

Before making an API call, the system checks if doing so would exceed any limit. If a limit would be exceeded, the request waits until capacity is available.

### Setting Appropriate Limits

Check your API provider's documentation for their specific limits:

**OpenAI (GPT-4):**
- Free tier: 3 requests per minute
- Tier 1: 500 requests per minute, 30,000 tokens per minute
- Tier 2+: Higher limits based on usage

**Anthropic (Claude):**
- Tier 1: 50 requests per minute, 40,000 tokens per minute
- Tier 2: 1,000 requests per minute, 80,000 tokens per minute

**Example Configuration for OpenAI Tier 1:**

```env
RATE_LIMIT_REQUESTS_PER_MINUTE=500
RATE_LIMIT_TOKENS_PER_MINUTE=30000
RATE_LIMIT_MAX_CONCURRENT_REQUESTS=10
```

Set limits slightly below your actual quotas to account for other applications sharing the same API key.

### Retry Behavior

When an API call fails due to rate limiting, the system automatically retries with exponential backoff:

1. **First retry**: Wait 1 second (with random variation)
2. **Second retry**: Wait 2 seconds (with random variation)
3. **Third retry**: Wait 4 seconds (with random variation)

The random variation prevents many requests from retrying at exactly the same time. After 3 failed attempts, the error is reported to the user.

## Performance Considerations

### When Parallel Execution Helps

Parallel execution provides the most benefit when:

- Your framework has many aspects with few dependencies
- Aspects are relatively independent
- You have sufficient API rate limit capacity
- Network latency to the API provider is significant

### When Sequential Processing is Better

Stick with sequential processing (parallel mode disabled) when:

- Your framework has many dependencies between aspects
- You have strict rate limits
- You want predictable, deterministic execution order
- Debugging or troubleshooting refinement logic

### Measuring Performance

To evaluate the benefit of parallel execution for your use case, compare processing times:

**With parallel execution:**

```bash
time poetry run query-refine --framework your_framework --parallel
```

**Without parallel execution:**

```bash
time poetry run query-refine --framework your_framework --no-parallel
```

The difference indicates the speedup from parallel processing. Frameworks with more independent aspects typically see larger improvements.

## Troubleshooting

### Circular Dependency Warnings

If you see a message about circular dependencies:

```text
Circular dependencies detected in framework, falling back to sequential execution
```

This means aspects in your framework have circular dependency relationships (A depends on B, B depends on C, C depends on A). The system automatically switches to sequential processing to ensure correct operation.

**Solution**: Review your framework's `depends_on` declarations and remove circular references.

### Rate Limit Errors

If you encounter rate limit errors frequently:

```text
Rate limit exceeded, retrying after 5 seconds...
```

**Solutions:**

1. Reduce `RATE_LIMIT_REQUESTS_PER_MINUTE` to a lower value
2. Reduce `PARALLEL_MAX_CONCURRENT` to process fewer aspects simultaneously
3. Enable adaptive backoff: `RATE_LIMIT_ADAPTIVE_BACKOFF=true`
4. Check if other applications are using the same API key

### Slower than Expected Performance

If parallel execution is not improving performance:

**Check dependency structure**: Use the CLI to see how aspects are organized:

```bash
poetry run query-refine --framework your_framework --parallel
```

Look for messages about how many aspects are in each level. If most aspects are in different levels, they cannot run in parallel.

**Verify rate limits**: If rate limits are very restrictive, the system spends time waiting rather than processing. Consider increasing your API tier or reducing concurrent processing.

**Network latency**: Parallel execution benefits from network latency. On very fast connections, the overhead of parallel coordination may outweigh benefits.

## Best Practices

### Framework Design

When designing refinement frameworks for parallel execution:

1. **Minimize dependencies**: Only declare dependencies when one aspect truly needs information from another
2. **Group related aspects**: Aspects that depend on the same prerequisites often process efficiently together
3. **Start broad, then narrow**: Place general aspects (with few dependencies) early in the framework

### Rate Limit Configuration

For optimal rate limit settings:

1. **Start conservative**: Begin with lower limits and increase gradually
2. **Monitor usage**: Check your API provider dashboard for actual usage patterns
3. **Leave headroom**: Set limits 10-20% below your actual quotas
4. **Use adaptive backoff**: Enable adaptive rate limiting in production environments

### Testing

When testing parallel execution:

1. **Test with small frameworks first**: Verify behavior with 2-3 aspects before scaling up
2. **Compare results**: Ensure parallel execution produces the same results as sequential
3. **Monitor API usage**: Watch your API provider metrics during testing
4. **Test error scenarios**: Simulate rate limit errors to verify retry behavior

## Advanced Topics

### Per-User Rate Limiting

The system supports per-user rate limiting in addition to global limits. This is useful for multi-tenant applications:

```python
from query_refinement_module.rate_limiter import TokenBucketRateLimiter
from query_refinement_module.interfaces import RateLimitConfig

# Create per-user rate limiter
config = RateLimitConfig(
    requests_per_minute=10,
    tokens_per_minute=5000,
)

limiter = TokenBucketRateLimiter(config=config, scope="user")
```

With per-user limiting, each user gets their own rate limit allocation.

### Redis-Based Rate Limiting

For distributed deployments with multiple API servers, use Redis for rate limiting:

```python
from query_refinement_module.rate_limiter import RedisRateLimiter
import redis

# Connect to Redis
redis_client = redis.Redis(host='localhost', port=6379)

# Create distributed rate limiter
limiter = RedisRateLimiter(
    redis_client=redis_client,
    config=config,
    scope="global"
)
```

Redis-based rate limiting ensures limits are enforced across all servers in your deployment.

### Custom Backoff Strategies

Customize the retry backoff behavior:

```python
from query_refinement_module.rate_limiter import BackoffStrategy

strategy = BackoffStrategy(
    base_delay=2.0,      # Start with 2 second delays
    max_delay=30.0,      # Cap at 30 seconds
    multiplier=2.0,      # Double delay each retry
    jitter=0.2,          # Add 20% random variation
)
```

Adjust these parameters based on your API provider's retry recommendations.

## Summary

Parallel execution improves query refinement performance by processing independent aspects simultaneously. The system handles dependency management, rate limiting, and error recovery automatically. Configure parallel execution through environment variables or command-line flags, and adjust rate limits based on your API provider's quotas.

For most use cases, enabling parallel execution with conservative rate limits provides a good balance of performance and reliability. Monitor your API usage and adjust settings as needed for your specific requirements.
