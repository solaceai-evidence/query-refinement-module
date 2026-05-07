#!/usr/bin/env python3
"""End-to-end evaluation for the pico_advanced framework with open-weight models.

Tests the complete refinement + synthesis pipeline:
  1. Dimension refinement — all 6 pico_advanced dims in dependency order,
     each receiving the real completed_context from prior dims.
  2. Synthesis — all completed dims passed to build_synthesis_messages(),
     response validated for structural correctness and key-term coverage.

Run:
    QUERY_REFINEMENT_LLM_COMPLETION_KWARGS='{"num_ctx": 8192}' \\
        .venv/bin/python scripts/evaluate_pico_advanced.py --model ollama/qwen2.5:72b

    # Use a specific env file (e.g. Claude):
    .venv/bin/python scripts/evaluate_pico_advanced.py \\
        --env-file .env.anthropic-claude-sonnet-4-6

    # Run a single scenario:
    .venv/bin/python scripts/evaluate_pico_advanced.py \\
        --model ollama/qwen2.5:72b --scenario 1
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]

_early_parser = argparse.ArgumentParser(add_help=False)
_early_parser.add_argument("--env-file", default=None)
_early_args, _ = _early_parser.parse_known_args()
_env_path = Path(_early_args.env_file) if _early_args.env_file else ROOT / ".env"
load_dotenv(_env_path, override=False)
os.environ.setdefault("QUERY_REFINEMENT_PROMPT_VARIANT", "open_llm")

import asyncio

from query_refinement_module.core import QueryRefinementManager
from query_refinement_module.providers import LiteLLMProvider
from query_refinement_module.schema.models import RefinementDimension, UserContext
from query_refinement_module.schema.prompt_builder import PromptBuilder
from query_refinement_module.session_models import AspectRefinementState, RefinementSession
from query_refinement_module.settings import LLMSettings

# ---------------------------------------------------------------------------
# pico_advanced framework definition (sourced from frameworks.yaml)
# Dimension order respects the dependency chain:
#   population → clinical_condition → intervention → comparator → outcome → study_type
# ---------------------------------------------------------------------------

PICO_USER_CONTEXT = UserContext(
    user_type="Systematic reviewer",
    context=(
        "Protocol development for systematic review or meta-analysis. "
        "Researcher is formulating a research question for a comprehensive evidence synthesis, "
        "requiring precise PICO framework specification for protocol registration."
    ),
    tone="professional",
    complexity="expert",
    examples_from="public health",
    constraints=[
        "Specificity check: Every dimension must have concrete, measurable definitions",
        "Alignment check: All dimensions must be mutually compatible",
        "Search-readiness check: Each element can be converted into specific database search terms",
        "Completeness check: All critical PICO elements defined without circular dependencies",
    ],
    pitfalls=[],
)

PICO_DIMENSIONS: list[dict[str, Any]] = [
    {
        "id": "population",
        "name": "Population",
        "description": (
            "The group of individuals, communities, or entities to whom the research applies, "
            "defined by demographic characteristics, geographic context, and relevant inclusion criteria."
        ),
        "strictness": "MODERATE",
        "depends_on": [],
        "specifications": (
            "**Task:** Evaluate and assemble population specification.\n\n"
            "**Elements to track:**\n"
            "- Age (range, category, or life stage)\n"
            "- Sex/gender\n"
            "- Ethnicity/race\n"
            "- Geographic setting or context\n"
            "- Relevant subgroup characteristics\n\n"
            "**Required:**\n"
            "- At least confirm whether 'all populations' or limited to specific demographics\n"
            "- Age specification if topic is age-dependent\n\n"
            "**Age standardization:**\n"
            "When assembling, standardize age terms: 'elderly' → 'older adults (65+ years)'"
        ),
    },
    {
        "id": "clinical_condition",
        "name": "Clinical Condition",
        "description": (
            "The health condition or disease under study, including its stage, severity, "
            "and relevant comorbidities."
        ),
        "strictness": "MODERATE",
        "depends_on": ["population"],
        "specifications": (
            "**Task:** Evaluate and assemble health condition specification.\n\n"
            "**Elements to track:**\n"
            "- Primary condition name\n"
            "- Disease stage (if applicable)\n"
            "- Severity (if applicable)\n"
            "- Relevant comorbidities (if applicable)\n\n"
            "**Required:**\n"
            "- Named condition is sufficient for MODERATE completeness\n"
            "- Extract from query, completed Population dimension, or conversation history"
        ),
    },
    {
        "id": "intervention",
        "name": "Intervention",
        "description": (
            "The healthcare action, exposure, or strategy being evaluated, specified in "
            "sufficient detail to allow replication."
        ),
        "strictness": "MODERATE",
        "depends_on": ["population", "clinical_condition"],
        "specifications": (
            "**Task:** Evaluate and assemble intervention specification.\n\n"
            "**Elements to track:**\n"
            "- Intervention type (pharmacological/procedural/behavioral/diagnostic)\n"
            "- Specific agent or method\n"
            "- Dosing/intensity (if relevant)\n"
            "- Duration (if relevant)\n\n"
            "**Required:**\n"
            "- Named intervention is sufficient for MODERATE completeness\n"
            "- Must be compatible with the Population and Clinical Condition dimensions\n\n"
            "**Important:** Extract ONLY the intervention being evaluated. "
            "Do NOT include the comparator (e.g. 'versus placebo'). "
            "The comparator will be captured in the separate Comparator dimension."
        ),
    },
    {
        "id": "comparator",
        "name": "Comparator",
        "description": (
            "The alternative intervention, standard of care, placebo, or no-intervention "
            "condition against which the intervention is evaluated."
        ),
        "strictness": "MODERATE",
        "depends_on": ["population", "intervention"],
        "specifications": (
            "**Task:** Evaluate and assemble comparator specification.\n\n"
            "**Elements to track:**\n"
            "- Comparator type (placebo/standard care/active comparator/no treatment)\n"
            "- Specific comparator details\n"
            "- Whether the comparison is head-to-head or against a passive control\n\n"
            "**Required:**\n"
            "- Named comparator is sufficient for MODERATE completeness"
        ),
    },
    {
        "id": "outcome",
        "name": "Outcome",
        "description": (
            "The measurable indicators, endpoints, or phenomena used to assess results, "
            "including health metrics, how they are measured, and the timeframe."
        ),
        "strictness": "MODERATE",
        "depends_on": ["population", "intervention", "comparator"],
        "specifications": (
            "**Task:** Evaluate and assemble outcome specification.\n\n"
            "**Elements to track:**\n"
            "- Primary outcome(s) or main variable(s) of interest\n"
            "- Outcome type (clinical, behavioral, attitudinal, system-level)\n"
            "- Measurement instrument or tool\n"
            "- Timeframe for measurement\n\n"
            "**Required for MODERATE completeness:**\n"
            "- Named outcome + HOW it will be measured\n"
            "- Timeframe if specified by user\n\n"
            "**NOT sufficient for MODERATE:**\n"
            "- Outcome name alone without measurement specification"
        ),
    },
    {
        "id": "study_type",
        "name": "Study Type",
        "description": (
            "The category of research methodology used to evaluate the intervention-outcome "
            "relationship, classified by design, randomisation, and control structure."
        ),
        "strictness": "MODERATE",
        "depends_on": ["population", "intervention", "comparator", "outcome"],
        "specifications": (
            "**Task:** Evaluate and assemble study design specification.\n\n"
            "**Elements to track:**\n"
            "- Primary study type (RCT, cohort, case-control, cross-sectional, etc.)\n"
            "- Secondary study types (systematic reviews, meta-analyses, etc.)\n"
            "- Blinding (if applicable)\n\n"
            "**Required:**\n"
            "- At least one study design specified\n"
            "- Named study type is sufficient for MODERATE completeness"
        ),
    },
]


# ---------------------------------------------------------------------------
# Scenario definition
# ---------------------------------------------------------------------------

@dataclass
class DimExpectation:
    """Expected refinement result for one dimension."""
    complete: bool
    current: str  # exact match (case-insensitive) when key_terms is empty
    key_terms: list[str] = field(default_factory=list)  # if non-empty, all terms must appear in actual.current
    check_complete: bool = True  # set False when completeness is borderline/defensible


@dataclass
class SynthesisCheck:
    """Minimal structural checks on synthesis output."""
    required_dim_ids: list[str]
    required_terms_in_integrated: list[str]   # all must appear (case-insensitive)
    required_fields: list[str] = field(default_factory=lambda: [
        "integrated_statement",
        "dimensions_specifications",
        "search_optimized",
        "search_filters",
        "terminology",
    ])


@dataclass
class Scenario:
    identifier: str
    name: str
    query: str
    # Per-dimension conversation history (keyed by dimension id)
    dim_history: dict[str, list[dict[str, str]]] = field(default_factory=dict)
    # Expected refinement outcome per dimension
    expected: dict[str, DimExpectation] = field(default_factory=dict)
    synthesis_check: SynthesisCheck | None = None


def build_scenarios() -> list[Scenario]:
    return [
        # ------------------------------------------------------------------
        # Scenario 1: Clean extraction — most dims extractable from query
        # One multi-turn for outcome (measurement required at MODERATE)
        # ------------------------------------------------------------------
        Scenario(
            identifier="1",
            name="Metformin RCT — extraction-heavy",
            query=(
                "Effect of metformin versus placebo on glycaemic control in adults aged 40-65 "
                "with type 2 diabetes in primary care settings — randomised controlled trials only"
            ),
            dim_history={
                # Outcome needs a measurement turn even though the concept is in the query
                "outcome": [
                    {
                        "question": "How will you measure glycaemic control, and over what timeframe?",
                        "response": "HbA1c reduction at 6 months",
                    }
                ],
            },
            expected={
                # Population: model may or may not include "primary care settings" —
                # key demographics must be present; setting inclusion is acceptable but not required.
                "population": DimExpectation(
                    complete=True,
                    check_complete=False,  # model may ask for setting clarification (defensible)
                    current="",
                    key_terms=["adults", "40-65", "type 2 diabetes"],
                ),
                "clinical_condition": DimExpectation(
                    complete=True,
                    current="type 2 diabetes",
                ),
                # Intervention: must contain "metformin" but NOT the comparator.
                "intervention": DimExpectation(
                    complete=True,
                    check_complete=False,  # model may ask for dosing (defensible at MODERATE)
                    current="",
                    key_terms=["metformin"],
                ),
                "comparator": DimExpectation(
                    complete=True,
                    current="placebo",
                ),
                # Outcome: model operationalises to HbA1c; that is correct.
                "outcome": DimExpectation(
                    complete=True,
                    current="",
                    key_terms=["HbA1c", "6 months"],
                ),
                "study_type": DimExpectation(
                    complete=True,
                    current="randomised controlled trials",
                ),
            },
            synthesis_check=SynthesisCheck(
                required_dim_ids=["population", "clinical_condition", "intervention",
                                  "comparator", "outcome", "study_type"],
                required_terms_in_integrated=["metformin", "placebo", "diabetes", "HbA1c"],
            ),
        ),
        # ------------------------------------------------------------------
        # Scenario 2: Multi-turn completions — most dims need conversation
        # ------------------------------------------------------------------
        Scenario(
            identifier="2",
            name="CBT vs waitlist — multi-turn",
            query="Can therapy help anxiety in young adults?",
            dim_history={
                "population": [
                    {
                        "question": "Which population are you focusing on?",
                        "response": "adults aged 18-35",
                    }
                ],
                "clinical_condition": [
                    {
                        "question": "Which anxiety disorder?",
                        "response": "generalised anxiety disorder (GAD)",
                    }
                ],
                "intervention": [
                    {
                        "question": "Which specific therapy?",
                        "response": "cognitive behavioural therapy (CBT)",
                    }
                ],
                "comparator": [
                    {
                        "question": "What will CBT be compared against?",
                        "response": "waitlist control",
                    }
                ],
                "outcome": [
                    {
                        "question": "What outcome will you measure?",
                        "response": "anxiety symptom severity",
                    },
                    {
                        "question": "How will you measure anxiety symptom severity?",
                        "response": "GAD-7 score at 12 weeks",
                    },
                ],
                "study_type": [
                    {
                        "question": "What study design?",
                        "response": "randomised controlled trials",
                    }
                ],
            },
            expected={
                "population": DimExpectation(
                    complete=True,
                    check_complete=False,  # model may ask for sex/ethnicity (defensible at MODERATE)
                    current="",
                    key_terms=["adults", "18-35"],
                ),
                "clinical_condition": DimExpectation(
                    complete=True,
                    current="",
                    # model sometimes appends population context — key terms are sufficient
                    key_terms=["generalised anxiety disorder", "GAD"],
                ),
                "intervention": DimExpectation(
                    complete=True,
                    check_complete=False,  # model may ask for session count (defensible at MODERATE)
                    current="",
                    key_terms=["cognitive behavioural therapy", "CBT"],
                ),
                "comparator": DimExpectation(complete=True, current="waitlist control"),
                "outcome": DimExpectation(
                    complete=True,
                    current="",
                    key_terms=["GAD-7", "12 weeks"],
                ),
                "study_type": DimExpectation(
                    complete=True, current="randomised controlled trials"
                ),
            },
            synthesis_check=SynthesisCheck(
                required_dim_ids=["population", "clinical_condition", "intervention",
                                  "comparator", "outcome", "study_type"],
                required_terms_in_integrated=["CBT", "anxiety", "GAD-7", "waitlist"],
            ),
        ),
    ]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fix_unescaped_quotes(s: str) -> str:
    """Escape unescaped double quotes inside JSON string values.

    Qwen sometimes emits boolean search strings like:
      "structured": "(("metformin" OR "placebo") AND ...)"
    where the inner quotes are not escaped, breaking the parser.
    This state machine detects whether a closing `"` is really the end of
    the current string value (next non-whitespace is : , } ]) or an inner
    quote (otherwise), and escapes the inner ones.
    """
    result: list[str] = []
    in_string = False
    i = 0
    while i < len(s):
        c = s[i]
        if c == "\\" and in_string:
            # Already-escaped sequence — pass both chars through unchanged
            result.append(c)
            i += 1
            if i < len(s):
                result.append(s[i])
                i += 1
            continue
        if c == '"':
            if not in_string:
                in_string = True
                result.append(c)
            else:
                # Decide: end-of-string or inner unescaped quote?
                j = i + 1
                while j < len(s) and s[j] in " \t\n\r":
                    j += 1
                if j >= len(s) or s[j] in ":,}]":
                    in_string = False
                    result.append(c)
                else:
                    result.append('\\"')
            i += 1
            continue
        result.append(c)
        i += 1
    return "".join(result)


def extract_json(text: str) -> dict[str, Any]:
    candidate = text.strip()
    if candidate.startswith("```"):
        candidate = re.sub(r"^```(?:json)?\s*", "", candidate)
        candidate = re.sub(r"\s*```$", "", candidate)
    start = candidate.find("{")
    end = candidate.rfind("}")
    if start == -1 or end == -1 or end < start:
        raise ValueError(f"No JSON object found: {text!r}")
    blob = candidate[start : end + 1]
    try:
        return json.loads(blob)
    except json.JSONDecodeError:
        # Try escaping unescaped inner quotes and retry
        return json.loads(_fix_unescaped_quotes(blob))


def _compare_refinement(
    actual: dict[str, Any], expected: DimExpectation
) -> tuple[bool, list[str]]:
    failures: list[str] = []
    required_keys = {"complete", "current", "question"}
    if set(actual.keys()) != required_keys:
        failures.append(f"json-shape expected {sorted(required_keys)} got {sorted(actual.keys())}")
    if expected.check_complete and actual.get("complete") != expected.complete:
        failures.append(
            f"complete expected {expected.complete!r} got {actual.get('complete')!r}"
        )
    actual_current = (actual.get("current") or "").strip().lower()
    if expected.key_terms:
        for term in expected.key_terms:
            if term.lower() not in actual_current:
                failures.append(f"current missing required term {term!r} (got {actual.get('current')!r})")
    else:
        expected_current = expected.current.strip().lower()
        if actual_current != expected_current:
            failures.append(
                f"current expected {expected.current!r} got {actual.get('current')!r}"
            )
    return (not failures), failures


def _compare_synthesis(
    actual: dict[str, Any], check: SynthesisCheck
) -> tuple[bool, list[str]]:
    failures: list[str] = []
    for f in check.required_fields:
        parts = f.split(".")
        obj = actual
        for p in parts:
            if not isinstance(obj, dict) or p not in obj:
                failures.append(f"missing field {f!r}")
                obj = None
                break
            obj = obj[p]

    integrated = actual.get("integrated_statement", "") or ""
    for term in check.required_terms_in_integrated:
        if term.lower() not in integrated.lower():
            failures.append(f"integrated_statement missing term {term!r}")

    dim_specs = actual.get("dimensions_specifications") or {}
    for dim_id in check.required_dim_ids:
        if dim_id not in dim_specs:
            failures.append(f"dimensions_specifications missing key {dim_id!r}")

    semantic = ""
    so = actual.get("search_optimized") or {}
    if isinstance(so, dict):
        semantic = so.get("semantic", "") or ""
    if not semantic.strip():
        failures.append("search_optimized.semantic is empty")

    return (not failures), failures


# ---------------------------------------------------------------------------
# Main runner
# ---------------------------------------------------------------------------

def run_scenario(
    scenario: Scenario,
    provider: LiteLLMProvider,
    builder: PromptBuilder,
    max_tokens_refinement: int,
    max_tokens_synthesis: int,
    verbose: bool,
) -> dict[str, Any]:
    """Run one full E2E scenario. Returns a result dict."""
    dim_results: list[dict[str, Any]] = []
    completed_context: list[dict[str, Any]] = []

    print(
        f"\n  Scenario {scenario.identifier}: {scenario.name}",
        file=sys.stderr,
        flush=True,
    )
    print(f"  Query: {scenario.query!r}", file=sys.stderr)

    all_refinement_passed = True

    for dim_def in PICO_DIMENSIONS:
        dim_id = dim_def["id"]
        exp = scenario.expected.get(dim_id)
        conv_history = scenario.dim_history.get(dim_id, [])

        # Build RefinementDimension with full pico context
        dimension = RefinementDimension(
            id=dim_id,
            name=dim_def["name"],
            description=dim_def["description"],
            specifications=dim_def["specifications"],
            strictness=dim_def["strictness"],
            depends_on=dim_def["depends_on"],
            user_context=PICO_USER_CONTEXT,
        )

        messages = builder.build_refinement_messages(
            dimension=dimension,
            query=scenario.query,
            conversation_history=conv_history,
            completed_context=completed_context,
            terminal_reinforcement_threshold=3,
        )

        print(
            f"    [{dim_id}] turns={len(conv_history)} completed_ctx={len(completed_context)} ...",
            file=sys.stderr,
            flush=True,
        )

        try:
            completion = provider.complete(
                messages=messages,
                max_tokens=max_tokens_refinement,
                temperature=0.0,
            )
            parsed = extract_json(completion.context)

            if exp is not None:
                passed, failures = _compare_refinement(parsed, exp)
            else:
                # No expectation — just check shape
                passed = set(parsed.keys()) == {"complete", "current", "question"}
                failures = [] if passed else [f"unexpected shape: {list(parsed.keys())}"]

            status = "PASS" if passed else "FAIL"
            print(f"      -> {status}: {failures if not passed else []}", file=sys.stderr)

            if not passed:
                all_refinement_passed = False

            # Record in completed_context for downstream dims using actual output
            completed_context.append(
                {
                    "id": dim_id,
                    "name": dim_def["name"],
                    "description": dim_def["description"],
                    "value": parsed.get("current") or "",
                    "was_skipped": False,
                }
            )

            dim_results.append(
                {
                    "dimension": dim_id,
                    "passed": passed,
                    "failures": failures,
                    "expected": {
                        "complete": exp.complete if exp else None,
                        "current": exp.current if exp else None,
                    },
                    "actual": parsed,
                    "raw": completion.context if verbose else None,
                }
            )

        except Exception as exc:
            msg = f"{type(exc).__name__}: {exc}"
            print(f"      -> ERROR: {msg}", file=sys.stderr)
            all_refinement_passed = False
            # Use empty value so downstream dims still receive the context key
            completed_context.append(
                {
                    "id": dim_id,
                    "name": dim_def["name"],
                    "description": dim_def["description"],
                    "value": "",
                    "was_skipped": False,
                }
            )
            dim_results.append(
                {
                    "dimension": dim_id,
                    "passed": False,
                    "failures": [f"execution error: {msg}"],
                    "expected": {
                        "complete": exp.complete if exp else None,
                        "current": exp.current if exp else None,
                    },
                    "actual": None,
                    "raw": None,
                }
            )

    # -----------------------------------------------------------------------
    # Synthesis
    # -----------------------------------------------------------------------
    synthesis_result: dict[str, Any] = {"passed": False, "failures": [], "actual": None, "raw": None}
    synthesis_raw: str | None = None

    print(f"    [synthesis] running split synthesis ...", file=sys.stderr, flush=True)

    try:
        # Build a RefinementSession from completed_context so we exercise the
        # same _run_split_synthesis path that production uses — NOT the legacy
        # monolithic build_synthesis_messages path.
        dim_objects = [
            RefinementDimension(
                id=d["id"],
                name=d["name"],
                description=d["description"],
                specifications=d["specifications"],
                strictness=d["strictness"],
                depends_on=d["depends_on"],
                user_context=PICO_USER_CONTEXT,
            )
            for d in PICO_DIMENSIONS
        ]
        dim_by_id = {d.id: d for d in dim_objects}

        session = RefinementSession(original_query=scenario.query)
        for entry in completed_context:
            aspect = dim_by_id.get(entry["id"])
            if aspect is None:
                continue
            state = AspectRefinementState(refinement_aspect=aspect)
            state.normalized_value = entry["value"] or None
            state.was_skipped = bool(entry.get("was_skipped", False))
            state.is_complete = True
            session.steps.append(state)

        manager = QueryRefinementManager(llm_provider=provider)

        synthesis_response, _ = asyncio.run(
            manager._run_split_synthesis(
                session,
                canonical_dimensions={
                    entry["id"]: entry["value"] if entry.get("value") else "[SKIPPED]"
                    for entry in completed_context
                },
                accepted_dimensions={
                    entry["id"]: entry["value"]
                    for entry in completed_context
                    if entry.get("value") and entry["value"] != "[SKIPPED]"
                },
                deterministic_filters=manager._assemble_deterministic_search_filters(session),
                temperature=0.0,
            )
        )
        parsed = synthesis_response.model_dump()

        if scenario.synthesis_check:
            passed, failures = _compare_synthesis(parsed, scenario.synthesis_check)
        else:
            passed = True
            failures = []

        status = "PASS" if passed else "FAIL"
        print(f"      -> {status}: {failures if not passed else []}", file=sys.stderr)

        synthesis_result = {
            "passed": passed,
            "failures": failures,
            "actual": parsed,
            "raw": None,
        }

    except Exception as exc:
        msg = f"{type(exc).__name__}: {exc}"
        print(f"      -> ERROR: {msg}", file=sys.stderr)
        synthesis_result = {
            "passed": False,
            "failures": [f"execution error: {msg}"],
            "actual": None,
            "raw": None,
        }

    scenario_passed = (
        all(r["passed"] for r in dim_results)
        and synthesis_result["passed"]
    )

    return {
        "id": scenario.identifier,
        "name": scenario.name,
        "query": scenario.query,
        "passed": scenario_passed,
        "dimensions": dim_results,
        "synthesis": synthesis_result,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="E2E evaluation for the pico_advanced framework."
    )
    parser.add_argument("--env-file", default=None, metavar="PATH")
    parser.add_argument(
        "--scenario",
        dest="scenarios",
        action="append",
        help="Scenario identifier to run (repeatable). Default: all.",
    )
    parser.add_argument("--model", help="Model override (e.g. ollama/qwen2.5:72b).")
    parser.add_argument(
        "--max-tokens-refinement",
        type=int,
        default=256,
        help="max_tokens for each refinement call (default 256).",
    )
    parser.add_argument(
        "--max-tokens-synthesis",
        type=int,
        default=4096,
        help="max_tokens for the synthesis call (default 4096).",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Include raw LLM response text in output JSON.",
    )
    args = parser.parse_args()

    builder = PromptBuilder()
    settings = LLMSettings.from_env()
    if args.model:
        settings.model = args.model
    provider = LiteLLMProvider(**settings.as_provider_kwargs())

    all_scenarios = build_scenarios()
    if args.scenarios:
        wanted = set(args.scenarios)
        all_scenarios = [s for s in all_scenarios if s.identifier in wanted]

    if not all_scenarios:
        print("No matching scenarios.", file=sys.stderr)
        return 2

    print(
        f"Running {len(all_scenarios)} scenario(s) | model={settings.model} | "
        f"variant={os.getenv('QUERY_REFINEMENT_PROMPT_VARIANT')}",
        file=sys.stderr,
        flush=True,
    )

    scenario_results: list[dict[str, Any]] = []
    for scenario in all_scenarios:
        result = run_scenario(
            scenario=scenario,
            provider=provider,
            builder=builder,
            max_tokens_refinement=args.max_tokens_refinement,
            max_tokens_synthesis=args.max_tokens_synthesis,
            verbose=args.verbose,
        )
        scenario_results.append(result)

    total = len(scenario_results)
    passed = sum(1 for r in scenario_results if r["passed"])
    failed = total - passed

    # Per-dimension totals across all scenarios
    dim_totals: dict[str, dict[str, int]] = {}
    for sr in scenario_results:
        for dr in sr["dimensions"]:
            dim_id = dr["dimension"]
            if dim_id not in dim_totals:
                dim_totals[dim_id] = {"passed": 0, "failed": 0}
            if dr["passed"]:
                dim_totals[dim_id]["passed"] += 1
            else:
                dim_totals[dim_id]["failed"] += 1

    synthesis_total = sum(1 for r in scenario_results if r["synthesis"]["passed"])

    summary = {
        "prompt_variant": os.getenv("QUERY_REFINEMENT_PROMPT_VARIANT"),
        "model": settings.model,
        "scenarios_total": total,
        "scenarios_passed": passed,
        "scenarios_failed": failed,
        "synthesis_passed": synthesis_total,
        "synthesis_total": total,
        "dimension_totals": dim_totals,
        "results": scenario_results,
    }

    print(json.dumps(summary, indent=2, ensure_ascii=True))
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
