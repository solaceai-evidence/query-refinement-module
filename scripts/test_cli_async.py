#!/usr/bin/env python3
"""Test CLI with simulated input to verify async works end-to-end."""

import asyncio
import sys
from io import StringIO
from unittest.mock import patch
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

async def test_cli_simulation():
    """Simulate CLI interaction to test async behavior."""
    from query_refinement_module.cli import build_manager, run_cli
    from query_refinement_module.schema import registry
    
    print("="*80)
    print("Testing CLI Async Execution")
    print("="*80)
    
    # Setup
    manager = build_manager(
        enable_tracing=False,
        parallel_enabled=True,
    )
    
    framework_name = "pico_advanced"
    query = "What treatments help with diabetes in adults?"
    
    print(f"\n✓ Framework: {framework_name}")
    print(f"✓ Query: {query}")
    print(f"✓ Parallel mode: {manager.parallel_config is not None}\n")
    
    # Simulate user inputs - ending the session immediately
    simulated_inputs = ["/end"]
    
    async def mock_input(prompt):
        """Mock async input that returns predetermined values."""
        if simulated_inputs:
            value = simulated_inputs.pop(0)
            print(f"{prompt}{value}")
            return value
        return "/end"
    
    # Patch asyncio.to_thread to use our mock
    original_to_thread = asyncio.to_thread
    async def patched_to_thread(func, *args):
        if func == input:
            return await mock_input(*args)
        return await original_to_thread(func, *args)
    
    with patch('asyncio.to_thread', patched_to_thread):
        try:
            await run_cli(manager, framework_name, query, parallel_enabled=True)
            print("\n✓ CLI executed successfully")
            return True
        except Exception as e:
            print(f"\n❌ CLI execution failed: {e}")
            import traceback
            traceback.print_exc()
            return False

if __name__ == "__main__":
    success = asyncio.run(test_cli_simulation())
    sys.exit(0 if success else 1)
