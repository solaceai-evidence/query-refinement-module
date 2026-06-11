#!/usr/bin/env python3
"""Benchmark split synthesis latency for local open-LLM runs.

Runs the production QueryRefinementManager synthesis path multiple times and
prints per-iteration timing plus median/mean summaries for the overall run,
each split call, and the post-statement overlap window.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path
from statistics import mean, median
from typing import Any

from dotenv import load_dotenv

from query_refinement_module.core import QueryRefinementManager, RefinementSession
from query_refinement_module.providers import LiteLLMProvider
from query_refinement_module.schema import RefinementAspect
from query_refinement_module.settings import LLMSettings


ROOT = Path(__file__).resolve().parents[1]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", default=None, help="Optional env file to load before building the provider")
    parser.add_argument("--iterations", type=int, default=3, help="Measured benchmark iterations")
    parser.add_argument("--warmup", type=int, default=1, help="Unreported warmup runs before measurements")
    parser.add_argument(
        "--query",
        default="What evidence exists on diabetes complications during heatwaves in pregnancy?",
        help="Original query used for synthesis",
    )
    parser.add_argument(
        "--dimension",
        action="append",
        default=[],
        metavar="ASPECT_ID=VALUE",
        help="Accepted dimension value to inject into the synthesis session. May be repeated.",
    )
    parser.add_argument(
        "--json-out",
        default=None,
        help="Optional path to write the full benchmark payload as JSON",
    )
    return parser.parse_args()


def _load_env(env_file: str | None) -> None:
    if env_file:
        load_dotenv(Path(env_file), override=False)
    else:
        load_dotenv(ROOT / ".env", override=False)
    os.environ.setdefault("PROMPT_VARIANT", "open_llm")


def _parse_dimensions(raw_dimensions: list[str]) -> dict[str, str]:
    if not raw_dimensions:
        return {
            "condition": "Diabetes complications during pregnancy under heatwave exposure",
        }

    parsed: dict[str, str] = {}
    for item in raw_dimensions:
        aspect_id, separator, value = item.partition("=")
        if not separator or not aspect_id.strip() or not value.strip():
            raise ValueError(f"Invalid --dimension value: {item!r}. Expected ASPECT_ID=VALUE.")
        parsed[aspect_id.strip()] = value.strip()
    return parsed


def _make_session(query: str, dimensions: dict[str, str]) -> RefinementSession:
    session = RefinementSession(original_query=query)
    for aspect_id, value in dimensions.items():
        aspect = RefinementAspect(
            id=aspect_id,
            name=aspect_id.replace("_", " ").title(),
            description=f"Benchmark dimension for {aspect_id.replace('_', ' ')}.",
            specifications=f"Normalize and preserve the user-approved {aspect_id.replace('_', ' ')} value.",
            allow_follow_up=True,
            max_follow_ups=3,
        )
        step = session.add_step(aspect)
        step.normalized_value = value
        step.is_complete = True
    return session


def _summarize_numeric(values: list[float]) -> dict[str, float]:
    return {
        "mean_ms": round(mean(values), 2),
        "median_ms": round(median(values), 2),
        "min_ms": round(min(values), 2),
        "max_ms": round(max(values), 2),
    }


async def _run_once(
    manager: QueryRefinementManager,
    query: str,
    dimensions: dict[str, str],
) -> dict[str, Any]:
    session = _make_session(query, dimensions)
    result = await manager.synthesize_refined_query(session)
    metadata = result.get("metadata") or {}
    return {
        "integrated_statement": result.get("integrated_statement"),
        "metadata": metadata,
    }


async def main() -> int:
    args = parse_args()
    _load_env(args.env_file)
    dimensions = _parse_dimensions(args.dimension)

    settings = LLMSettings.from_env(require_model=True, load_env_file=False)
    provider = LiteLLMProvider(**settings.as_provider_kwargs())
    manager = QueryRefinementManager(
        llm_provider=provider,
        default_temperature=settings.temperature,
        default_max_tokens=settings.max_tokens or 4096,
        terminal_reinforcement_threshold=settings.terminal_reinforcement_threshold,
    )

    total_runs = args.warmup + args.iterations
    measured_runs: list[dict[str, Any]] = []

    for index in range(total_runs):
        run = await _run_once(manager, args.query, dimensions)
        if index < args.warmup:
            print(f"warmup {index + 1}/{args.warmup}: {round((run['metadata'] or {}).get('duration_ms', 0), 2)} ms")
            continue
        measured_runs.append(run)
        iteration = len(measured_runs)
        metadata = run["metadata"] or {}
        overlap = ((metadata.get("parallel_timing") or {}).get("post_statement") or {}).get("overlap_window_ms", 0)
        print(
            f"iteration {iteration}/{args.iterations}: total={round(metadata.get('duration_ms', 0), 2)} ms, "
            f"overlap={round(overlap, 2)} ms"
        )

    totals = [float((run["metadata"] or {}).get("duration_ms", 0)) for run in measured_runs]
    overlap_windows = [
        float((((run["metadata"] or {}).get("parallel_timing") or {}).get("post_statement") or {}).get("overlap_window_ms", 0))
        for run in measured_runs
    ]

    call_names = ["statement", "semantic", "terminology", "filter_resolution", "keyword_support"]
    call_summaries: dict[str, dict[str, float]] = {}
    for call_name in call_names:
        durations = [
            float((((run["metadata"] or {}).get("call_timings") or {}).get(call_name) or {}).get("duration_ms", 0))
            for run in measured_runs
        ]
        call_summaries[call_name] = _summarize_numeric(durations)

    summary = {
        "model": settings.model,
        "prompt_variant": os.getenv("PROMPT_VARIANT", ""),
        "query": args.query,
        "dimensions": dimensions,
        "iterations": args.iterations,
        "warmup": args.warmup,
        "total_duration_ms": _summarize_numeric(totals),
        "post_statement_overlap_ms": _summarize_numeric(overlap_windows),
        "call_duration_ms": call_summaries,
        "runs": measured_runs,
    }

    print("\nSummary")
    print(json.dumps({
        "model": summary["model"],
        "total_duration_ms": summary["total_duration_ms"],
        "post_statement_overlap_ms": summary["post_statement_overlap_ms"],
        "call_duration_ms": summary["call_duration_ms"],
    }, indent=2))

    if args.json_out:
        output_path = Path(args.json_out)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
        print(f"\nWrote benchmark payload to {output_path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))