"""Async command-line interface for query refinement testing."""

from __future__ import annotations

from dotenv import load_dotenv

import argparse
import asyncio
import logging
import os
import sys
from typing import Any, Dict, Optional

from .core import QueryRefinementManager, is_user_command, parse_user_command
from .llm_model_defaults import get_model_defaults
from .logging_utils import configure_file_logging
from .providers import ConsoleTracing, FileTracingProvider, LiteLLMProvider
from .schema import registry
from .schema.response import (
    SearchExpansionInput,
)
from .settings import LLMSettings

load_dotenv(override=False)

logger = logging.getLogger(__name__)

def build_manager(
    *,
    enable_tracing: bool,
    trace_dir: Optional[str] = None,
    log_dir: Optional[str] = None,
    context_window: Optional[int] = None,
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
    settings = LLMSettings.from_env(load_env_file=True)
    _apply_context_window_override(settings, context_window)

    provider = LiteLLMProvider(**settings.as_provider_kwargs())
    # Analyzer is deprecated - don't create one by default
    # analyzer = LLMQueryAnalyzer(provider, **settings.as_analyzer_kwargs())

    return QueryRefinementManager(
        llm_provider=provider,
        tracing_provider=tracer,
        default_temperature=getattr(settings, "temperature", 0.0),
        default_max_tokens=getattr(settings, "max_tokens", 4096) or 4096,
        terminal_reinforcement_threshold=settings.terminal_reinforcement_threshold,
    )


def _apply_context_window_override(
    settings: LLMSettings,
    context_window: Optional[int],
) -> None:
    if context_window is None:
        return
    if context_window <= 0:
        raise ValueError("--context-window must be a positive integer")

    model_defaults = get_model_defaults(settings.model, api_base=settings.api_base)
    context_window_kwarg = model_defaults.context_window_kwarg
    if context_window_kwarg is None:
        raise ValueError(
            f"--context-window is not supported for model '{settings.model}'."
        )

    settings.completion_kwargs[context_window_kwarg] = context_window


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


def _is_accepted_dimension_value(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return value.strip() not in {"", "[SKIPPED]", "null"}
    return True


def _accepted_dimensions_from_session(session, fallback_dimensions: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    accepted: Dict[str, Any] = {}
    for step in getattr(session, "steps", []) or []:
        aspect = getattr(step, "refinement_aspect", None)
        aspect_id = getattr(aspect, "id", None)
        if not aspect_id:
            continue
        value = getattr(step, "normalized_value", None)
        if value is None:
            value = getattr(step, "normalized_value_as_str", None)
        if _is_accepted_dimension_value(value):
            accepted[aspect_id] = value

    if accepted or not fallback_dimensions:
        return accepted
    return {
        key: value
        for key, value in fallback_dimensions.items()
        if _is_accepted_dimension_value(value)
    }




def _build_search_expansion_input_from_synthesis(
    synthesis: Dict[str, Any],
) -> Optional[SearchExpansionInput]:
    """Build Agent D input from the synthesis dict.

    Returns None if combined_blocks are unavailable.
    """
    clarified_query = synthesis.get("clarified_query")
    if not clarified_query:
        return None

    search_optimized = synthesis.get("search_optimized")
    combined_blocks = None
    if search_optimized is not None:
        keyword = getattr(search_optimized, "keyword", None)
        if keyword is not None:
            combined_blocks = getattr(keyword, "combined_blocks", None)

    if not combined_blocks:
        return None

    concept_graph = synthesis.get("concept_graph") or {}

    # Agent B passthrough
    so = synthesis.get("search_optimized")
    semantic_statement = getattr(so, "semantic", "") or "" if so else ""
    keyword_statement_val = synthesis.get("keyword_statement") or ""

    # Agent C passthrough
    kw = getattr(so, "keyword", None) if so else None
    keyword_structured = getattr(kw, "structured", "") or "" if kw else ""
    phrases = list(getattr(kw, "phrases", None) or []) if kw else []
    search_filters = synthesis.get("search_filters")

    return SearchExpansionInput(
        clarified_query=clarified_query,
        anchor_blocks=combined_blocks,
        concept_graph=concept_graph,
        semantic_statement=semantic_statement,
        keyword_statement=keyword_statement_val,
        keyword_structured=keyword_structured,
        search_filters=search_filters,
        phrases=phrases,
    )


def _read_optional_input(prompt: str) -> str:
    try:
        return input(prompt)
    except (EOFError, StopIteration):
        return ""


def _resolve_numeric_examples(user_input: str, examples: Optional[list[str]]) -> tuple[str, bool]:
    """
    Resolve numeric input to example text.

    If user enters number(s) referencing examples (e.g., "1" or "1, 2" or "1."),
    convert to the actual example text(s). Otherwise return input as-is.

    Returns:
        (resolved_input, was_numeric): The resolved text and whether it was numeric input
    """
    if not examples:
        return user_input, False

    import re
    # Extract just the numeric part from tokens, handling "1", "1.", "1..", etc.
    numbers = re.findall(r'\d+', user_input.strip())

    if not numbers:
        return user_input, False

    # Check if input looks like numeric selection: should be mostly digits/dots/spaces/commas/list-words
    # This heuristic prevents misinterpreting "type 1 diabetes" as numeric reference
    cleaned = re.sub(r'\b(and|or)\b', '', user_input.strip(), flags=re.IGNORECASE)
    cleaned = re.sub(r'[\d\s,\.]+', '', cleaned)
    if cleaned:  # If anything other than digits/spaces/dots/commas/and/or remains
        return user_input, False

    # Try to resolve each number to an example (1-indexed)
    resolved = []
    for num_str in numbers:
        try:
            idx = int(num_str) - 1  # Convert 1-indexed to 0-indexed
            if 0 <= idx < len(examples):
                resolved.append(examples[idx])
            else:
                # Out of range - treat original input as not numeric
                return user_input, False
        except (ValueError, IndexError):
            return user_input, False

    if resolved:
        # Join multiple selections with a separator
        result = " | ".join(resolved) if len(resolved) > 1 else resolved[0]
        return result, True

    return user_input, False


def _print_search_expansion_levels(response) -> None:
    if response.recommended_starting_level and response.recommendation_rationale:
        print(f"recommended_starting_level: {response.recommended_starting_level}")
        print(f"recommendation_rationale: {response.recommendation_rationale}\n")

    if response.search_filters:
        sf = response.search_filters
        filter_parts = []
        years = getattr(sf, "publication_years", None) or (sf.get("publication_years") if isinstance(sf, dict) else None)
        types_ = getattr(sf, "publication_types", None) or (sf.get("publication_types") if isinstance(sf, dict) else None)
        if years:
            filter_parts.append(f"Years: {years}")
        if types_:
            filter_parts.append(f"Types: {', '.join(types_)}")
        if filter_parts:
            print(f"Filters: {' | '.join(filter_parts)}")

    if response.phrases:
        print(f"Key phrases: {', '.join(response.phrases[:6])}")

    print()

    for level in response.levels:
        tags = []
        if level.level == 0:
            tags.append("anchor")
        elif level.level == 1:
            tags.append("deterministic")
        if level.cochrane_compliant:
            tags.append("Cochrane-sensitive")
        tag_str = f" [{', '.join(tags)}]" if tags else ""
        print(f"Level {level.level} — {level.label}{tag_str}")
        print(f"  query:          {level.clarified_query}")
        if level.semantic_statement:
            print(f"  semantic_query: {level.semantic_statement[:120]}{'...' if len(level.semantic_statement) > 120 else ''}")
        if level.keyword_statement:
            print(f"  keyword_query:  {level.keyword_statement}")
        print(f"  boolean_query:  {level.search_query}")
        if level.controlled_vocabulary:
            for vocab_name, terms in level.controlled_vocabulary.items():
                print(f"  controlled_vocabulary.{vocab_name}: {', '.join(terms[:6])}" + (" …" if len(terms) > 6 else ""))
        if level.broadened_value and level.broadened_value != "(no restriction)":
            print(f"  broadened_aspect.{level.broadened_aspect}: {level.broadened_value}")
        print(f"  rationale:      {level.rationale}\n")

    if not response.levels:
        print("No expansion levels generated.\n")


async def _run_cli_search_expansion(
    manager: QueryRefinementManager,
    synthesis: Dict[str, Any],
) -> None:
    logger.info("CLI: starting Agent D search expansion")

    try:
        expansion_input = _build_search_expansion_input_from_synthesis(synthesis)
        if expansion_input is None:
            logger.warning(
                "CLI: Agent D search expansion unavailable because combined_blocks were missing"
            )
            print(
                "Search expansion unavailable: combined_blocks not available from synthesis output."
            )
            return

        expansion_response, metadata = await manager.generate_search_expansion_levels(
            search_input=expansion_input,
        )
    except Exception as exc:
        logger.warning("CLI: Agent D search expansion failed", exc_info=True)
        print(f"Warning: Agent D search expansion failed ({exc})")
        return

    logger.info(
        "CLI: Agent D search expansion completed",
        extra={
            "generated_level_count": metadata.get("generated_level_count", 0),
            "status": metadata.get("status"),
            "used_llm": metadata.get("used_llm"),
        },
    )
    print("─"*80)
    print("AGENT D — SEARCH EXPANSION LEVELS")
    print("─"*80)
    _print_search_expansion_levels(expansion_response)


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
            print(" Checking if clarification is needed...\n")
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
            current_examples: Optional[list[str]] = None  # Track examples for numeric resolution
            if result.examples:
                current_examples = result.examples
                for i, opt in enumerate(current_examples, 1):
                    print(f"  {i}. {opt}")
                print()

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
                            analysis_result = await manager.get_analysis_prompts(
                                session=session,
                                aspect_id=step.refinement_aspect.id,
                                mode=mode
                            )

                            status = manager.process_analysis_result(
                                session=session,
                                aspect_id=step.refinement_aspect.id,
                                result=analysis_result
                            )

                            if status['complete']:
                                print(f"✓ {header} is now complete")
                            else:
                                question = analysis_result.question
                                current_examples = analysis_result.examples or []
                                print(f"\n{question}\n")
                        except Exception as e:
                            print(f" Error regenerating question: {e}")
                    continue

                # Record answer (resolve numeric references to examples)
                if not question:
                    question = step.follow_up_question or f"Please provide details about {header}"
                resolved_input, was_numeric = _resolve_numeric_examples(user_input, current_examples)
                if was_numeric:
                    print(f"  → Selected: {resolved_input}")
                step.add_follow_up(question=question, response=resolved_input)

                # Selection from provided options is always complete — skip LLM eval loop
                if was_numeric:
                    step.is_complete = True
                    break

                # Run follow-up analysis
                print("\n Analyzing your answer...")
                try:
                    followup_result = await manager.run_followup_until_clear(
                        session,
                        aspect_id=step.refinement_aspect.id,
                        max_rounds=5
                    )

                    complete = followup_result.get('is_complete', False)
                    rounds = followup_result.get('rounds', 0)

                    if complete:
                        print(f"✓ {header} complete after {rounds} round(s)")
                        step.is_complete = True
                        break
                    else:
                        # Need more clarification
                        question = step.follow_up_question or f"Can you provide more details about {header}?"
                        print(f"\n{question}\n")
                        current_examples = step.quick_replies or []
                        if current_examples:
                            for i, opt in enumerate(current_examples, 1):
                                print(f"  {i}. {opt}")
                            print()

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
                logger.info("CLI: starting chained synthesis for Agents A-C")
                synthesis = await manager.synthesize_refined_query(session)
            except ValueError as exc:
                print(f"Error: {exc}")
            except Exception as exc:
                print(f"Error: {exc}")
            else:
                search_optimized = synthesis.get("search_optimized")
                keyword = getattr(search_optimized, "keyword", None) if search_optimized else None
                combined_blocks = getattr(keyword, "combined_blocks", None) if keyword else None
                concept_graph = synthesis.get("concept_graph") or {}
                logger.info(
                    "CLI: completed chained synthesis for Agents A-C",
                    extra={
                        "clarified_query_length": len(
                            (synthesis.get("clarified_query") or "").strip()
                        ),
                        "concept_graph_size": len(concept_graph),
                        "combined_block_count": len(combined_blocks or []),
                    },
                )
                clarified_query = synthesis.get("clarified_query", "").strip()
                if not clarified_query:
                    clarified_query = synthesis.get("refined_query", "").strip() or session.original_query

                # ── AGENT A — CLARIFIED RESEARCH STATEMENT ──────────────────
                print("\n" + "─"*80)
                print("AGENT A — CLARIFIED RESEARCH STATEMENT")
                print("─"*80)
                print(f"  {clarified_query}\n")

                dimension_values = synthesis.get("dimensions_specifications")
                if dimension_values:
                    print("Refined Dimensions:")
                    for aspect_id, value in dimension_values.items():
                        aspect = next(
                            (s.refinement_aspect for s in session.steps if s.refinement_aspect.id == aspect_id),
                            None,
                        )
                        aspect_name = aspect.name if aspect else aspect_id
                        if value is not None and value != "" and value != "[SKIPPED]" and value != "null":
                            print(f"  • {aspect_name}: {value}")
                    print()

                # ── AGENT B — SEMANTIC REPRESENTATION ────────────────────────
                print("─"*80)
                print("AGENT B — SEMANTIC REPRESENTATION")
                print("─"*80)

                if search_optimized:
                    semantic = search_optimized.semantic or ""
                    if semantic:
                        print(f"\nSemantic Query (dense / vector search):")
                        print(f"  {semantic}")

                keyword_statement = synthesis.get("keyword_statement") or ""
                if keyword_statement:
                    print(f"\nKeyword Query (BM25 / simple keyword search):")
                    print(f"  {keyword_statement}")

                if concept_graph:
                    print(f"\nConcept Graph ({len(concept_graph)} concept(s) extracted):")
                    for concept_name, entry in concept_graph.items():
                        role = entry.get("query_role") or "other" if isinstance(entry, dict) else "other"
                        print(f"  [{role:<42}]  {concept_name}")
                print()

                # ── AGENT C — SEARCH CONSTRUCTION ────────────────────────────
                print("─"*80)
                print("AGENT C — SEARCH CONSTRUCTION")
                print("─"*80)

                if search_optimized:
                    keyword = search_optimized.keyword
                    if keyword:
                        structured = keyword.structured or ""
                        if structured:
                            print(f"\nBoolean Query (anchor — sparse / keyword search):")
                            print(f"  {structured}")

                        phrases = keyword.phrases or []
                        if phrases:
                            print(f"\nKey Phrases:")
                            for phrase in phrases:
                                print(f"  • \"{phrase}\"")

                        terms = keyword.terms
                        if terms:
                            required = terms.required or []
                            optional = terms.optional or []
                            excluded = terms.excluded or []
                            if required:
                                print(f"\nRequired Terms: {', '.join(required)}")
                            if optional:
                                print(f"Optional Terms:  {', '.join(optional)}")
                            if excluded:
                                print(f"Excluded Terms:  {', '.join(excluded)}")

                        combined_blocks = keyword.combined_blocks or []
                        if combined_blocks:
                            print(f"\nCombined Blocks (source-specific query construction):")
                            for i, block in enumerate(combined_blocks, 1):
                                role = getattr(block, "role", "")
                                free_text = getattr(block, "free_text", []) or []
                                cv = getattr(block, "controlled_vocabulary", {}) or {}
                                print(f"\n  Block {i} [{role}]")
                                if free_text:
                                    print(f"    Free-text:  {', '.join(free_text)}")
                                for vocab_name, vocab_terms in cv.items():
                                    if vocab_terms:
                                        print(f"    {vocab_name + ':':<12}{', '.join(vocab_terms)}")

                search_filters = synthesis.get("search_filters")
                if search_filters:
                    filter_parts = []
                    if search_filters.publication_years:
                        filter_parts.append(f"Years: {search_filters.publication_years}")
                    if search_filters.publication_types:
                        filter_parts.append(f"Types: {', '.join(search_filters.publication_types)}")
                    if search_filters.fields_of_study:
                        filter_parts.append(f"Fields: {', '.join(search_filters.fields_of_study)}")
                    if search_filters.venues:
                        filter_parts.append(f"Venues: {', '.join(search_filters.venues)}")
                    if filter_parts:
                        print(f"\nSearch Filters:  {' | '.join(filter_parts)}")
                print()

                # ── AGENT D — SEARCH EXPANSION ────────────────────────────────
                await _run_cli_search_expansion(manager, synthesis)
                    
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
    parser.add_argument(
        "--context-window",
        "--num-ctx",
        dest="context_window",
        type=int,
        help="Override the model context window for this CLI run only",
        required=False,
    )
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

    build_manager_kwargs = {
        "enable_tracing": trace_enabled,
        "trace_dir": args.trace_dir,
        "log_dir": args.log_dir,
    }
    if getattr(args, "context_window", None) is not None:
        build_manager_kwargs["context_window"] = args.context_window

    try:
        manager = build_manager(**build_manager_kwargs)
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
