#!/usr/bin/env python3
"""Print framework prompts from a refinement frameworks YAML file.

This utility prints, for each selected framework:
1) Global directive system prompt (once)
2) User context system prompt (once)
3) The full message payload for each dimension as built by runtime workflow

Important:
- Per-dimension payloads are generated through RefinementSession + step.get_messages,
    which is the same path used before LLM submission.
- To let downstream dependencies render, the script marks prior dimensions complete
    with placeholder assembled values after printing each dimension.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import Dict, Iterable, List, TextIO


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Print prompts for refinement frameworks from a YAML file. "
            "Outputs global directive once, user context once, then all dimensions."
        )
    )
    parser.add_argument(
        "yaml_path",
        help="Path to refinement frameworks YAML file",
    )
    parser.add_argument(
        "--framework",
        dest="framework_name",
        default=None,
        help="Optional framework name to print (default: print all frameworks in file)",
    )
    parser.add_argument(
        "--output",
        "-o",
        dest="output_path",
        default=None,
        help="Optional output file path (.txt). If omitted, prints to stdout.",
    )
    parser.add_argument(
        "--query",
        dest="original_query",
        default="<original query placeholder>",
        help="Original query used in user message payload construction.",
    )
    parser.add_argument(
        "--terminal-threshold",
        dest="terminal_threshold",
        type=int,
        default=3,
        help="Terminal reinforcement threshold passed to runtime message builder.",
    )
    return parser


def _print_block(out: TextIO, title: str, content: str) -> None:
    print("\n" + "=" * 100, file=out)
    print(title, file=out)
    print("=" * 100, file=out)
    print(content.strip() if content else "", file=out)


def _iter_frameworks(selected: str | None, available: Iterable[str]) -> List[str]:
    names = list(available)
    if selected:
        if selected not in names:
            raise ValueError(
                f"Framework '{selected}' not found. Available: {', '.join(names) if names else 'none'}"
            )
        return [selected]
    return names


def _render_payload(messages: List[Dict[str, str]]) -> str:
    lines: List[str] = []
    for idx, msg in enumerate(messages, start=1):
        role = msg.get("role", "unknown")
        cache_mark = msg.get("_cache", False)
        lines.append(f"--- MESSAGE {idx} | role={role} | cache={cache_mark} ---")
        lines.append(msg.get("content", ""))
        lines.append("")
    return "\n".join(lines).rstrip()


def main() -> int:
    parser = _build_parser()
    args = parser.parse_args()

    yaml_path = Path(args.yaml_path).expanduser().resolve()
    if not yaml_path.exists():
        print(f"Error: YAML file not found: {yaml_path}", file=sys.stderr)
        return 1

    os.environ["REFINEMENT_FRAMEWORK_PATH"] = str(yaml_path)

    try:
        from query_refinement_module.schema.registry import (
            FrameworkLoadError,
            get_framework,
            list_frameworks,
            reload_from_env,
        )
        from query_refinement_module.schema.prompt_builder import PromptBuilder
        from query_refinement_module.session_models import RefinementSession
    except Exception as exc:
        print(f"Error importing query refinement modules: {exc}", file=sys.stderr)
        return 1

    try:
        reload_from_env(raise_on_error=True)
    except FrameworkLoadError as exc:
        print(f"Error loading frameworks: {exc}", file=sys.stderr)
        return 1

    builder = PromptBuilder()

    try:
        target_frameworks = _iter_frameworks(args.framework_name, list_frameworks())
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    if not target_frameworks:
        print("No frameworks found in the provided YAML file.", file=sys.stderr)
        return 1

    out: TextIO
    output_file = None
    if args.output_path:
        output_path = Path(args.output_path).expanduser().resolve()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_file = output_path.open("w", encoding="utf-8")
        out = output_file
    else:
        out = sys.stdout

    try:
        for framework_name in target_frameworks:
            aspects = get_framework(framework_name)
            if not aspects:
                continue

            session = RefinementSession(original_query=args.original_query)
            for aspect in aspects:
                session.add_step(aspect)

            print("\n" + "#" * 100, file=out)
            print(f"FRAMEWORK: {framework_name}", file=out)
            print("#" * 100, file=out)

            _print_block(out, "GLOBAL DIRECTIVE SYSTEM PROMPT", builder.get_global_system_prompt())

            user_context = aspects[0].user_context if aspects else None
            user_context_rendered = (
                builder.render_user_context(user_context) if user_context is not None else "[No user context]"
            )
            _print_block(out, "USER CONTEXT SYSTEM PROMPT", user_context_rendered)

            for index, step in enumerate(session.steps, start=1):
                aspect = step.refinement_aspect
                dependency_context = session.get_dependency_context(aspect.id)
                messages = step.get_messages(
                    query=session.original_query,
                    dependency_context=dependency_context,
                    terminal_reinforcement_threshold=args.terminal_threshold,
                )

                _print_block(
                    out,
                    f"DIMENSION {index}: {aspect.id} | FULL LLM MESSAGE PAYLOAD",
                    _render_payload(messages),
                )

                # Mark current step as completed with placeholder so downstream
                # dependent dimensions receive context through real runtime logic.
                if not step.is_complete:
                    step.is_complete = True
                if step.normalized_value is None and not step.was_skipped:
                    step.normalized_value = f"<assembled value for {aspect.id}>"
    finally:
        if output_file is not None:
            output_file.close()

    if args.output_path:
        print(f"Wrote prompt output to: {output_path}", file=sys.stderr)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
