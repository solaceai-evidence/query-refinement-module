"""Async command-line interface for query refinement testing."""

from __future__ import annotations

from dotenv import load_dotenv

import argparse
import asyncio
import os
import sys
from typing import Optional

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
    # Analyzer is deprecated - don't create one by default
    # analyzer = LLMQueryAnalyzer(provider, **settings.as_analyzer_kwargs())

    return QueryRefinementManager(
        llm_provider=provider,
        tracing_provider=tracer,
        terminal_reinforcement_threshold=settings.terminal_reinforcement_threshold,
    )


def _format_dependency_context(session, aspect_id: str) -> Optional[str]:
    context = session.get_dependency_context(aspect_id)
    if not context:
        return None

    lines = ["Dependency Context:"]
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
    print(f"Needs refinement: {summary['incomplete_count']}")
    print(f"Already clear: {summary['complete_count']}")
    print()
    for aspect in summary["aspects"]:
        status = "complete" if aspect["is_complete"] else "needs_refinement"
        print(f"  [{status.upper()}] {aspect['name']}")
        reason = aspect.get("reasoning")
        if reason:
            print(f"  → {reason}")
        print()
    print("="*80)


async def run_cli(manager: QueryRefinementManager, framework_name: str, query: str) -> None:
    try:
        framework = registry.get_framework(framework_name)
    except ValueError as exc:
        print(f"Error: {exc}")
        return

    print("\n" + "="*80)
    print("QUERY REFINEMENT - Sequential On-Demand Mode")
    print("="*80)
    print(f"Original query: {query}")
    print(f"Framework: {framework_name}")
    print(f"Total aspects: {len(framework)}")
    print("="*80)
    
    # Use sequential initialization (no upfront analysis)
    print("\n Initializing session...")
    session = manager.initialize_sequential(query, framework)
    print(f"✓ Session ready with {len(session.steps)} aspects to refine\n")

    print("="*80)
    print("INSTRUCTIONS")
    print("="*80)
    print("• Answer each question to clarify details on the research dimensions associated with your input")
    print("• Commands: /help, /status, /back, /skip, /done, /end")
    print("• Press Ctrl+C to exit at any time")
    print("="*80 + "\n")

    interrupted = False

    try:
        while True:
            if session.synthesis_requested:
                break

            # Get next aspect that needs refinement (respects dependencies)
            step = session.get_next_unrefined_aspect()
            if not step:
                # All aspects complete
                break

            header = step.refinement_aspect.name
            aspect_desc = step.refinement_aspect.description or ""
            
            print("\n" + "─"*80)
            print(f" {header.upper()}")
            if aspect_desc:
                print(f" {aspect_desc}")
            print("─"*80)

            # Show dependency context if available
            context_text = _format_dependency_context(session, step.refinement_aspect.id)
            if context_text:
                print(f"\n{context_text}\n")

            # Generate initial question for this aspect using unified approach
            print(" Generating clarifying question...\n")
            try:
                result = await manager.get_analysis_prompts(
                    session=session,
                    aspect_id=step.refinement_aspect.id,
                    mode='initial'
                )
                
                # Process result
                status = manager.process_analysis_result(
                    session=session,
                    aspect_id=step.refinement_aspect.id,
                    result=result
                )
                
                if status['complete']:
                    # Aspect is already clear from the query
                    print(f"✓ {header} is already clear from your query")
                    continue
                
                # Not complete - show question to user
                question = result.question
                
            except Exception as e:
                print(f" Error: {e}")
                print(f"Skipping aspect {header}...")
                step.was_skipped = True
                step.is_complete = True
                continue
            
            print(f"{question}\n")
            
            # Interactive loop for this aspect
            while not step.is_complete:
                # Get user input
                try:
                    user_input = await asyncio.to_thread(input, "→ ")
                    user_input = user_input.strip()
                except (KeyboardInterrupt, asyncio.CancelledError):
                    print("\n\n Session interrupted. Exiting...")
                    interrupted = True
                    break
                
                if not user_input:
                    continue

                # Handle commands
                if is_user_command(user_input):
                    command_result = parse_user_command(user_input)
                    payload = session.handle_command(command_result)
                    print(payload.get("message", ""))
                    if payload.get("submit") or session.synthesis_requested:
                        break
                    invalidated = payload.get("invalidated", []) or []
                    if invalidated:
                        print("Revisit: " + ", ".join(invalidated))
                    # If skip/done was executed, the step is now complete
                    if step.is_complete:
                        break
                    # If /clear was used, regenerate the question
                    if payload.get("regenerate_question"):
                        try:
                            print("\n Regenerating question...")
                            # Use unified approach to regenerate
                            mode = 'followup' if step.conversation_history else 'initial'
                            result = await manager.get_analysis_prompts(
                                session=session,
                                aspect_id=step.refinement_aspect.id,
                                mode=mode
                            )
                            
                            status = manager.process_analysis_result(
                                session=session,
                                aspect_id=step.refinement_aspect.id,
                                result=result
                            )
                            
                            if status['complete']:
                                print(f"✓ {header} is now complete")
                            else:
                                question = result.question
                                print(f"\n{question}\n")
                        except Exception as e:
                            print(f" Error regenerating question: {e}")
                    continue

                # Record answer
                if not question:
                    question = step.follow_up_question or f"Please provide details about {header}"
                step.add_follow_up(question=question, response=user_input)
                
                # Run follow-up analysis
                print("\n Analyzing your answer...")
                try:
                    result = await manager.run_followup_until_clear(
                        session,
                        aspect_id=step.refinement_aspect.id,
                        max_rounds=5
                    )
                    
                    complete = result.get('is_complete', False)
                    rounds = result.get('rounds', 0)
                    
                    if complete:
                        print(f"✓ {header} complete after {rounds} round(s)")
                        step.is_complete = True
                        break
                    else:
                        # Need more clarification
                        question = step.follow_up_question or f"Can you provide more details about {header}?"
                        print(f"\n{question}\n")
                        
                except Exception as e:
                    print(f" Error during analysis: {e}")
                    print(f"Marking {header} as complete with current answer.")
                    step.is_complete = True
                    break
            
            if interrupted:
                break

        if not interrupted:
            print("\n" + "="*80)
            print("GENERATING REFINED QUERY")
            print("="*80)
            print(f"Original: {session.original_query}\n")

            try:
                synthesis = await manager.synthesize_refined_query(session)
            except ValueError as exc:
                print(f"Error: {exc}")
            except Exception as exc:
                print(f"Error: {exc}")
            else:
                refined_query = synthesis.get("refined_query", "").strip()
                integrated_statement = synthesis.get("integrated_statement", "").strip()
                
                # Display synthesized statement (or fallback to refined_query)
                if integrated_statement:
                    print(f"Refined:  {integrated_statement}\n")
                elif refined_query:
                    print(f"Refined:  {refined_query}\n")
                else:
                    print(f"Refined:  {session.original_query}\n")
                
                # Show refined dimensions
                detail_values = synthesis.get("detail_values")
                if detail_values:
                    print("─"*80)
                    print("REFINED DIMENSIONS")
                    print("─"*80)
                    for aspect_id, value in detail_values.items():
                        aspect = next((s.refinement_aspect for s in session.steps if s.refinement_aspect.id == aspect_id), None)
                        aspect_name = aspect.name if aspect else aspect_id
                        if value and value != "[SKIPPED]" and value != "null":
                            print(f"• {aspect_name}: {value}")
                    print()
                
                # Show search optimized queries
                search_optimized = synthesis.get("search_optimized")
                if search_optimized:
                    print("─"*80)
                    print("SEARCH-OPTIMIZED QUERIES")
                    print("─"*80)
                    
                    semantic = search_optimized.get("semantic", "")
                    if semantic:
                        print(f"\nSemantic Query (for vector search):")
                        print(f"  {semantic}")
                    
                    keyword = search_optimized.get("keyword", {})
                    if keyword:
                        structured = keyword.get("structured", "")
                        if structured:
                            print(f"\nBoolean Query:")
                            print(f"  {structured}")
                        
                        phrases = keyword.get("phrases", [])
                        if phrases:
                            print(f"\nKey Phrases:")
                            for phrase in phrases:
                                print(f"  • \"{phrase}\"")
                        
                        terms = keyword.get("terms", {})
                        if terms:
                            required = terms.get("required", [])
                            optional = terms.get("optional", [])
                            excluded = terms.get("excluded", [])
                            
                            if required:
                                print(f"\nRequired Terms: {', '.join(required)}")
                            if optional:
                                print(f"Optional Terms: {', '.join(optional)}")
                            if excluded:
                                print(f"Excluded Terms: {', '.join(excluded)}")
                    
                    grey_lit = search_optimized.get("grey_literature", {})
                    if grey_lit and any(grey_lit.values()):
                        print(f"\nGrey Literature Search:")
                        broad = grey_lit.get("broad_concepts", [])
                        if broad:
                            print(f"  Concepts: {', '.join(broad)}")
                        org = grey_lit.get("organizational_terms", [])
                        if org:
                            print(f"  Organizations: {', '.join(org)}")
                        geo = grey_lit.get("geographic_variants", [])
                        if geo:
                            print(f"  Geographic: {', '.join(geo)}")
                    print()
                
                # Show search filters
                search_filters = synthesis.get("search_filters")
                if search_filters:
                    print("─"*80)
                    print("SEARCH FILTERS")
                    print("─"*80)
                    
                    pub_years = search_filters.get("publication_years", "")
                    if pub_years:
                        print(f"Publication Years: {pub_years}")
                    
                    venues = search_filters.get("venues", [])
                    if venues:
                        print(f"Venues: {', '.join(venues)}")
                    
                    authors = search_filters.get("authors", [])
                    if authors:
                        print(f"Authors: {', '.join(authors)}")
                    
                    pub_types = search_filters.get("publication_types", [])
                    if pub_types:
                        print(f"Publication Types: {', '.join(pub_types)}")
                    
                    fields = search_filters.get("fields_of_study", [])
                    if fields:
                        print(f"Fields of Study: {', '.join(fields)}")
                    print()
                
                # Show terminology
                terminology = synthesis.get("terminology")
                if terminology:
                    print("─"*80)
                    print("TERMINOLOGY")
                    print("─"*80)
                    
                    primary = terminology.get("primary_terms", [])
                    if primary:
                        print(f"Primary Terms: {', '.join(primary)}")
                    
                    synonyms = terminology.get("synonyms", {})
                    if synonyms:
                        print(f"\nSynonyms:")
                        for term, syn_list in synonyms.items():
                            if syn_list:
                                print(f"  {term}: {', '.join(syn_list)}")
                    
                    domain = terminology.get("domain_specific", [])
                    if domain:
                        print(f"\nDomain-Specific: {', '.join(domain)}")
                    
                    colloq = terminology.get("colloquial", [])
                    if colloq:
                        print(f"Colloquial: {', '.join(colloq)}")
                    print()
                    
            print("="*80)

    except KeyboardInterrupt:
        interrupted = True
        print("\n" + "="*80)
        print("Session interrupted by user.")
        print("="*80)
    except asyncio.CancelledError:
        interrupted = True
        print("\n" + "="*80)
        print("Session cancelled.")
        print("="*80)

    if interrupted:
        return


def parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Interactive CLI for query refinement testing.")
    parser.add_argument("--framework", "-f", help="Name of the refinement framework to load", required=False)
    parser.add_argument("--query", "-q", help="Original query to refine", required=False)
    parser.add_argument("--list-frameworks", action="store_true", help="List available frameworks and exit")
    parser.add_argument("--trace", action="store_true", help="Enable verbose console tracing")
    parser.add_argument("--trace-dir", help="Write tracing operations and events to this directory")
    parser.add_argument("--log-dir", help="Directory for application logs (defaults to trace-dir when set)")
    
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

    try:
        manager = build_manager(
            enable_tracing=trace_enabled,
            trace_dir=args.trace_dir,
            log_dir=args.log_dir,
        )
    except RuntimeError as exc:
        print(f"Failed to initialise LLM provider: {exc}")
        return
    except ValueError as exc:
        print(f"Invalid LLM configuration: {exc}")
        return

    try:
        asyncio.run(run_cli(manager, framework_name, query))
    except KeyboardInterrupt:
        print("\n\n Session interrupted. Goodbye!")
    except asyncio.CancelledError:
        print("\n\n Session cancelled. Goodbye!")


if __name__ == "__main__":  # pragma: no cover
    main(sys.argv[1:])
