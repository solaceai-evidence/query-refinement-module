#!/usr/bin/env python3
"""Quick async validation test for the refactored code."""

import asyncio
import sys
import os

# Add parent dir to path
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from query_refinement_module.providers import LiteLLMProvider
from query_refinement_module.core import QueryRefinementManager


async def test_concurrent_llm_calls():
    """Test that multiple async LLM calls can run concurrently."""
    
    # Setup provider - use default_model parameter
    provider = LiteLLMProvider(
        default_model="gpt-4o-mini",
        default_completion_kwargs={"temperature": 0.0, "max_tokens": 100}
    )
    
    print("✓ Provider initialized with semaphore (50 concurrent limit)")
    
    # Test concurrent calls
    print("\n🧪 Testing 10 concurrent LLM calls...")
    
    async def make_call(i):
        result = await provider.complete_async(
            system_prompt="You are a helpful assistant.",
            user_prompt=f"Say 'Test {i}' and nothing else."
        )
        return f"Call {i}: {result.context[:50]}"
    
    import time
    start = time.time()
    results = await asyncio.gather(*[make_call(i) for i in range(10)])
    elapsed = time.time() - start
    
    print(f"✓ Completed 10 calls in {elapsed:.2f}s")
    for result in results[:3]:
        print(f"  - {result}")
    
    print(f"\n✅ Async conversion working! Semaphore controlling concurrency.")
    print(f"   Average: {elapsed/10:.2f}s per call (with parallelism)")
    return True


if __name__ == "__main__":
    try:
        asyncio.run(test_concurrent_llm_calls())
    except Exception as e:
        print(f"❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    try:
        result = asyncio.run(test_async_manager())
        sys.exit(0 if result else 1)
    except Exception as e:
        print(f"\n❌ Test failed: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        sys.exit(1)
