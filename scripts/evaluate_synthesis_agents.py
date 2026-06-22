#!/usr/bin/env python3
"""Per-agent evaluation for the 4-agent synthesis pipeline.

Tests Agents A (Normalization), B (Semantic Representation), C (Search Expansion),
and D (Search Construction) in sequence for each scenario, inspecting each
agent's output independently.

Run:
    LLM_COMPLETION_KWARGS='{"num_ctx": 8192}' \\
        .venv/bin/python scripts/evaluate_synthesis_agents.py --model ollama/qwen2.5:72b

    # Verbose — include full JSON output for each agent:
    .venv/bin/python scripts/evaluate_synthesis_agents.py \\
        --model ollama/qwen2.5:72b --verbose

    # Single scenario:
    .venv/bin/python scripts/evaluate_synthesis_agents.py \\
        --model ollama/qwen2.5:72b --scenario 2

    # From env file:
    .venv/bin/python scripts/evaluate_synthesis_agents.py \\
        --env-file .env.anthropic-claude-sonnet-4-6
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
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
os.environ.setdefault("PROMPT_VARIANT", "open_llm")

from query_refinement_module.core import QueryRefinementManager
from query_refinement_module.providers import LiteLLMProvider
from query_refinement_module.schema.models import RefinementDimension
from query_refinement_module.schema.response import (
    SearchExpansionContext,
    SearchExpansionInput,
)
from query_refinement_module.session_models import AspectRefinementState, RefinementSession
from query_refinement_module.settings import LLMSettings


# ---------------------------------------------------------------------------
# Scenario definitions
# ---------------------------------------------------------------------------

@dataclass
class Dimension:
    """One dimension for the scenario (id, name, description, value)."""
    id: str
    name: str
    description: str
    value: str  # None/empty string → skipped


@dataclass
class Scenario:
    identifier: str
    name: str
    domain: str
    query: str
    dimensions: list[Dimension]
    # Agent A checks
    a_required_terms_in_statement: list[str] = field(default_factory=list)
    # Agent B checks
    b_required_concept_roles: list[str] = field(default_factory=list)   # at least one concept with this query_role
    b_min_concepts: int = 4
    # Agent D checks
    d_required_terms_in_boolean: list[str] = field(default_factory=list)  # case-insensitive


def build_scenarios() -> list[Scenario]:
    return [
        # ------------------------------------------------------------------
        # Scenario 1: Healthcare — antibiotic-resistant bacteria in ICUs
        # Domain: biomedical (deliberately NOT PICO-labelled in the dims)
        # ------------------------------------------------------------------
        Scenario(
            identifier="1",
            name="Antibiotic resistance in ICU patients",
            domain="healthcare",
            query=(
                "What is the effect of antimicrobial stewardship programmes on "
                "antibiotic-resistant infections in adult ICU patients?"
            ),
            dimensions=[
                Dimension("population", "Population", "Who the study targets",
                          "adult patients in intensive care units"),
                Dimension("topic", "Topic / condition", "The clinical problem",
                          "antibiotic-resistant bacterial infections"),
                Dimension("intervention", "Intervention", "What is being tested",
                          "antimicrobial stewardship programmes"),
                Dimension("comparator", "Comparator", "Control or alternative",
                          "standard care without stewardship programme"),
                Dimension("outcome", "Outcome", "What is measured",
                          "incidence of antibiotic-resistant infections at 6 months"),
                Dimension("study_design", "Study design", "Research methodology",
                          "randomised controlled trials and quasi-experimental studies"),
            ],
            a_required_terms_in_statement=["antimicrobial stewardship", "antibiotic"],
            b_required_concept_roles=["population_or_entity", "topic_or_condition"],
            b_min_concepts=4,
            d_required_terms_in_boolean=["stewardship", "antibiotic"],
        ),
        # ------------------------------------------------------------------
        # Scenario 2: Education — digital technology in rural primary schools
        # Domain: education research
        # ------------------------------------------------------------------
        Scenario(
            identifier="2",
            name="Digital technology integration in rural schools",
            domain="education",
            query=(
                "How does the integration of digital technology affect learning "
                "outcomes in rural primary schools in low-income countries?"
            ),
            dimensions=[
                Dimension("population", "Population", "Who the study targets",
                          "primary school pupils aged 6-12 in rural low-income country settings"),
                Dimension("intervention", "Intervention / phenomenon", "What is being studied",
                          "integration of digital technology (tablets, laptops, educational software)"),
                Dimension("comparator", "Comparator", "Control condition",
                          "traditional classroom instruction without digital technology"),
                Dimension("outcome", "Outcome", "What is measured",
                          "student learning outcomes (literacy, numeracy scores)"),
                Dimension("context", "Context / setting", "Environmental factors",
                          "rural primary schools in sub-Saharan Africa and South Asia"),
                Dimension("study_design", "Study design", "Research methodology",
                          "randomised controlled trials, quasi-experimental designs, and longitudinal studies"),
            ],
            a_required_terms_in_statement=["digital technology", "rural", "learning outcomes"],
            b_required_concept_roles=["population_or_entity", "intervention_or_exposure_or_phenomenon"],
            b_min_concepts=4,
            d_required_terms_in_boolean=["digital", "rural"],
        ),
        # ------------------------------------------------------------------
        # Scenario 3: Environmental / energy policy — renewable energy adoption
        # Domain: environmental science and policy
        # ------------------------------------------------------------------
        Scenario(
            identifier="3",
            name="Renewable energy adoption barriers in developing countries",
            domain="environmental_policy",
            query=(
                "What barriers prevent the adoption of solar photovoltaic systems "
                "for electricity access in rural communities in developing countries?"
            ),
            dimensions=[
                Dimension("phenomenon", "Phenomenon", "The process being studied",
                          "barriers to adoption of solar photovoltaic (PV) systems"),
                Dimension("population", "Community type", "Who the study involves",
                          "rural off-grid communities in developing countries"),
                Dimension("context", "Geographic context", "Where the study applies",
                          "sub-Saharan Africa, South and Southeast Asia"),
                Dimension("outcome", "Outcome", "What is being evaluated",
                          "electricity access rates and energy poverty reduction"),
                Dimension("study_design", "Study design", "Research approach",
                          "mixed-methods: surveys, case studies, and econometric analyses"),
                Dimension("excluded", "Exclusion", "What is out of scope",
                          "[SKIPPED]"),
            ],
            a_required_terms_in_statement=["solar photovoltaic", "rural"],
            b_required_concept_roles=["population_or_entity", "intervention_or_exposure_or_phenomenon"],
            b_min_concepts=4,
            d_required_terms_in_boolean=["solar", "photovoltaic"],
        ),
    ]


# ---------------------------------------------------------------------------
# Session builder
# ---------------------------------------------------------------------------

def _build_session(scenario: Scenario) -> RefinementSession:
    """Construct a RefinementSession from a scenario definition."""
    session = RefinementSession(original_query=scenario.query)
    for dim in scenario.dimensions:
        rd = RefinementDimension(
            id=dim.id,
            name=dim.name,
            description=dim.description,
            specifications="",
        )
        state = AspectRefinementState(refinement_aspect=rd)
        if dim.value and dim.value.upper() != "[SKIPPED]":
            state.normalized_value = dim.value
            state.was_skipped = False
        else:
            state.normalized_value = None
            state.was_skipped = True
        state.is_complete = True
        session.steps.append(state)
    return session


# ---------------------------------------------------------------------------
# Checks
# ---------------------------------------------------------------------------

def _count_words(text: str) -> int:
    return len(text.split())


def check_agent_a(
    result: dict[str, Any],
    scenario: Scenario,
) -> tuple[bool, list[str]]:
    failures: list[str] = []
    stmt = result.get("normalized_statement") or ""
    dim_specs = result.get("dimensions_specifications") or {}

    if not stmt.strip():
        failures.append("normalized_statement is empty")
    else:
        for term in scenario.a_required_terms_in_statement:
            if term.lower() not in stmt.lower():
                failures.append(f"normalized_statement missing required term {term!r}")

    # The LLM receives dimension names (e.g., "Population") not IDs (e.g., "population"),
    # so dimension_specifications keys use names. We check count instead of exact IDs.
    expected_count = len(scenario.dimensions)
    actual_count = len(dim_specs)
    if actual_count < expected_count:
        failures.append(
            f"dimensions_specifications has {actual_count} entries, expected {expected_count}"
        )

    # Skipped dimensions should be null (check by value pattern rather than ID lookup)
    skipped_count = sum(1 for d in scenario.dimensions if not d.value or d.value.upper() == "[SKIPPED]")
    actual_null_count = sum(1 for v in dim_specs.values() if v is None)
    if skipped_count > 0 and actual_null_count < skipped_count:
        failures.append(
            f"Expected {skipped_count} null values for skipped dimensions, "
            f"got {actual_null_count}"
        )

    return (not failures), failures


def check_agent_b(
    result: dict[str, Any],
    scenario: Scenario,
) -> tuple[bool, list[str]]:
    failures: list[str] = []
    stmt = result.get("semantic_statement") or ""
    graph = result.get("concept_graph") or {}

    if not stmt.strip():
        failures.append("semantic_statement is empty")
    else:
        word_count = _count_words(stmt)
        if word_count < 20:
            failures.append(f"semantic_statement too short ({word_count} words, expected ≥20)")
        if word_count > 150:
            failures.append(f"semantic_statement too long ({word_count} words, expected ≤150)")

    if len(graph) < scenario.b_min_concepts:
        failures.append(
            f"concept_graph has {len(graph)} concepts, expected ≥{scenario.b_min_concepts}"
        )

    # Check all entries have query_role
    missing_role = [c for c, v in graph.items() if not (v.get("query_role") if isinstance(v, dict) else None)]
    if missing_role:
        failures.append(f"concepts missing query_role: {missing_role}")

    # Check required roles are present
    actual_roles = {
        (v.get("query_role") if isinstance(v, dict) else None)
        for v in graph.values()
    }
    for role in scenario.b_required_concept_roles:
        if role not in actual_roles:
            failures.append(f"concept_graph missing a concept with query_role={role!r}")

    # Check true_synonyms is a list (not a string) for all concepts
    for concept, entry in graph.items():
        if not isinstance(entry, dict):
            failures.append(f"concept_graph[{concept!r}] is not a dict")
            continue
        syns = entry.get("true_synonyms")
        if syns is not None and not isinstance(syns, list):
            failures.append(f"concept_graph[{concept!r}].true_synonyms is not a list")

    return (not failures), failures


def check_agent_c(
    levels: list[dict[str, Any]],
) -> tuple[bool, list[str]]:
    failures: list[str] = []
    if not levels:
        failures.append("expansion returned no levels at all (not even Level 0)")
        return False, failures

    # Level 0 must exist
    level_nums = [lv.get("level") for lv in levels]
    if 0 not in level_nums:
        failures.append("Level 0 (anchor) is missing from expansion results")

    # At least one generated level expected (L1 or higher)
    generated = [lv for lv in levels if (lv.get("level") or 0) >= 1]
    if not generated:
        failures.append("No generated expansion levels (only Level 0); model may have returned empty levels")

    required_fields = {"level", "label", "strategy", "search_query", "rationale"}
    for lv in levels:
        lv_num = lv.get("level", "?")
        missing = required_fields - set(lv.keys())
        if missing:
            failures.append(f"Level {lv_num} missing fields: {sorted(missing)}")
        if not (lv.get("search_query") or "").strip():
            failures.append(f"Level {lv_num} has empty search_query")
        if not (lv.get("rationale") or "").strip():
            failures.append(f"Level {lv_num} has empty rationale")
        strategy = lv.get("strategy") or ""
        valid_strategies = {"anchor", "lexical", "conceptual_single_aspect", "conceptual_multi_aspect", "indexing_variant"}
        if strategy and strategy not in valid_strategies:
            failures.append(f"Level {lv_num} has unknown strategy {strategy!r}")

    return (not failures), failures


def check_agent_d(
    result: dict[str, Any],
    scenario: Scenario,
) -> tuple[bool, list[str]]:
    failures: list[str] = []

    keyword = result.get("keyword") or {}
    structured = (keyword.get("structured") if isinstance(keyword, dict) else None) or ""
    phrases = (keyword.get("phrases") if isinstance(keyword, dict) else None) or []
    filters = result.get("search_filters") or {}

    if not structured.strip():
        failures.append("keyword.structured is empty")
    else:
        has_bool = any(op in structured.upper() for op in [" AND ", " OR ", " NOT "])
        if not has_bool:
            failures.append("keyword.structured contains no Boolean operators (AND/OR/NOT)")
        for term in scenario.d_required_terms_in_boolean:
            if term.lower() not in structured.lower():
                failures.append(f"keyword.structured missing required term {term!r}")

    if not isinstance(phrases, list) or len(phrases) == 0:
        failures.append("keyword.phrases is empty or not a list")
    else:
        for phrase in phrases:
            if not isinstance(phrase, str):
                failures.append(f"keyword.phrases contains non-string value: {phrase!r}")
                break

    if not filters:
        failures.append("search_filters is empty or missing")

    return (not failures), failures


# ---------------------------------------------------------------------------
# Per-scenario runner
# ---------------------------------------------------------------------------

def run_scenario(
    scenario: Scenario,
    manager: QueryRefinementManager,
    model: str,
    verbose: bool,
) -> dict[str, Any]:
    print(f"\n  Scenario {scenario.identifier}: {scenario.name} ({scenario.domain})", file=sys.stderr, flush=True)
    print(f"  Query: {scenario.query!r}", file=sys.stderr)

    results: dict[str, Any] = {
        "id": scenario.identifier,
        "name": scenario.name,
        "domain": scenario.domain,
        "query": scenario.query,
        "agents": {},
        "passed": False,
    }

    # ── Agent A ──────────────────────────────────────────────────────────
    print("    [Agent A] Research Statement Normalization ...", file=sys.stderr, flush=True)
    try:
        session = _build_session(scenario)
        norm, meta_a = asyncio.run(
            manager._run_normalization(session, model=model, temperature=0.0)
        )
        norm_dict = norm.model_dump()
        passed_a, failures_a = check_agent_a(norm_dict, scenario)
        status = "PASS" if passed_a else "FAIL"
        print(f"      -> {status}: {failures_a if not passed_a else []}", file=sys.stderr)
        results["agents"]["A"] = {
            "passed": passed_a,
            "failures": failures_a,
            "output": norm_dict if verbose else {
                "research_statement": norm.normalized_statement,
                "dimension_count": len(norm.dimensions_specifications),
            },
            "metadata": meta_a,
        }
    except Exception as exc:
        msg = f"{type(exc).__name__}: {exc}"
        print(f"      -> ERROR: {msg}", file=sys.stderr)
        results["agents"]["A"] = {"passed": False, "failures": [f"execution error: {msg}"], "output": None}
        results["passed"] = False
        return results

    # ── Agent B ──────────────────────────────────────────────────────────
    print("    [Agent B] Semantic Representation ...", file=sys.stderr, flush=True)
    try:
        sem, meta_b = asyncio.run(
            manager._run_semantic_representation(
                norm.normalized_statement,
                norm.dimensions_specifications,
                model=model,
                temperature=0.0,
            )
        )
        sem_dict = sem.model_dump()
        concept_graph_serialized = {
            c: (e.model_dump() if hasattr(e, "model_dump") else e)
            for c, e in sem.concept_graph.items()
        }
        passed_b, failures_b = check_agent_b(
            {"semantic_statement": sem.semantic_statement, "concept_graph": concept_graph_serialized},
            scenario,
        )
        status = "PASS" if passed_b else "FAIL"
        print(f"      -> {status}: {failures_b if not passed_b else []}", file=sys.stderr)
        results["agents"]["B"] = {
            "passed": passed_b,
            "failures": failures_b,
            "output": sem_dict if verbose else {
                "semantic_statement": sem.semantic_statement,
                "concept_count": len(sem.concept_graph),
                "concept_roles": {
                    c: (e.query_role if hasattr(e, "query_role") else (e.get("query_role") if isinstance(e, dict) else None))
                    for c, e in sem.concept_graph.items()
                },
            },
            "metadata": meta_b,
        }
    except Exception as exc:
        msg = f"{type(exc).__name__}: {exc}"
        print(f"      -> ERROR: {msg}", file=sys.stderr)
        results["agents"]["B"] = {"passed": False, "failures": [f"execution error: {msg}"], "output": None}
        results["passed"] = False
        return results

    # ── Agent D ──────────────────────────────────────────────────────────
    print("    [Agent D] Search Construction ...", file=sys.stderr, flush=True)
    construction = None
    try:
        concept_graph_for_d = {
            c: (e.model_dump() if hasattr(e, "model_dump") else e)
            for c, e in sem.concept_graph.items()
        }
        construction, meta_d = asyncio.run(
            manager._run_search_construction(
                research_statement=norm.normalized_statement,
                dimensions_specifications=norm.dimensions_specifications,
                semantic_statement=sem.semantic_statement,
                concept_graph=concept_graph_for_d,
                model=model,
                temperature=0.0,
                max_tokens=2048,
            )
        )
        construction_dict = construction.model_dump()
        passed_d, failures_d = check_agent_d(construction_dict, scenario)
        status = "PASS" if passed_d else "FAIL"
        print(f"      -> {status}: {failures_d if not passed_d else []}", file=sys.stderr)
        results["agents"]["D"] = {
            "passed": passed_d,
            "failures": failures_d,
            "output": construction_dict if verbose else {
                "keyword_structured_preview": (construction.keyword.structured or "")[:200],
                "phrase_count": len(construction.keyword.phrases),
                "grey_literature_populated": construction.grey_literature is not None,
            },
            "metadata": meta_d,
        }
    except Exception as exc:
        msg = f"{type(exc).__name__}: {exc}"
        print(f"      -> ERROR: {msg}", file=sys.stderr)
        results["agents"]["D"] = {"passed": False, "failures": [f"execution error: {msg}"], "output": None}

    # ── Agent C ──────────────────────────────────────────────────────────
    # Uses Agent D's structured query as the anchor; falls back to research_statement.
    print("    [Agent C] Search Expansion ...", file=sys.stderr, flush=True)
    try:
        concept_graph_for_c = {
            c: (e.model_dump() if hasattr(e, "model_dump") else e)
            for c, e in sem.concept_graph.items()
        }
        # Level 0 anchor is the normalized research statement (the "Exact clarified question"),
        # not Agent D's Boolean query. Both Agent C and Agent D are independent downstream
        # consumers of Agent B's concept_graph.
        anchor_query = norm.normalized_statement
        search_input = SearchExpansionInput(
            anchor_query=anchor_query,
            search_context=SearchExpansionContext(
                concept_graph=concept_graph_for_c,
            ),
            advisory_dimensions=norm.dimensions_specifications or {},
        )
        levels, meta_c = asyncio.run(
            manager.generate_search_expansion_levels(
                search_input=search_input,
                model=model,
                temperature=0.0,
                max_tokens=2048,
            )
        )
        levels_dicts = [lv.model_dump() if hasattr(lv, "model_dump") else lv for lv in levels]
        passed_c, failures_c = check_agent_c(levels_dicts)
        status = "PASS" if passed_c else "FAIL"
        print(f"      -> {status}: {failures_c if not passed_c else []} ({len(levels_dicts)} levels)", file=sys.stderr)
        results["agents"]["C"] = {
            "passed": passed_c,
            "failures": failures_c,
            "output": levels_dicts if verbose else [
                {"level": lv.get("level"), "strategy": lv.get("strategy"), "label": lv.get("label")}
                for lv in levels_dicts
            ],
            "metadata": meta_c,
        }
    except Exception as exc:
        msg = f"{type(exc).__name__}: {exc}"
        print(f"      -> ERROR: {msg}", file=sys.stderr)
        results["agents"]["C"] = {"passed": False, "failures": [f"execution error: {msg}"], "output": None}

    agent_passes = [v.get("passed", False) for v in results["agents"].values()]
    results["passed"] = all(agent_passes)
    return results


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(
        description="Per-agent evaluation for the 4-agent synthesis pipeline."
    )
    parser.add_argument("--env-file", default=None, metavar="PATH")
    parser.add_argument("--model", help="Model override (e.g. ollama/qwen2.5:72b).")
    parser.add_argument(
        "--scenario",
        dest="scenarios",
        action="append",
        help="Scenario identifier to run (repeatable). Default: all.",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Include full agent output JSON in results.",
    )
    args = parser.parse_args()

    settings = LLMSettings.from_env()
    if args.model:
        settings.model = args.model
    provider = LiteLLMProvider(**settings.as_provider_kwargs())
    manager = QueryRefinementManager(llm_provider=provider)

    all_scenarios = build_scenarios()
    if args.scenarios:
        wanted = set(args.scenarios)
        all_scenarios = [s for s in all_scenarios if s.identifier in wanted]

    if not all_scenarios:
        print("No matching scenarios.", file=sys.stderr)
        return 2

    print(
        f"Evaluating 4-agent synthesis pipeline | model={settings.model} | "
        f"scenarios={len(all_scenarios)} | variant={os.getenv('PROMPT_VARIANT')}",
        file=sys.stderr,
        flush=True,
    )

    scenario_results: list[dict[str, Any]] = []
    for scenario in all_scenarios:
        result = run_scenario(
            scenario=scenario,
            manager=manager,
            model=settings.model,
            verbose=args.verbose,
        )
        scenario_results.append(result)

    # ── Summary ──────────────────────────────────────────────────────────
    total = len(scenario_results)
    passed = sum(1 for r in scenario_results if r["passed"])

    agent_totals: dict[str, dict[str, int]] = {}
    for sr in scenario_results:
        for agent_id, agent_result in sr.get("agents", {}).items():
            if agent_id not in agent_totals:
                agent_totals[agent_id] = {"passed": 0, "failed": 0}
            if agent_result.get("passed"):
                agent_totals[agent_id]["passed"] += 1
            else:
                agent_totals[agent_id]["failed"] += 1

    summary = {
        "model": settings.model,
        "prompt_variant": os.getenv("PROMPT_VARIANT"),
        "scenarios_total": total,
        "scenarios_passed": passed,
        "scenarios_failed": total - passed,
        "agent_totals": agent_totals,
        "results": scenario_results,
    }

    print(json.dumps(summary, indent=2, ensure_ascii=True))

    print(
        f"\nResult: {passed}/{total} scenarios passed | "
        + " | ".join(
            f"Agent {k}: {v['passed']}/{v['passed']+v['failed']}"
            for k, v in sorted(agent_totals.items())
        ),
        file=sys.stderr,
    )

    return 0 if passed == total else 1


if __name__ == "__main__":
    raise SystemExit(main())
