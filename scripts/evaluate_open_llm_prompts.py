#!/usr/bin/env python3
"""Run the concrete open-LLM prompt cases against the real runtime prompt path.

This script uses:
- PromptBuilder.build_refinement_messages()
- the env-driven template selector in query_refinement_module.schema.templates
- LiteLLMProvider configured from .env

It does not wire the open-LLM templates into production automatically. Instead,
it forces QUERY_REFINEMENT_PROMPT_VARIANT=open_llm for this process so the
prompt pair can be evaluated in isolation.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]

# env file resolution: --env-file flag is parsed early so dotenv loads the right file
# before any module-level imports use the env.
_early_parser = argparse.ArgumentParser(add_help=False)
_early_parser.add_argument("--env-file", default=None)
_early_args, _ = _early_parser.parse_known_args()
_env_path = Path(_early_args.env_file) if _early_args.env_file else ROOT / ".env"
load_dotenv(_env_path, override=False)
os.environ.setdefault("QUERY_REFINEMENT_PROMPT_VARIANT", "open_llm")

from query_refinement_module.providers import LiteLLMProvider
from query_refinement_module.schema.models import CompletedDimension, RefinementDimension, UserContext
from query_refinement_module.schema.prompt_builder import PromptBuilder
from query_refinement_module.settings import LLMSettings


DEFAULT_USER_CONTEXT = UserContext(
    user_type="researcher",
    context="Clarifying a search specification",
    tone="professional",
    complexity="intermediate",
    examples_from="general",
    constraints=[],
    pitfalls=[],
)


@dataclass
class Case:
    identifier: str
    category: str
    name: str
    query: str
    dimension_name: str
    dimension_description: str
    specifications: str
    strictness: str | None = None
    conversation_history: list[dict[str, str]] = field(default_factory=list)
    completed_context: list[dict[str, Any]] = field(default_factory=list)
    depends_on: list[str] = field(default_factory=list)
    user_context: UserContext = field(default_factory=lambda: DEFAULT_USER_CONTEXT)
    expected_complete: bool = False
    expected_current: str = ""
    expected_question: str = ""
    ignore_question: bool = False  # skip question comparison when phrasing varies but content is acceptable


def _population_specs() -> str:
    return (
        "Determine the specific population for this query. Extract any valid population signal first. "
        "Complete only when the population is specific enough for the current strictness level."
    )


def _setting_specs() -> str:
    return (
        "Determine the setting or context. Extract setting information from the original query, completed "
        "dimensions, or the current turn before asking anything."
    )


def _outcome_specs() -> str:
    return (
        "Determine the outcome of interest. Extract the user's stated outcome first. If the outcome is named "
        "but not fully operationalized, keep it in current and ask only for the missing measurement detail."
    )


def _topic_specs() -> str:
    return "Determine the topic or domain. Extract established acronyms and topic phrases directly when present."


def _phase_specs() -> str:
    return (
        "Determine the phase, stage, or restriction. If the user indicates no restriction, preserve any prior "
        "anchor and mark the dimension complete."
    )


def build_cases() -> list[Case]:
    educational_novice = UserContext(
        user_type="student",
        context="Needs clear step-by-step help",
        tone="educational",
        complexity="novice",
        examples_from="public health",
        constraints=[],
        pitfalls=[],
    )

    return [
        Case(
            identifier="1",
            category="stable-fact inference",
            name="Stable fact inference: Ethiopia",
            query="rural displacement camps in northeastern Ethiopia",
            dimension_name="Setting",
            dimension_description="Geographic or institutional setting",
            specifications=_setting_specs(),
            strictness="moderate",
            expected_complete=True,
            expected_current="rural displacement camps in northeastern Ethiopia",
            expected_question="",
        ),
        Case(
            identifier="2",
            category="stable-fact inference",
            name="Stable fact inference: COPD acronym",
            query="barriers to implementing COPD management protocols",
            dimension_name="Topic/Domain",
            dimension_description="Research topic or domain",
            specifications=_topic_specs(),
            strictness="moderate",
            expected_complete=True,
            expected_current="COPD management protocols",
            expected_question="",
        ),
        Case(
            identifier="3",
            category="reference resolution",
            name="Echo reference: both",
            query="prevention or treatment approaches",
            dimension_name="Investigative Focus",
            dimension_description="Which focus areas matter",
            specifications="Determine which focus areas the user wants included.",
            strictness="moderate",
            conversation_history=[
                {
                    "question": "Are you interested in prevention or treatment? Or both?",
                    "response": "both",
                }
            ],
            expected_complete=True,
            expected_current="prevention and treatment",
            expected_question="",
        ),
        Case(
            identifier="4",
            category="reference resolution",
            name="Labeled multi-reference",
            query="implementation research priorities",
            dimension_name="Investigative Focus",
            dimension_description="Which aspects are in scope",
            specifications="Determine which aspects the user wants included.",
            strictness="moderate",
            conversation_history=[
                {
                    "question": "What aspects interest you? (a) identifying barriers, (b) comparing across groups, (c) evaluating impact?",
                    "response": "option (a) and (b)",
                }
            ],
            expected_complete=True,
            expected_current="identifying barriers and comparing across groups",
            expected_question="",
        ),
        Case(
            identifier="5",
            category="reference resolution",
            name="Positional multi-reference",
            query="settings for service delivery",
            dimension_name="Setting",
            dimension_description="Which settings are in scope",
            specifications=_setting_specs(),
            strictness="moderate",
            conversation_history=[
                {
                    "question": "Which settings matter most? (1) primary care clinics (2) hospitals (3) community centers (4) mobile outreach units",
                    "response": "first and fourth options",
                }
            ],
            expected_complete=True,
            expected_current="primary care clinics and mobile outreach units",
            expected_question="",
        ),
        Case(
            identifier="6",
            category="opt-out handling",
            name="Opt-out: any age group",
            query="age restriction for the population",
            dimension_name="Population Age Restriction",
            dimension_description="Age-based population restriction",
            specifications="Determine any age restriction. If the user opts out of restricting age, mark complete.",
            strictness="moderate",
            conversation_history=[
                {
                    "question": "What age group should this focus on?",
                    "response": "any age group",
                }
            ],
            expected_complete=True,
            expected_current="any age group",
            expected_question="",
        ),
        Case(
            identifier="7",
            category="opt-out handling",
            name="Opt-out with prior anchor",
            query="heat stroke",
            dimension_name="Phase Restriction",
            dimension_description="Phase or stage restriction",
            specifications=_phase_specs(),
            strictness="moderate",
            conversation_history=[
                {
                    "question": "Which condition is this about?",
                    "response": "heat stroke",
                },
                {
                    "question": "Is there a specific phase or stage restriction?",
                    "response": "no specific phase",
                },
            ],
            expected_complete=True,
            expected_current="heat stroke (no phase restriction)",
            expected_question="",
        ),
        Case(
            identifier="8",
            category="carry-forward and extraction",
            name="Extract from original query",
            query="I want to evaluate the performance of our mobile app notification system for enterprise users",
            dimension_name="Target Group",
            dimension_description="Who the work focuses on",
            specifications="Determine the target group from the query or prior context before asking anything.",
            strictness="moderate",
            expected_complete=True,
            expected_current="enterprise users",
            expected_question="",
        ),
        Case(
            identifier="9",
            category="extraction vs examples",
            name="Partial user answer outside examples",
            query="barriers to implementing COPD management protocols",
            dimension_name="Outcome",
            dimension_description="How the outcome will be assessed",
            specifications=_outcome_specs(),
            strictness="moderate",
            conversation_history=[
                {
                    "question": "What outcomes will measure barriers? e.g., adoption rates, adherence scores, implementation time?",
                    "response": "protocol adoption and adherence",
                }
            ],
            expected_complete=False,
            expected_current="protocol adoption and adherence",
            expected_question="How will you measure protocol adoption and adherence?",
        ),
        Case(
            identifier="10",
            category="dependency handling",
            name="Dependency conflict",
            query="population alignment",
            dimension_name="Population",
            dimension_description="Population for the current dimension",
            specifications=_population_specs(),
            strictness="moderate",
            depends_on=["population_dependency"],
            completed_context=[
                {
                    "id": "population_dependency",
                    "name": "Population",
                    "description": "Foundational population",
                    "value": "adults aged 18-65 with type 2 diabetes",
                    "was_skipped": False,
                }
            ],
            conversation_history=[
                {
                    "question": "Which population should this dimension cover?",
                    "response": "children with type 1 diabetes",
                }
            ],
            expected_complete=False,
            expected_current="children with type 1 diabetes",
            expected_question="Your current answer conflicts with the dependency 'adults aged 18-65 with type 2 diabetes'. Which population should this dimension align with?",
        ),
        Case(
            identifier="11",
            category="strictness handling",
            name="Strictness: MODERATE extract first",
            query="depression outcomes",
            dimension_name="Outcome",
            dimension_description="Outcome measure",
            specifications=_outcome_specs(),
            strictness="moderate",
            conversation_history=[
                {
                    "question": "What outcome are you focusing on?",
                    "response": "depression severity",
                }
            ],
            expected_complete=False,
            expected_current="depression severity",
            expected_question="How will you measure depression severity?",
        ),
        Case(
            identifier="12",
            category="strictness handling",
            name="Strictness: STRICT operationalize",
            query="population needed",
            dimension_name="Population",
            dimension_description="Specific population",
            specifications=_population_specs(),
            strictness="strict",
            conversation_history=[
                {
                    "question": "Which specific population do you mean?",
                    "response": "people",
                }
            ],
            expected_complete=False,
            expected_current="people",
            expected_question="Which specific population do you mean?",
        ),
        Case(
            identifier="13",
            category="output format",
            name="Output format invalid trap",
            query="adults with diabetes",
            dimension_name="Population",
            dimension_description="Specific population",
            specifications=_population_specs(),
            strictness="strict",
            expected_complete=False,
            expected_current="adults with diabetes",
            expected_question="",  # phrasing varies; this case tests JSON shape only
            ignore_question=True,
        ),
        Case(
            identifier="14",
            category="completed-dimension extraction",
            name="Prior-context extraction",
            query="setting needed",
            dimension_name="Setting",
            dimension_description="Specific setting",
            specifications=_setting_specs(),
            strictness="moderate",
            completed_context=[
                {
                    "id": "population",
                    "name": "Population",
                    "description": "Population",
                    "value": "adults aged 18-65 with type 2 diabetes in urban clinics",
                    "was_skipped": False,
                }
            ],
            expected_complete=True,
            expected_current="urban clinics",
            expected_question="",
        ),
        Case(
            identifier="15",
            category="long-turn priority retention",
            name="Long-turn retention",
            query="service delivery settings",
            dimension_name="Setting",
            dimension_description="Specific setting",
            specifications=_setting_specs(),
            strictness="moderate",
            user_context=educational_novice,
            conversation_history=[
                {
                    "question": "What broad service area are you interested in?",
                    "response": "community health",
                },
                {
                    "question": "Should this focus on a single country or multiple countries?",
                    "response": "multiple countries",
                },
                {
                    "question": "Do you want adult services, child services, or both?",
                    "response": "both",
                },
                {
                    "question": "Which settings matter most? (a) primary care clinics (b) hospitals (c) community centers",
                    "response": "a and c",
                },
            ],
            expected_complete=True,
            expected_current="primary care clinics and community centers",
            expected_question="",
        ),
    ]


def build_dimension(case: Case) -> RefinementDimension:
    return RefinementDimension(
        id=f"case_{case.identifier}",
        name=case.dimension_name,
        description=case.dimension_description,
        specifications=case.specifications,
        strictness=case.strictness,
        depends_on=case.depends_on,
        user_context=case.user_context,
    )


def build_messages(builder: PromptBuilder, case: Case) -> list[dict[str, str]]:
    return builder.build_refinement_messages(
        dimension=build_dimension(case),
        query=case.query,
        conversation_history=case.conversation_history,
        completed_context=case.completed_context,
        terminal_reinforcement_threshold=3,
    )


def extract_json(text: str) -> dict[str, Any]:
    candidate = text.strip()
    if candidate.startswith("```"):
        candidate = re.sub(r"^```(?:json)?\s*", "", candidate)
        candidate = re.sub(r"\s*```$", "", candidate)
    start = candidate.find("{")
    end = candidate.rfind("}")
    if start == -1 or end == -1 or end < start:
        raise ValueError(f"No JSON object found in response: {text!r}")
    return json.loads(candidate[start:end + 1])


def _compare(actual: dict[str, Any], case: Case) -> tuple[bool, list[str]]:
    failures: list[str] = []

    expected_keys = {"complete", "current", "question"}
    actual_keys = set(actual)
    if actual_keys != expected_keys:
        failures.append(f"json-shape expected {sorted(expected_keys)} got {sorted(actual_keys)}")

    if actual.get("complete") != case.expected_complete:
        failures.append(f"complete expected {case.expected_complete!r} got {actual.get('complete')!r}")

    if actual.get("current") != case.expected_current:
        failures.append(f"current expected {case.expected_current!r} got {actual.get('current')!r}")

    if not case.ignore_question and actual.get("question") != case.expected_question:
        failures.append(f"question expected {case.expected_question!r} got {actual.get('question')!r}")

    return (not failures), failures


def iter_selected_cases(cases: Iterable[Case], selected: list[str] | None) -> list[Case]:
    if not selected:
        return list(cases)
    wanted = set(selected)
    return [case for case in cases if case.identifier in wanted]


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate open-LLM prompt cases against the live provider path.")
    parser.add_argument("--env-file", default=None, metavar="PATH", help="Path to .env file to load (default: .env in repo root).")
    parser.add_argument("--case", dest="cases", action="append", help="Case identifier to run (repeatable). Default: run all cases.")
    parser.add_argument("--model", help="Optional model override (for example: ollama/qwen2.5:32b).")
    parser.add_argument("--max-tokens", type=int, default=256, help="Completion max_tokens override.")
    args = parser.parse_args()

    builder = PromptBuilder()
    settings = LLMSettings.from_env()
    if args.model:
        settings.model = args.model
    provider = LiteLLMProvider(**settings.as_provider_kwargs())
    cases = iter_selected_cases(build_cases(), args.cases)

    if not cases:
        print("No matching cases selected.", file=sys.stderr)
        return 2

    results: list[dict[str, Any]] = []
    for case in cases:
        print(f"[{case.identifier}/15] Running: {case.name} ...", file=sys.stderr, flush=True)
        messages = build_messages(builder, case)
        try:
            completion = provider.complete(messages=messages, max_tokens=args.max_tokens, temperature=0.0)
            parsed = extract_json(completion.context)
            passed, failures = _compare(parsed, case)
            status = "PASS" if passed else "FAIL"
            print(f"  -> {status}: {failures if not passed else []}", file=sys.stderr, flush=True)
            results.append(
                {
                    "id": case.identifier,
                    "category": case.category,
                    "name": case.name,
                    "passed": passed,
                    "failures": failures,
                    "expected": {
                        "complete": case.expected_complete,
                        "current": case.expected_current,
                        "question": case.expected_question,
                    },
                    "actual": parsed,
                    "raw": completion.context,
                }
            )
        except Exception as exc:  # pragma: no cover - execution surface
            results.append(
                {
                    "id": case.identifier,
                    "category": case.category,
                    "name": case.name,
                    "passed": False,
                    "failures": [f"execution error: {type(exc).__name__}: {exc}"],
                    "expected": {
                        "complete": case.expected_complete,
                        "current": case.expected_current,
                        "question": case.expected_question,
                    },
                    "actual": None,
                    "raw": None,
                }
            )

    summary = {
        "prompt_variant": os.getenv("QUERY_REFINEMENT_PROMPT_VARIANT"),
        "model": settings.model,
        "total": len(results),
        "passed": sum(1 for result in results if result["passed"]),
        "failed": sum(1 for result in results if not result["passed"]),
        "results": results,
    }

    print(json.dumps(summary, indent=2, ensure_ascii=True))
    return 0 if summary["failed"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())