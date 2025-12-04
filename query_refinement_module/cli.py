"""Synchronous command-line interface for local query refinement testing."""

from __future__ import annotations

from dotenv import load_dotenv

import argparse
import os
import sys
from typing import Optional

from .analyzers import LLMQueryAnalyzer
from .core import QueryRefinementManager, is_user_command, parse_user_command
from .logging_utils import configure_file_logging
from .providers import ConsoleTracing, FileTracingProvider, LiteLLMProvider
from .schema import registry
from .settings import LLMSettings

load_dotenv(override=False)

def build_manager(
    *,
    enable_tracing: bool,
    trace_dir: Optional[str] = None,
    log_dir: Optional[str] = None,
    parallel_enabled: bool = True,
) -> QueryRefinementManager:
    logs_directory = log_dir or trace_dir
    if logs_directory:
        configure_file_logging(logs_directory)

    tracer: Optional[ConsoleTracing | FileTracingProvider]
    if trace_dir:
        tracer = FileTracingProvider(trace_dir)
    elif enable_tracing:
        tracer = ConsoleTracing()
    else:
        tracer = None
    settings = LLMSettings.from_env()

    provider = LiteLLMProvider(**settings.as_provider_kwargs())
    analyzer = LLMQueryAnalyzer(provider, **settings.as_analyzer_kwargs())

    # Build parallel config if enabled
    parallel_config = None
    if parallel_enabled:
        from .interfaces import RateLimitConfig
        from .parallel import ParallelConfig
        from .rate_limiter import TokenBucketRateLimiter, BackoffStrategy
        
        # Get rate limits from environment or provider defaults
        rate_limit_config = RateLimitConfig.from_env()
        if not rate_limit_config or not rate_limit_config.requests_per_minute:
            # Use provider defaults
            rate_limit_config = provider.get_rate_limits()
        
        rate_limiter = TokenBucketRateLimiter(
            config=rate_limit_config,
            scope="global",
        )
        
        parallel_config = ParallelConfig(
            enabled=True,
            max_concurrent=rate_limit_config.max_concurrent_requests or 5,
            rate_limiter=rate_limiter,
            backoff_strategy=BackoffStrategy(),
            max_retries=3,
        )

    return QueryRefinementManager(
        llm_provider=provider,
        query_analyzer=analyzer,
        tracing_provider=tracer,
        parallel_config=parallel_config,
    )


def _format_dependency_context(session, aspect_id: str) -> Optional[str]:
    context = session.get_dependency_context(aspect_id)
    if not context:
        return None

    lines = ["📎 Dependency Context:"]
    for dep_id, info in context.items():
        label = info.get("name", dep_id)
        value = info.get("value", "[unspecified]")
        lines.append(f"  • {label}: {value}")
    return "\n".join(lines)


def _print_summary(manager: QueryRefinementManager, session) -> None:
    summary = manager.get_initialization_summary(session)
    print("\n" + "="*80)
    print("SESSION SUMMARY")
    print("="*80)
    print(f"Refinement aspects in this framework: {summary['total_aspects']}")
    print(f"Needs refinement: {summary['aspects_needing_refinement']}")
    print(f"Already clear: {summary['aspects_clear']}")
    print()
    for aspect in summary["aspects"]:
        status = aspect["status"]
        print(f"  [{status.upper()}] {aspect['name']}")
        reason = aspect.get("reason")
        if reason:
            print(f"  → {reason}")
        print()
    print("="*80)


