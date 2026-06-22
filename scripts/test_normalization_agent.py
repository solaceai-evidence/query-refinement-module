#!/usr/bin/env python3
"""Quick smoke-test for Agent A (Normalization) only."""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv
load_dotenv(ROOT / ".env", override=False)

from query_refinement_module.core import QueryRefinementManager
from query_refinement_module.providers import LiteLLMProvider
from query_refinement_module.schema.models import RefinementDimension
from query_refinement_module.session_models import RefinementSession
from query_refinement_module.settings import LLMSettings

MODEL = "ollama/qwen2.5:72b"

# Typos: "efect", "trainig", "muslce", "strenth", "patiens"
QUERY = (
    "What is the efect of resistance trainig programes on muslce strenth in older patiens?"
)

# Conflict: Population (dim 1) says "aged 65 and above";
#           Context (dim 5, later) says "aged 55 and above" — later wins.
DIMENSIONS = [
    ("population",   "Population",    "Who the study targets",
     "older adults aged 65 and above with no prior resistance training"),
    ("intervention", "Intervention",  "What is being tested",
     "progressive resistance training (PRT) programmes, 3 sessions per week for 12 weeks"),
    ("comparator",   "Comparator",    "Control or alternative",
     "sedentary control group with no structured exercise"),
    ("outcome",      "Outcome",       "What is measured",
     "muscle strength measured by 1-repetition maximum (1RM) test"),
    ("context",      "Context / setting", "Where the study takes place",
     "community-dwelling adults aged 55 and above in outpatient rehabilitation centres"),
    ("study_design", "Study design",  "Research methodology",
     "[SKIPPED]"),
]

# Expected behaviour:
#   - typos corrected in normalized_statement
#   - "aged 55 and above" (later dim) wins over "aged 65 and above" (earlier dim)
#   - all dimension values present in full


def build_session() -> RefinementSession:
    session = RefinementSession(original_query=QUERY)
    for dim_id, name, description, value in DIMENSIONS:
        rd = RefinementDimension(id=dim_id, name=name, description=description)
        session.add_step(rd)
        step = session.steps[-1]
        step.normalized_value = None if value == "[SKIPPED]" else value
        step.is_complete = True
    return session


async def main() -> None:
    settings = LLMSettings.from_env()
    settings.model = MODEL
    provider = LiteLLMProvider(**settings.as_provider_kwargs())
    manager = QueryRefinementManager(llm_provider=provider)

    print(f"Model: {MODEL}", flush=True)
    print(f"Query (with typos): {QUERY!r}\n", flush=True)

    session = build_session()
    norm, meta = await manager._run_normalization(session, model=MODEL, temperature=0.0)

    print("=== Agent A output ===")
    print(json.dumps(norm.model_dump(), indent=2, ensure_ascii=False))
    print("\n=== Metadata ===")
    print(json.dumps({"model": meta.get("model"), "total_tokens": meta.get("total_tokens"), "llm_duration_ms": meta.get("llm_duration_ms")}, indent=2))

    errors = []
    stmt = norm.normalized_statement.lower()

    if not norm.normalized_statement.strip():
        errors.append("normalized_statement is empty")

    # Typos must be corrected
    for typo in ("efect", "trainig", "programes", "muslce", "strenth", "patiens"):
        if typo in stmt:
            errors.append(f"typo not corrected: {typo!r} still present")

    # Conflict resolution: later dim (55+) must win over earlier dim (65+)
    if "55" not in stmt:
        errors.append("conflict resolution failed: '55' (later dim) not in normalized_statement")
    if "65" in stmt and "55" in stmt:
        # acceptable if model includes both with a note, but flag it for review
        print("  NOTE: both '65' and '55' appear — check conflict resolution manually")

    # All non-skipped dimension values must appear in full
    required_fragments = [
        "progressive resistance training",
        "1-repetition maximum",
        "sedentary control group",
        "outpatient rehabilitation centres",
        "3 sessions per week",
    ]
    for fragment in required_fragments:
        if fragment.lower() not in stmt:
            errors.append(f"dimension value fragment missing: {fragment!r}")

    if len(norm.dimensions_specifications) < len(DIMENSIONS):
        errors.append(
            f"dimensions_specifications has {len(norm.dimensions_specifications)} entries, "
            f"expected {len(DIMENSIONS)}"
        )

    print()
    if errors:
        print("FAIL — issues found:")
        for e in errors:
            print(f"  - {e}")
        sys.exit(1)
    else:
        print("PASS — all checks passed")


if __name__ == "__main__":
    asyncio.run(main())
