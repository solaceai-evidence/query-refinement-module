import pytest

from query_refinement_module.schema import RefinementAspect


def _build_aspect(examples):
    """Create a minimal RefinementAspect for testing examples validation."""
    return RefinementAspect(
        id="demo",
        name="Demo",
        description="Demo description",
        specifications="Evaluate {query}",
        examples=examples,
    )


def test_examples_allow_other_category():
    """Test that 'other' category is allowed in examples."""
    examples = {
        "other": [
            {
                "statement": "Effectiveness for exactly 40-year-old women",
                "note": "Hyper-specific cohorts risk excluding nearby age bands.",
                "guidance": "Ask whether a broader age range is acceptable.",
            }
        ]
    }

    aspect = _build_aspect(examples)

    assert aspect.examples is not None
    # With Pydantic, examples is an ExamplesCollection object
    assert len(aspect.examples.other) == 1
    assert aspect.examples.other[0].note.startswith("Hyper-specific cohorts")


def test_examples_other_accepts_mixed_types():
    """Pydantic ExamplesCollection accepts extra fields with any type."""
    examples = {"other": [{"statement": "Example", "note": "A note", "custom": 42}]}

    aspect = _build_aspect(examples)
    assert aspect.examples is not None
    assert len(aspect.examples.other) == 1
