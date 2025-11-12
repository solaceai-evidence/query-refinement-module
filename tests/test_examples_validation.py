import pytest

from query_refinement_module.schema.model import RefinementAspect


def _build_aspect(examples):
    """Create a minimal RefinementAspect for testing examples validation."""
    return RefinementAspect(
        id="demo",
        name="Demo",
        description="Demo description",
        analysis_prompt="Evaluate {query}",
        examples=examples,
    )


def test_examples_allow_other_category():
    examples = {
        "other": [
            {
                "query": "Effectiveness for exactly 40-year-old women",
                "note": "Hyper-specific cohorts risk excluding nearby age bands.",
                "guidance": "Ask whether a broader age range is acceptable.",
            }
        ]
    }

    aspect = _build_aspect(examples)

    assert aspect.examples is not None
    assert aspect.examples["other"][0]["note"].startswith("Hyper-specific cohorts")


def test_examples_other_rejects_non_string_values():
    examples = {"other": [{"query": "Example", "note": 42}]}

    with pytest.raises(ValueError):
        _build_aspect(examples)