def run_cli(manager: QueryRefinementManager, framework_name: str, query: str, parallel_enabled: bool = True) -> None:
    try:
        framework = registry.get_framework(framework_name)
    except ValueError as exc:
        print(f"Error: {exc}")
        return

    print("\n" + "="*80)
    if parallel_enabled and manager.parallel_config:
        print(f"⚡ PARALLEL MODE: Up to {manager.parallel_config.max_concurrent} concurrent requests")
    else:
        print("📝 SEQUENTIAL MODE: Processing one aspect at a time")
    print("="*80)
    
    session = manager.initialize(query, framework)
    _print_summary(manager, session)

    print("\n" + "="*80)
    print("INSTRUCTIONS")
    print("="*80)
    print("• Type your answers to refine each aspect")
    print("• Use commands like /help, /status, /back, /skip, /end")
    print("• Press Ctrl+C to exit at any time")
    print("="*80 + "\n")

    interrupted = False

    try:
        while True:
            if session.synthesis_requested:
                break

            step = session.get_active_step()
            if not step:
                break

            if hasattr(manager, "ensure_step_is_ready"):
                if not manager.ensure_step_is_ready(session, step):
                    # Aspect resolved after refreshed analysis; move to next candidate.
                    continue

            header = step.refinement_aspect.name
            question = step.analysis_suggested_question or header
            
            print("\n" + "─"*80)
            if step.needs_review:
                print(f"📋 {header.upper()} (needs review)")
            else:
                print(f"📋 {header.upper()}")
            print("─"*80)

            context_text = _format_dependency_context(session, step.refinement_aspect.id)
            if context_text:
                print(f"\n{context_text}\n")

            print(f"{question}\n")
            user_input = input("→ ").strip()
            if not user_input:
                continue

            if is_user_command(user_input):
                command_result = parse_user_command(user_input)
                payload = session.handle_command(command_result)
                print(payload.get("message", ""))
                if payload.get("submit") or session.synthesis_requested:
                    continue
                invalidated = payload.get("invalidated", []) or []
                if invalidated:
                    print("Revisit: " + ", ".join(invalidated))
                continue

            step.add_follow_up(question=question, response=user_input)
            step.is_complete = True
            step.needs_review = False
            print(f"Recorded response for {header}.")

        print("\n" + "="*80)
        print("RESULTS")
        print("="*80)
        print(f"Original: {session.original_query}")

        try:
            synthesis = manager.synthesize_refined_query(session)
        except ValueError as exc:
            print(f"Error: {exc}")
        except Exception as exc:
            print(f"Error: {exc}")
        else:
            refined_query = synthesis.get("refined_query", "").strip()
            if refined_query:
                print(f"Refined:  {refined_query}")
            else:
                print(f"Refined:  {session.original_query}")
        print("="*80)

    except KeyboardInterrupt:
        interrupted = True
        print("\n" + "="*80)
        print("Session interrupted by user.")
        print("="*80)

    if interrupted:
        return


def parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Interactive CLI for query refinement testing.")
    parser.add_argument("--framework", "-f", help="Name of the framework to load", required=False)
    parser.add_argument("--query", "-q", help="Original query to refine", required=False)
    parser.add_argument("--list-frameworks", action="store_true", help="List available frameworks and exit")
    parser.add_argument("--trace", action="store_true", help="Enable verbose console tracing")
    parser.add_argument("--trace-dir", help="Write tracing operations and events to this directory")
    parser.add_argument("--log-dir", help="Directory for application logs (defaults to trace-dir when set)")
    
    # Parallel execution options
    parallel_group = parser.add_mutually_exclusive_group()
    parallel_group.add_argument(
        "--parallel",
        action="store_true",
        default=None,
        help="Enable parallel aspect analysis (default: enabled via QUERY_REFINEMENT_PARALLEL_MODE)"
    )
    parallel_group.add_argument(
        "--no-parallel",
        action="store_true",
        help="Disable parallel execution, process aspects sequentially"
    )
    
    return parser.parse_args(argv)


def main(argv: Optional[list[str]] = None) -> None:
    args = parse_args(argv)

    try:
        registry.reload_from_env(raise_on_error=True)
    except registry.FrameworkLoadError as exc:
        print(f"Failed to load refinement frameworks: {exc}")
        last_error = registry.get_last_load_error()
        if last_error and str(exc) != last_error:
            print(last_error)
        return

    frameworks = registry.list_frameworks()
    if args.list_frameworks:
        if not frameworks:
            print("No frameworks loaded. Set REFINEMENT_FRAMEWORK_PATH to your YAML file.")
        else:
            print("Available frameworks:")
            for name in frameworks:
                print(f"- {name}")
        return

    if not frameworks:
        print("No frameworks available. Use --list-frameworks for help.")
        return

    framework_name = args.framework or (frameworks[0] if len(frameworks) == 1 else None)
    if not framework_name:
        print("Select a framework with --framework. Use --list-frameworks to inspect options.")
        return

    if framework_name not in frameworks:
        print(f"Framework '{framework_name}' not found. Use --list-frameworks to view valid names.")
        return

    query = args.query
    if not query:
        try:
            query = input("Original query: ").strip()
        except KeyboardInterrupt:
            print()
            return

    if not query:
        print("A non-empty query is required.")
        return

    trace_enabled = bool(args.trace or args.trace_dir)
    
    # Determine parallel mode: CLI flags override environment variable
    if args.no_parallel:
        parallel_enabled = False
    elif args.parallel:
        parallel_enabled = True
    else:
        # Check environment variable (default: true)
        env_parallel = os.getenv("QUERY_REFINEMENT_PARALLEL_MODE", "true").lower()
        parallel_enabled = env_parallel in ("true", "1", "yes", "on")

    try:
        manager = build_manager(
            enable_tracing=trace_enabled,
            trace_dir=args.trace_dir,
            log_dir=args.log_dir,
            parallel_enabled=parallel_enabled,
        )
    except RuntimeError as exc:
        print(f"Failed to initialise LLM provider: {exc}")
        return
    except ValueError as exc:
        print(f"Invalid LLM configuration: {exc}")
        return

    run_cli(manager, framework_name, query, parallel_enabled=parallel_enabled)


if __name__ == "__main__":  # pragma: no cover
    main(sys.argv[1:])
