#!/usr/bin/env python3
"""Interaction-style comparison test.

Runs the same query and dimension through every combination of tone × complexity
and prints the model's question side-by-side, so you can verify that:
  - Tone controls register/framing (warmth, directness, consequence-framing)
  - Complexity controls vocabulary and explanation depth
  - Each combination produces visibly distinct output

Run:
    QUERY_REFINEMENT_LLM_COMPLETION_KWARGS='{"num_ctx": 8192}' \\
        .venv/bin/python scripts/evaluate_interaction_styles.py --model ollama/qwen2.5:72b

    .venv/bin/python scripts/evaluate_interaction_styles.py \\
        --env-file .env.anthropic-claude-sonnet-4-6
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]

_early_parser = argparse.ArgumentParser(add_help=False)
_early_parser.add_argument("--env-file", default=None)
_early_parser.add_argument("--model", default=None)
_early_args, _ = _early_parser.parse_known_args()
_env_path = Path(_early_args.env_file) if _early_args.env_file else ROOT / ".env"
load_dotenv(_env_path, override=False)
# Styles test uses production templates (no open_llm variant)
os.environ.pop("QUERY_REFINEMENT_PROMPT_VARIANT", None)

sys.path.insert(0, str(ROOT))

from query_refinement_module.providers import LiteLLMProvider
from query_refinement_module.schema.models import RefinementDimension, UserContext
from query_refinement_module.schema.prompt_builder import PromptBuilder
from query_refinement_module.settings import LLMSettings

# ---------------------------------------------------------------------------
# Test fixture: partial population info with required elements still missing —
# forces the model to acknowledge what it has, explain gaps, and frame a
# follow-up question. That full response is where register (tone) and depth
# (complexity) manifest.
# ---------------------------------------------------------------------------

QUERY = (
    "I want to study the effectiveness of antidepressants in middle-aged adults "
    "attending primary care clinics — I think around 40 to 60 year olds but I'm not "
    "sure whether to include both men and women or just focus on women."
)

DIMENSION = RefinementDimension(
    id="population",
    name="Population",
    description=(
        "The group of individuals defined by demographic characteristics, "
        "geographic context, and relevant inclusion criteria."
    ),
    depends_on=[],
    specifications=(
        "**Task:** Evaluate and assemble population specification.\n\n"
        "**Elements to track:**\n"
        "- Age (range, category, or life stage)\n"
        "- Sex/gender\n"
        "- Ethnicity/race\n"
        "- Geographic setting or context\n"
        "- Relevant subgroup characteristics\n\n"
        "**Required:**\n"
        "- Age range: must be explicitly confirmed\n"
        "- Sex/gender: must be specified (inclusive or restricted)\n"
        "- Setting: clinical, community, or other — must be named\n\n"
        "**Not required unless raised:**\n"
        "- Ethnicity/race\n"
    ),
)

# ---------------------------------------------------------------------------
# Tone × Complexity combinations to test
# ---------------------------------------------------------------------------

COMBOS = [
    # (tone, complexity, label)
    ("educational", "intermediate",  "educational × intermediate"),
    ("educational", "advanced",      "educational × advanced"),
    ("professional", "intermediate", "professional × intermediate"),
    ("professional", "expert",       "professional × expert"),
    ("pragmatic",    "advanced",     "pragmatic × advanced"),
    ("pragmatic",    "expert",       "pragmatic × expert"),
]

BASE_USER_CONTEXT = dict(
    user_type="Researcher",
    context="Conducting a literature review on depression interventions.",
    examples_from="mental health",
    constraints=[],
    pitfalls=[],
)


def extract_json(text: str) -> dict:
    text = text.strip()
    # strip markdown fences
    if "```" in text:
        import re
        m = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
        if m:
            text = m.group(1).strip()
    # find outermost braces
    start = text.find("{")
    end = text.rfind("}") + 1
    if start == -1 or end == 0:
        raise ValueError(f"No JSON object found in: {text[:200]}")
    return json.loads(text[start:end])


def run_combo(
    tone: str,
    complexity: str,
    label: str,
    provider: LiteLLMProvider,
    builder: PromptBuilder,
) -> dict:
    ctx = UserContext(tone=tone, complexity=complexity, **BASE_USER_CONTEXT)
    dim = RefinementDimension(
        id=DIMENSION.id,
        name=DIMENSION.name,
        description=DIMENSION.description,
        depends_on=DIMENSION.depends_on,
        specifications=DIMENSION.specifications,
        user_context=ctx,
    )
    messages = builder.build_refinement_messages(
        dimension=dim,
        query=QUERY,
        conversation_history=[],
        completed_context=[],
        terminal_reinforcement_threshold=3,
    )
    raw = provider.complete(messages=messages, max_tokens=512, temperature=0.0).context
    try:
        parsed = extract_json(raw)
        question = parsed.get("question", "")
        complete = parsed.get("complete", None)
        current = parsed.get("current", "")
    except Exception as e:
        question = f"[PARSE ERROR: {e}] raw={raw[:300]}"
        complete = None
        current = ""
    return {
        "label": label,
        "tone": tone,
        "complexity": complexity,
        "complete": complete,
        "current": current,
        "question": question,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Compare interaction style outputs")
    parser.add_argument("--model", default=None, help="Override LLM model")
    parser.add_argument("--env-file", default=None)
    args = parser.parse_args()

    settings = LLMSettings.from_env()
    if args.model:
        settings.model = args.model

    provider = LiteLLMProvider(**settings.as_provider_kwargs())
    builder = PromptBuilder()

    results = []
    for tone, complexity, label in COMBOS:
        print(f"\n[running] {label} ...", flush=True)
        result = run_combo(tone, complexity, label, provider, builder)
        results.append(result)
        print(f"  complete={result['complete']}  current={result['current']!r}")
        print(f"  question: {result['question']}")

    # ---------------------------------------------------------------------------
    # Summary: tone groups (does tone visibly affect register?)
    # ---------------------------------------------------------------------------
    print("\n" + "=" * 72)
    print("QUESTION TEXT BY COMBINATION")
    print("=" * 72)
    for r in results:
        print(f"\n[{r['label']}]")
        print(f"  Q: {r['question']}")

    # ---------------------------------------------------------------------------
    # Automated checks
    # ---------------------------------------------------------------------------
    print("\n" + "=" * 72)
    print("AUTOMATED STYLE CHECKS")
    print("=" * 72)

    failures = []

    # Warmth markers — educational tone should contain affirmations or rationale
    WARM_MARKERS = [
        "make sense", "helpful", "understand", "matter", "because", "important",
        "helps", "allows", "ensure", "so that", "to help", "this means",
        "great", "good", "you've", "i can see",
    ]
    DIRECT_MARKERS = ["specify", "define", "clarify", "provide", "indicate", "confirm"]
    CONSEQUENCE_MARKERS = [
        "without this", "search will", "retrieval", "enables", "allow",
        "otherwise", "this will", "result in", "impact", "affect", "limiting",
    ]
    TECHNICAL_TERMS = [
        "demographic", "eligibility", "inclusion criteria", "specification",
        "operationaliz", "age range", "stratum", "subgroup", "cohort",
        "restriction", "stratif", "sex-specific", "sex/gender",
        "primary care", "setting", "clinical",
    ]

    for r in results:
        q = r["question"].lower()
        label = r["label"]
        tone = r["tone"]
        complexity = r["complexity"]

        if tone == "educational":
            if not any(m in q for m in WARM_MARKERS):
                failures.append(
                    f"[{label}] WARN — expected warm/rationale framing in educational tone. "
                    f"No marker found in: {r['question'][:120]}"
                )
        if tone == "professional":
            # Professional = direct imperative, minimal warmth
            if any(m in q for m in ["i notice", "just to make sure", "that makes sense"]):
                failures.append(
                    f"[{label}] WARN — unexpected warmth in professional tone: {r['question'][:120]}"
                )
        if tone == "pragmatic":
            if not any(m in q for m in CONSEQUENCE_MARKERS):
                failures.append(
                    f"[{label}] WARN — expected consequence-framing in pragmatic tone. "
                    f"No marker found in: {r['question'][:120]}"
                )

        # Expert complexity should use more technical terms than intermediate
        if complexity == "expert":
            if not any(t in q for t in TECHNICAL_TERMS):
                failures.append(
                    f"[{label}] WARN — expected technical vocabulary at expert complexity. "
                    f"No term found in: {r['question'][:120]}"
                )

    # Uniqueness check — no two questions should be identical
    questions = [r["question"].strip() for r in results]
    seen = {}
    for i, q in enumerate(questions):
        if q in seen:
            failures.append(
                f"[{results[i]['label']}] FAIL — identical question as [{results[seen[q]]['label']}]"
            )
        seen[q] = i

    if failures:
        print("\nISSUES FOUND:")
        for f in failures:
            print(f"  {f}")
    else:
        print("\nAll style checks passed.")

    # JSON output
    output = {
        "model": settings.model,
        "query": QUERY,
        "dimension": DIMENSION.id,
        "results": results,
        "style_check_failures": failures,
        "style_checks_passed": len(failures) == 0,
    }
    print("\n" + json.dumps(output, indent=2))


if __name__ == "__main__":
    main()
