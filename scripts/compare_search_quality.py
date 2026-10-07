#!/usr/bin/env python3
"""Rescore and compare stored search-quality benchmark runs with the current checks.

Usage:
    poetry run python scripts/compare_search_quality.py eval_results/search_quality_baseline_*.json eval_results/search_quality_v2_*.json
"""

from __future__ import annotations

import json
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from query_refinement_module.schema.search_quality import _content_stems, assess_search, split_top_level, user_source_text  # noqa: E402

SCENARIOS = {s["id"]: s for s in json.loads((ROOT / "scripts/eval_scenarios/search_quality.json").read_text())}


def rescore(path: Path) -> dict:
    data = json.loads(path.read_text())
    rows = []
    for run in data["runs"]:
        if "error" in run:
            rows.append({"error": True})
            continue
        scenario = SCENARIOS[run["id"]]
        source = user_source_text(scenario["original_query"], scenario["dimensions"])
        groups = split_top_level(run["structured"])
        raw = run["raw_report"]
        wanted = _content_stems(scenario["original_query"])
        rows.append({
            "raw_blocks": raw["block_count"],
            "final_groups": len(groups),
            "raw_ready": raw["search_ready"],
            "final_ready": run["final_report"]["search_ready"],
            "raw_aligned": raw["aligned"],
            "raw_redundant": bool(raw["redundant_blocks"]),
            "raw_ungrounded": bool(raw["ungrounded_blocks"]),
            "outcome_block_raw": "outcome" in (raw.get("block_roles") or []),
            "unrestricted_stmt": run["unrestricted_in_statement"],
            "question_coverage": len(wanted & _content_stems(run["structured"])) / len(wanted) if wanted else 1.0,
            "repaired": bool(run["repairs"]),
        })
    ok = [r for r in rows if "error" not in r]
    pct = lambda key: f"{100 * sum(1 for r in ok if r[key]) / len(ok):.0f}%"
    return {
        "label": data["label"],
        "runs": len(rows),
        "errors": len(rows) - len(ok),
        "AND-blocks, mean (raw from Agent C)": f"{statistics.mean(r['raw_blocks'] for r in ok):.1f}",
        "AND-blocks, mean (delivered)": f"{statistics.mean(r['final_groups'] for r in ok):.1f}",
        "search-ready (raw)": pct("raw_ready"),
        "search-ready (delivered)": pct("final_ready"),
        "blocks aligned with structured query": pct("raw_aligned"),
        "runs with redundant block": pct("raw_redundant"),
        "runs with ungrounded block": pct("raw_ungrounded"),
        "runs with outcome block": pct("outcome_block_raw"),
        "'no restriction' in statement": pct("unrestricted_stmt"),
        "original-question coverage, mean": f"{statistics.mean(r['question_coverage'] for r in ok):.2f}",
        "runs repaired": pct("repaired"),
    }


def main() -> None:
    results = [rescore(Path(arg)) for arg in sys.argv[1:]]
    keys = [k for k in results[0] if k != "label"]
    width = max(len(k) for k in keys)
    print(f"| {'metric':{width}} | " + " | ".join(r["label"] for r in results) + " |")
    print(f"|{'-' * (width + 2)}|" + "|".join("-" * (len(r["label"]) + 2) for r in results) + "|")
    for key in keys:
        print(f"| {key:{width}} | " + " | ".join(f"{str(r[key]):>{len(r['label'])}}" for r in results) + " |")


if __name__ == "__main__":
    main()
