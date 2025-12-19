#!/usr/bin/env python3
"""Quick test script to verify async streaming works."""

import asyncio
import sys
from query_refinement_module.cli import build_manager
from query_refinement_module.schema import registry

async def test_streaming():
    """Test streaming initialization."""
    print("="*80)
    print("Testing Async Streaming Implementation")
    print("="*80)
    
    # Build manager with parallel enabled
    manager = build_manager(
        enable_tracing=False,
        parallel_enabled=True,
    )
    
    # Get framework
    frameworks = registry.list_frameworks()
    if not frameworks:
        print("❌ No frameworks available")
        return False
    
    framework_name = frameworks[0]
    framework = registry.get_framework(framework_name)
    
    print(f"\n✓ Using framework: {framework_name}")
    print(f"✓ Parallel config: max_concurrent={manager.parallel_config.max_concurrent}")
    
    # Test query
    query = "What are effective treatments for diabetes?"
    print(f"✓ Test query: {query}\n")
    
    # Test streaming
    print("Starting streaming initialization...\n")
    
    session = None
    level_count = 0
    
    try:
        async for session_partial, level_idx, level_results, metadata, is_final in manager.initialize_streaming(
            query, framework, manager.parallel_config
        ):
            session = session_partial
            
            if is_final:
                print(f"\n✓ Final result received")
                break
            
            level_count += 1
            total_completed = metadata.get("total_completed", 0)
            total_aspects = metadata.get("total_aspects", 0)
            elapsed = metadata.get("elapsed_time", 0)
            successful = metadata.get("successful_in_level", 0)
            
            print(f"✓ Level {level_idx + 1} complete:")
            print(f"  • {successful}/{len(level_results)} aspects successful")
            print(f"  • {total_completed}/{total_aspects} total analyzed")
            print(f"  • {elapsed:.2f}s elapsed\n")
            
    except Exception as e:
        print(f"\n❌ Error during streaming: {e}")
        import traceback
        traceback.print_exc()
        return False
    
    if session:
        print(f"\n✓ Session initialized successfully")
        print(f"  • Total steps: {len(session.steps)}")
        print(f"  • Levels processed: {level_count}")
        print(f"  • Steps needing refinement: {len([s for s in session.steps if not s.is_complete])}")
        return True
    else:
        print(f"\n❌ Session not initialized")
        return False

if __name__ == "__main__":
    success = asyncio.run(test_streaming())
    sys.exit(0 if success else 1)
