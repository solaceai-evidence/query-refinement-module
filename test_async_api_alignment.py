#!/usr/bin/env python3
"""
Quick integration test to verify API async alignment.

This script tests that:
1. API endpoints are properly async
2. Streaming initialization works with parallel mode
3. Fallback to sequential mode works correctly
"""
import asyncio
import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.dirname(__file__))

from query_refinement_module.core import QueryRefinementManager
from query_refinement_module.providers import LiteLLMProvider
from query_refinement_module.analyzers import LLMQueryAnalyzer
from query_refinement_module.schema.registry import get_framework
from query_refinement_module.settings import LLMSettings
from query_refinement_module.parallel import ParallelConfig
from query_refinement_module.interfaces import RateLimitConfig
from query_refinement_module.rate_limiter import TokenBucketRateLimiter, BackoffStrategy


async def test_streaming_initialization():
    """Test that streaming initialization works correctly."""
    print("=" * 80)
    print("Testing Async Streaming Initialization")
    print("=" * 80)
    
    # Build manager with parallel config
    settings = LLMSettings.from_env()
    provider = LiteLLMProvider(**settings.as_provider_kwargs())
    analyzer = LLMQueryAnalyzer(provider, **settings.as_analyzer_kwargs())
    
    rate_limit_config = RateLimitConfig.from_env()
    if not rate_limit_config or not rate_limit_config.requests_per_minute:
        rate_limit_config = provider.get_rate_limits()
    
    rate_limiter = TokenBucketRateLimiter(
        config=rate_limit_config,
        scope="global",
    )
    
    parallel_config = ParallelConfig(
        enabled=True,
        max_concurrent=3,
        rate_limiter=rate_limiter,
        backoff_strategy=BackoffStrategy(),
        max_retries=3,
    )
    
    manager = QueryRefinementManager(
        llm_provider=provider,
        query_analyzer=analyzer,
        tracing_provider=None,
        parallel_config=parallel_config,
    )
    
    # Test with a simple query
    query = "childhood obesity interventions"
    framework = get_framework("pico_advanced")
    
    print(f"\nQuery: {query}")
    print(f"Framework: pico_advanced")
    print(f"Parallel mode: ENABLED (max_concurrent={parallel_config.max_concurrent})")
    print("\nInitializing with streaming...")
    
    session = None
    level_count = 0
    
    try:
        async for session_partial, level_idx, level_results, metadata, is_final in manager.initialize_streaming(
            query, framework, parallel_config
        ):
            session = session_partial
            
            if is_final:
                print(f"\n✓ Final session ready")
                break
            
            level_count += 1
            successful = metadata.get("successful_in_level", 0)
            failed = metadata.get("failed_in_level", 0)
            total_completed = metadata.get("total_completed", 0)
            total_aspects = metadata.get("total_aspects", 0)
            elapsed = metadata.get("elapsed_time", 0)
            
            print(f"\n  Level {level_idx + 1} complete: {successful}/{len(level_results)} successful "
                  f"[{total_completed}/{total_aspects} total, {elapsed:.1f}s]")
            
            for aspect_id, result in level_results.items():
                if result:
                    status = "✓ clear" if not result.needs_refinement else "→ needs refinement"
                    print(f"    {status}: {aspect_id}")
                else:
                    print(f"    ✗ failed: {aspect_id}")
        
        if session:
            print(f"\n✓ Session initialized successfully")
            print(f"  Total aspects: {len(session.steps)}")
            print(f"  Needs refinement: {sum(1 for s in session.steps if not s.is_complete)}")
            print(f"  Already clear: {sum(1 for s in session.steps if s.is_complete)}")
            return True
        else:
            print("\n✗ Session initialization failed - no session returned")
            return False
            
    except Exception as e:
        print(f"\n✗ Error during streaming initialization: {e}")
        import traceback
        traceback.print_exc()
        return False


async def test_sequential_fallback():
    """Test that sequential mode still works."""
    print("\n" + "=" * 80)
    print("Testing Sequential Mode Fallback")
    print("=" * 80)
    
    # Build manager WITHOUT parallel config
    settings = LLMSettings.from_env()
    provider = LiteLLMProvider(**settings.as_provider_kwargs())
    analyzer = LLMQueryAnalyzer(provider, **settings.as_analyzer_kwargs())
    
    manager = QueryRefinementManager(
        llm_provider=provider,
        query_analyzer=analyzer,
        tracing_provider=None,
        parallel_config=None,  # No parallel config
    )
    
    query = "childhood obesity interventions"
    framework = get_framework("pico_advanced")
    
    print(f"\nQuery: {query}")
    print(f"Framework: pico_advanced")
    print(f"Parallel mode: DISABLED")
    print("\nInitializing with standard method...")
    
    try:
        session = await asyncio.to_thread(
            manager.initialize,
            query,
            framework,
            None,
        )
        
        if session:
            print(f"\n✓ Session initialized successfully (sequential mode)")
            print(f"  Total aspects: {len(session.steps)}")
            print(f"  Needs refinement: {sum(1 for s in session.steps if not s.is_complete)}")
            print(f"  Already clear: {sum(1 for s in session.steps if s.is_complete)}")
            return True
        else:
            print("\n✗ Session initialization failed - no session returned")
            return False
            
    except Exception as e:
        print(f"\n✗ Error during sequential initialization: {e}")
        import traceback
        traceback.print_exc()
        return False


async def main():
    """Run all tests."""
    print("\n" + "=" * 80)
    print("API Async Alignment Integration Tests")
    print("=" * 80)
    
    results = []
    
    # Test 1: Streaming initialization
    try:
        result1 = await test_streaming_initialization()
        results.append(("Streaming Initialization", result1))
    except Exception as e:
        print(f"\n✗ Streaming test crashed: {e}")
        results.append(("Streaming Initialization", False))
    
    # Test 2: Sequential fallback
    try:
        result2 = await test_sequential_fallback()
        results.append(("Sequential Fallback", result2))
    except Exception as e:
        print(f"\n✗ Sequential test crashed: {e}")
        results.append(("Sequential Fallback", False))
    
    # Summary
    print("\n" + "=" * 80)
    print("Test Results Summary")
    print("=" * 80)
    
    for test_name, passed in results:
        status = "✓ PASSED" if passed else "✗ FAILED"
        print(f"{status}: {test_name}")
    
    all_passed = all(result for _, result in results)
    
    if all_passed:
        print("\n✓ All tests passed!")
        return 0
    else:
        print("\n✗ Some tests failed")
        return 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
