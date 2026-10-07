#!/usr/bin/env python3
"""Benchmark the synthesis pipeline (Agents A-C) on fixed scenarios.

Each scenario fixes the user's original question and the dimension values a
dialogue would have produced (``null`` = skipped), so differences between runs
come from the pipeline, not from the dialogue. For every run we record
deterministic search-readiness indicators (see ``schema.search_quality``):

- syntax validity and block/AND-group alignment
- redundant blocks (restating another block) and ungrounded blocks (no basis in user input)
- leakage of broadening/colloquial terms into the anchor query
- "no restriction" phrasing leaking into the clarified statement
- question coverage: share of the original question's content words present in the anchor query

Usage:
    poetry run python scripts/evaluate_search_quality.py --label baseline --repeat 2
    poetry run python scripts/evaluate_search_quality.py --label v2 --only copd_exercise_unrestricted

Results are written to eval_results/search_quality_<label>_<timestamp>.json.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import statistics
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env")

import query_refinement_module.api  # noqa: E402,F401  (import order avoids an application<->api cycle)
from query_refinement_module.api.dependencies import get_refinement_manager  # noqa: E402
from query_refinement_module.schema import registry  # noqa: E402
from query_refinement_module.schema.search_quality import (  # noqa: E402
    _content_stems,
    assess_search,
    user_source_text,
)
from query_refinement_module.session_models import RefinementSession  # noqa: E402

UNRESTRICTED_RE = re.compile(r"\b(no restrictions?|unrestricted|any setting|all ages|all genders|without restriction)\b", re.I)


def build_session(scenario: dict) -> RefinementSession:
    framework = registry.get_framework(scenario["framework"])
    session = RefinementSession(original_query=scenario["original_query"])
    session._complete_framework = list(framework)
    for aspect in framework:
        step = session.add_step(aspect)
        value = scenario["dimensions"].get(aspect.id)
        if value is None:
            step.was_skipped = True
        else:
            step.normalized_value = value
        step.is_complete = True
    return session


def _dump(value):
    if hasattr(value, "model_dump"):
        return value.model_dump()
    return value


def question_coverage(structured: str, original_query: str) -> float:
    """Share of the original question's content words present in the anchor query.

    Unlike "every dimension is in the query", this does not reward extra AND-blocks:
    it only checks that the user's own core concepts survived into the search.
    """
    wanted = _content_stems(original_query)
    if not wanted:
        return 1.0
    return len(wanted & _content_stems(structured)) / len(wanted)


async def run_one(manager, scenario: dict, semaphore: asyncio.Semaphore) -> dict:
    async with semaphore:
        started = time.monotonic()
        try:
            result = await manager.synthesize_refined_query(build_session(scenario))
        except Exception as exc:  # recorded as a reliability failure
            return {"id": scenario["id"], "error": f"{type(exc).__name__}: {exc}"}
        elapsed = time.monotonic() - started

    search_optimized = _dump(result.get("search_optimized")) or {}
    keyword = search_optimized.get("keyword") or {}
    structured = keyword.get("structured") or ""
    blocks = [_dump(block) for block in keyword.get("combined_blocks") or []]
    source = user_source_text(scenario["original_query"], scenario["dimensions"])
    quality = result.get("search_quality") or {}
    final_report = assess_search(structured, blocks, source_text=source, concept_graph=result.get("concept_graph"))

    return {
        "id": scenario["id"],
        "framework": scenario["framework"],
        "seconds": round(elapsed, 1),
        "clarified_query": result.get("clarified_query"),
        "structured": structured,
        "block_roles": [block.get("role") for block in blocks],
        "concept_count": len(result.get("concept_graph") or {}),
        "raw_report": quality.get("raw") or final_report,
        "repairs": quality.get("repairs") or [],
        "final_report": final_report,
        "unrestricted_in_statement": bool(UNRESTRICTED_RE.search(result.get("clarified_query") or "")),
        "coverage": round(question_coverage(structured, scenario["original_query"]), 2),
    }


def summarise(runs: list[dict]) -> dict:
    ok = [run for run in runs if "error" not in run]
    def rate(key_fn):
        return round(sum(1 for run in ok if key_fn(run)) / len(ok), 2) if ok else None
    return {
        "runs": len(runs),
        "errors": len(runs) - len(ok),
        "mean_blocks_raw": round(statistics.mean(run["raw_report"]["block_count"] for run in ok), 2) if ok else None,
        "mean_blocks_final": round(statistics.mean(run["final_report"]["block_count"] for run in ok), 2) if ok else None,
        "raw_search_ready_rate": rate(lambda run: run["raw_report"]["search_ready"]),
        "final_search_ready_rate": rate(lambda run: run["final_report"]["search_ready"]),
        "runs_with_redundant_block_raw": rate(lambda run: run["raw_report"]["redundant_blocks"]),
        "runs_with_ungrounded_block_raw": rate(lambda run: run["raw_report"]["ungrounded_blocks"]),
        "runs_with_leaked_terms_raw": rate(lambda run: run["raw_report"]["leaked_terms"]),
        "runs_with_syntax_problems_raw": rate(lambda run: run["raw_report"]["syntax_problems"]),
        "runs_repaired": rate(lambda run: run["repairs"]),
        "unrestricted_in_statement_rate": rate(lambda run: run["unrestricted_in_statement"]),
        "mean_coverage": round(statistics.mean(run["coverage"] for run in ok), 2) if ok else None,
        "mean_seconds": round(statistics.mean(run["seconds"] for run in ok), 1) if ok else None,
    }


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--label", required=True, help="Name for this run, e.g. baseline or v2")
    parser.add_argument("--repeat", type=int, default=1, help="Runs per scenario (LLM output varies)")
    parser.add_argument("--only", nargs="*", help="Scenario ids to run")
    parser.add_argument("--concurrency", type=int, default=3)
    parser.add_argument("--scenarios", default=str(ROOT / "scripts/eval_scenarios/search_quality.json"))
    args = parser.parse_args()

    scenarios = json.loads(Path(args.scenarios).read_text())
    if args.only:
        scenarios = [s for s in scenarios if s["id"] in set(args.only)]

    registry.reload_from_env(raise_on_error=True)
    manager = get_refinement_manager()
    semaphore = asyncio.Semaphore(args.concurrency)
    runs = await asyncio.gather(*[
        run_one(manager, scenario, semaphore) for scenario in scenarios for _ in range(args.repeat)
    ])

    summary = summarise(runs)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_dir = ROOT / "eval_results"
    out_dir.mkdir(exist_ok=True)
    out_path = out_dir / f"search_quality_{args.label}_{stamp}.json"
    out_path.write_text(json.dumps({
        "label": args.label,
        "created_at": stamp,
        "model": getattr(manager.llm_provider, "_default_model", None),
        "repeat": args.repeat,
        "summary": summary,
        "runs": runs,
    }, indent=2, ensure_ascii=False))

    print(f"\n{'scenario':38} {'blocks':>6} {'ready':>5} {'redund':>6} {'ungrnd':>6} {'leak':>4} {'cov':>4} {'repair':>6}")
    for run in runs:
        if "error" in run:
            print(f"{run['id']:38} ERROR {run['error'][:60]}")
            continue
        raw = run["raw_report"]
        print(
            f"{run['id']:38} {raw['block_count']:>6} {str(raw['search_ready'])[0]:>5} "
            f"{len(raw['redundant_blocks']):>6} {len(raw['ungrounded_blocks']):>6} "
            f"{sum(len(v) for v in raw['leaked_terms'].values()):>4} {run['coverage']:>4} {len(run['repairs']):>6}"
        )
    print("\nSummary:", json.dumps(summary, indent=2))
    print(f"\nWritten to {out_path.relative_to(ROOT)}")


if __name__ == "__main__":
    asyncio.run(main())
