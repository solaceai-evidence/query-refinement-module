#!/usr/bin/env python3
"""
Script to print the actual prompts sent to the LLM during CLI execution.

This script intercepts and displays the message arrays before they're sent to the LLM,
making it easy to debug and inspect prompt construction.

Usage:
    poetry run python scripts/print_llm_prompts.py --framework pico_advanced --query "your query here"
    
    # After the first question is generated, type your answer to see follow-up prompts
"""

import asyncio
import sys
import argparse
from typing import List, Dict, Any
from dotenv import load_dotenv

# Add parent directory to path
sys.path.insert(0, '.')

from query_refinement_module.core import QueryRefinementManager
from query_refinement_module.providers import LiteLLMProvider
from query_refinement_module.schema import registry
from query_refinement_module.settings import LLMSettings

load_dotenv(override=False)


def print_separator(title: str):
    """Print a nice separator."""
    print("\n" + "="*80)
    print(f" {title}")
    print("="*80)


def print_messages(messages: List[Dict[str, str]], title: str = "Messages Sent to LLM"):
    """Pretty-print the message array."""
    print_separator(title)
    
    for i, msg in enumerate(messages, 1):
        role = msg.get('role', 'unknown')
        content = msg.get('content', '')
        cache_marker = " [CACHED]" if msg.get('_cache') else ""
        
        print(f"\n{'─'*80}")
        print(f"Message {i}: {role.upper()}{cache_marker}")
        print(f"{'─'*80}")
        print(content)
    
    print("\n" + "="*80 + "\n")


async def main():
    parser = argparse.ArgumentParser(description="Print LLM prompts for debugging")
    parser.add_argument("--framework", "-f", required=True, help="Framework name")
    parser.add_argument("--query", "-q", required=True, help="Query to analyze")
    parser.add_argument("--aspect", "-a", help="Specific aspect to show (defaults to first)")
    parser.add_argument("--mode", "-m", choices=['initial', 'followup'], default='initial',
                       help="Show initial or followup prompt")
    args = parser.parse_args()
    
    # Load frameworks
    try:
        registry.reload_from_env(raise_on_error=True)
    except registry.FrameworkLoadError as exc:
        print(f"Failed to load frameworks: {exc}")
        return 1
    
    frameworks = registry.list_frameworks()
    if args.framework not in frameworks:
        print(f"Framework '{args.framework}' not found.")
        print(f"Available: {', '.join(frameworks)}")
        return 1
    
    # Initialize manager
    settings = LLMSettings.from_env()
    provider = LiteLLMProvider(**settings.as_provider_kwargs())
    manager = QueryRefinementManager(llm_provider=provider)
    
    # Get framework
    framework = registry.get_framework(args.framework)
    
    # Initialize session
    session = manager.initialize_sequential(
        original_query=args.query,
        refinement_framework=framework
    )
    
    # Get first (or specified) aspect
    if args.aspect:
        step = next((s for s in session.steps if s.refinement_aspect.id == args.aspect), None)
        if not step:
            print(f"Aspect '{args.aspect}' not found.")
            print(f"Available: {', '.join(s.refinement_aspect.id for s in session.steps)}")
            return 1
    else:
        step = session.steps[0]
    
    aspect = step.refinement_aspect
    
    print_separator(f"Framework: {args.framework}")
    print(f"Query: {args.query}")
    print(f"Aspect: {aspect.aspect_name} ({aspect.id})")
    print(f"Mode: {args.mode}")
    
    # Build messages
    dependency_context = session.get_dependency_context(aspect.id)
    
    if args.mode == 'followup' and not step.conversation_history:
        # Add a simulated conversation turn for demonstration
        print("\n⚠️  No conversation history - adding simulated follow-up for demonstration")
        step.conversation_history.append({
            'question': 'What age range are you targeting?',
            'response': 'Adults 30-50 years old'
        })
    
    messages = step.get_messages(
        query=session.original_query,
        dependency_context=dependency_context
    )
    
    # Print the messages
    print_messages(messages, title=f"{args.mode.upper()} - Messages Sent to LLM")
    
    # Show some statistics
    print(f"Total messages: {len(messages)}")
    print(f"Cached messages: {sum(1 for m in messages if m.get('_cache'))}")
    print(f"System messages: {sum(1 for m in messages if m.get('role') == 'system')}")
    print(f"User messages: {sum(1 for m in messages if m.get('role') == 'user')}")
    print(f"Assistant messages: {sum(1 for m in messages if m.get('role') == 'assistant')}")
    
    # Show character counts
    total_chars = sum(len(m.get('content', '')) for m in messages)
    cached_chars = sum(len(m.get('content', '')) for m in messages if m.get('_cache'))
    print(f"\nTotal characters: {total_chars:,}")
    print(f"Cached characters: {cached_chars:,} ({cached_chars*100//total_chars if total_chars else 0}%)")
    
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
