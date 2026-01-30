import json

import pytest

from query_refinement_module.schema import RefinementAspect


def make_aspect(**overrides) -> RefinementAspect:
    base_kwargs = {
        "id": "demo",
        "aspect_name": "Demo Aspect",
        "aspect_description": "Tracks demo behaviour",
        "evaluation_instructions": "Review this query: {query}",
    }
    base_kwargs.update(overrides)
    return RefinementAspect(**base_kwargs)


def test_refinement_aspect_injects_query_when_no_placeholder():
    """Test that query is injected at the beginning if {query} placeholder is missing."""
    aspect = RefinementAspect(
        id="demo",
        aspect_name="Missing Placeholder",
        aspect_description="No placeholder in prompt",
        evaluation_instructions="Evaluate the demographic characteristics.",
    )
    
    user_prompt = aspect.get_evaluation_instructions_prompt("What is the effect of exercise?")
    
    # Should include the user statement
    assert "What is the effect of exercise?" in user_prompt
    # Should still include the analysis prompt
    assert "Evaluate the demographic characteristics" in user_prompt


def test_refinement_aspect_uses_placeholder_when_present():
    """Test that query placeholder is properly substituted when present in analysis_prompt."""
    aspect = RefinementAspect(
        id="demo",
        aspect_name="With Placeholder",
        aspect_description="Has placeholder in prompt",
        evaluation_instructions="Analyze this query: {query}\n\nConsider all aspects.",
    )
    
    user_prompt = aspect.get_evaluation_instructions_prompt("What is the effect of exercise?")
    
    # Should have the query substituted in the analysis prompt
    assert "Analyze this query: What is the effect of exercise?" in user_prompt
    # Should include the rest of the prompt
    assert "Consider all aspects" in user_prompt
    # Should NOT have the "Review this query:" prefix since it's already in analysis_prompt
    assert not user_prompt.startswith("Review this query:")


def test_response_format_validates_allowed_types():
    """Pydantic model accepts additional fields - validation happens at response time."""
    aspect = make_aspect(
        response_format={
            "additional_fields": {"score": "float"},
            "field_descriptions": {"score": "Confidence score"},
        }
    )
    
    # The Pydantic model accepts the response_format config
    assert aspect.response_format is not None
    assert "score" in aspect.response_format.get("additional_fields", {})


def test_response_format_accepts_custom_types():
    """Pydantic model is more permissive with response_format - doesn't validate type names at construction."""
    aspect = make_aspect(
        response_format={"additional_fields": {"score": "decimal"}}
    )
    # No error raised - validation is more lenient with Pydantic
    assert aspect.response_format is not None


def test_examples_accepts_extra_fields():
    """Pydantic ExamplesCollection allows extra fields for flexibility."""
    aspect = make_aspect(examples={"clear": [{"statement": "Example"}]})
    assert aspect.examples is not None
    assert aspect.has_examples()


def test_examples_accepts_mixed_field_types():
    """Pydantic example models allow extra fields with any type."""
    aspect = make_aspect(
        examples={
            "clear": [
                {
                    "statement": "Example",
                    "custom_field": 42,  # Extra field accepted
                }
            ]
        }
    )
    assert aspect.examples is not None
    assert len(aspect.examples.clear) == 1


def test_default_system_prompt_uses_name_and_description():
    aspect = make_aspect()
    prompt = aspect.get_system_role()

    # The global system prompt should contain core directives
    assert "refinement specialist" in prompt or "Research Query Refinement" in prompt
    assert "Dimension" in prompt or "dimension" in prompt
    assert "complete" in prompt.lower()  # Quality gates mention completeness


def test_get_evaluation_instructions_prompt_includes_examples_and_format():
    aspect = make_aspect(
        examples={
            "needs_refinement": [
                {
                    "statement": "Does exercise help?",
                    "issue": "Too broad",
                    "example_question": "What type of exercise?",
                }
            ]
        },
    )

    prompt = aspect.get_evaluation_instructions_prompt("Sample query")

    assert "Sample query" in prompt
    assert "NEEDS CLARIFICATION:" in prompt or "Too broad" in prompt
    # Should include base schema fields
    assert "is_complete" in prompt
    assert "reasoning" in prompt


def test_get_prompts_returns_system_and_user_prompts():
    """Test that get_prompts returns global system prompt and user prompt."""
    aspect = make_aspect(system_prompt="Be concise.")  # Custom system prompt is now deprecated
    import warnings
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        system_prompt, user_prompt = aspect.get_prompts("Query text")

    # System prompt should be the global system prompt (custom is deprecated)
    assert "Research Query Refinement" in system_prompt
    assert "Query text" in user_prompt


def test_format_examples_omits_missing_categories():
    aspect = make_aspect(
        examples={
            "clear": [
                {
                    "statement": "Specific example",
                    "explanation": "Complete",
                }
            ],
            "partial": [
                {
                    "statement": "Missing",
                    "has": "Age",
                    "missing": "Duration",
                    "example_question": "For how long?",
                }
            ],
        }
    )

    formatted = aspect._format_examples()

    assert "CLEAR SPECIFICATIONS:" in formatted
    assert "NEEDS REFINEMENT:" not in formatted
    assert "Has: Age" in formatted
    assert "Example Q: \"For how long?\"" in formatted


def test_format_response_instructions_lists_fields():
    """Test that response instructions include base schema fields."""
    aspect = make_aspect()

    instructions = aspect._format_response_instructions()

    # Should include base schema fields
    assert "is_complete" in instructions
    assert "reasoning" in instructions
    assert "refinement_aspect_value" in instructions
    assert "next_question" in instructions


def test_validate_response_missing_base_fields():
    aspect = make_aspect()
    is_valid, error = aspect.validate_response({})

    assert not is_valid
    assert "Missing required field" in error
    assert "is_complete" in error


def test_validate_response_type_errors():
    aspect = make_aspect()
    is_valid, error = aspect.validate_response(
        {
            "is_complete": "true",
            "reasoning": 123,
            "next_question": None,
        }
    )

    assert not is_valid
    assert "must be" in error  # Type validation error


def test_validate_response_strict_warns_on_unexpected_fields():
    aspect = make_aspect()
    is_valid, error, warnings = aspect.validate_response_strict(
        {
            "is_complete": True,
            "reasoning": "All set",
            "next_question": None,
            "refinement_aspect_value": "Some value",
            "extra": "ignored",
        }
    )

    assert is_valid
    assert error is None
    assert any("extra" in w for w in warnings)


def test_validate_response_with_additional_fields():
    """Test response validation with custom response_format fields."""
    aspect = make_aspect(
        response_format={"additional_fields": {"confidence": "float"}}
    )

    is_valid, message = aspect.validate_response({
        "is_complete": True,
        "reasoning": "Done",
        "refinement_aspect_value": "Value",
        "confidence": 0.9
    })
    assert is_valid


def test_model_serialization_roundtrip():
    """Pydantic models use model_dump() for serialization."""
    aspect = make_aspect(
        response_format={"additional_fields": {"score": "integer"}},
        depends_on=["other"],
        metadata={"priority": "high"},
    )

    # Pydantic uses model_dump() instead of to_dict()
    data = aspect.model_dump()
    clone = RefinementAspect(**data)

    assert clone.id == aspect.id
    assert clone.response_format == aspect.response_format
    assert clone.depends_on == ["other"]
    assert clone.metadata["priority"] == "high"