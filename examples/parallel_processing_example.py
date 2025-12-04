"""
Example demonstrating parallel processing with rate limiting.

This example shows how to use ParallelConfig with the QueryRefinementManager
to enable parallel aspect analysis with rate limiting and dependency management.
"""

from query_refinement_module.parallel import ParallelConfig
from query_refinement_module.rate_limiter import TokenBucketRateLimiter, BackoffStrategy
from query_refinement_module.interfaces import RateLimitConfig
from query_refinement_module.schema import RefinementAspect

# Example: Setting up parallel processing with rate limiting

# 1. Create rate limiter (e.g., 10 requests per minute, global scope)
rate_limit_config = RateLimitConfig(
    requests_per_minute=10,
    tokens_per_minute=None,  # Optional token limiting
    max_concurrent=5,
    adaptive_backoff=True
)

rate_limiter = TokenBucketRateLimiter(
    config=rate_limit_config,
    scope="global"
)

# 2. Create backoff strategy for retries
backoff = BackoffStrategy(
    base_delay=1.0,
    max_delay=60.0,
    multiplier=2.0,
    jitter=0.1
)

# 3. Configure parallel execution
parallel_config = ParallelConfig(
    enabled=True,
    max_concurrent=5,
    rate_limiter=rate_limiter,
    backoff_strategy=backoff,
    max_retries=3
)

# 4. Example refinement aspects with dependencies
aspects = [
    # Level 0: No dependencies
    RefinementAspect(
        id="population",
        name="Population",
        description="Define the target population"
    ),
    RefinementAspect(
        id="intervention",
        name="Intervention",
        description="Specify the intervention being studied"
    ),
    
    # Level 1: Depends on Level 0
    RefinementAspect(
        id="outcomes",
        name="Outcomes",
        description="Define measurable outcomes",
        depends_on=["population", "intervention"]
    ),
    
    # Level 2: Depends on Level 1
    RefinementAspect(
        id="study_design",
        name="Study Design",
        description="Specify study methodology",
        depends_on=["outcomes"]
    )
]

# Usage example (pseudo-code):
"""
# Initialize manager with your LLM provider and analyzer
manager = QueryRefinementManager(
    llm_provider=your_llm_provider,
    query_analyzer=LLMBasedQueryAnalyzer(system_prompt="...")
)

# Initialize session with parallel config
session = manager.initialize(
    original_query="What is the effect of exercise on blood pressure?",
    refinement_framework=aspects,
    parallel_config=parallel_config  # Enable parallel processing
)

# Execution flow:
# - Level 0 (population, intervention): Analyzed in parallel
# - Level 1 (outcomes): Analyzed after Level 0 completes
# - Level 2 (study_design): Analyzed after Level 1 completes
# 
# Rate limiting ensures we don't exceed 10 requests per minute.
# If rate limit is exceeded, exponential backoff with jitter is applied.
# Failed aspects are retried up to 3 times before giving up.
"""

print("Example parallel configuration created successfully!")
print(f"- Max concurrent: {parallel_config.max_concurrent}")
print(f"- Rate limit: {rate_limit_config.requests_per_minute} RPM")
print(f"- Max retries: {parallel_config.max_retries}")
print(f"- Adaptive backoff: {rate_limit_config.adaptive_backoff}")
