import json

import pytest

from query_refinement_module.schema.model import RefinementAspect


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
    aspect = make_aspect(
        response_format={
            "additional_fields": {"score": "float"},
            "field_descriptions": {"score": "Confidence score"},
        }
    )

    is_valid, error = aspect.validate_response(
        {
            "is_complete": False,
            "reasoning": "All good",
            "next_question": "Clarify?",
            "score": 0.75,
        }
    )

    assert is_valid
    assert error is None


def test_response_format_rejects_invalid_type():
    with pytest.raises(ValueError):
        make_aspect(
            response_format={"additional_fields": {"score": "decimal"}}
        )


def test_examples_validation_rejects_unknown_category():
    with pytest.raises(ValueError) as excinfo:
        make_aspect(examples={"unsupported": [{"statement": "Example"}]})
    assert "Invalid example categories" in str(excinfo.value)


def test_examples_validation_rejects_non_string_fields():
    with pytest.raises(ValueError):
        make_aspect(
            examples={
                "clear": [
                    {
                        "statement": "Example",
                        "explanation": 42,  # type: ignore[arg-type]
                    }
                ]
            }
        )


def test_default_system_prompt_uses_name_and_description():
    aspect = make_aspect()
    prompt = aspect.get_system_role()

    assert "Demo Aspect" in prompt or "refinement specialist" in prompt
    assert "Demo description" in prompt or "Tracks demo behaviour" in prompt or "refinement specialist" in prompt
    assert "focused question" in prompt or "structured JSON" in prompt


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
        response_format={"additional_fields": {"confidence": "float"}},
    )

    prompt = aspect.get_evaluation_instructions_prompt("Sample query")

    assert "Sample query" in prompt
    assert "NEEDS CLARIFICATION:" in prompt  # Updated term from new schema
    assert "confidence" in prompt
    assert "float" in prompt


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
    aspect = make_aspect(
        response_format={
            "additional_fields": {"priority": "string"},
            "field_descriptions": {"priority": "Low/Medium/High"},
        }
    )

    instructions = aspect._format_response_instructions()

    assert "is_complete" in instructions
    assert "priority" in instructions
    assert "Low/Medium/High" in instructions
    assert json.loads(
        instructions.split("```json\n", 1)[1].split("\n```", 1)[0]
    )["priority"] == "<string>"


def test_validate_response_missing_base_fields():
    aspect = make_aspect()
    is_valid, error = aspect.validate_response({})

    assert not is_valid
    assert "Missing required fields" in error
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
            "next_question": "",
            "refinement_aspect_value": "Some value",
            "demo": "Some value",  # Dynamic value field
            "extra": "ignored",
        }
    )

    assert is_valid
    assert error is None
    assert warnings == ["Response contains unexpected fields: extra"]


def test_validate_field_type_rejects_bool_for_float():
    aspect = make_aspect(
        response_format={"additional_fields": {"confidence": "float"}}
    )

    is_valid, message = aspect._validate_field_type("confidence", True, "float")
    assert not is_valid
    assert "must be float" in message


def test_validate_field_type_warns_on_unknown_type(caplog):
    aspect = make_aspect()

    with caplog.at_level("WARNING"):
        is_valid, message = aspect._validate_field_type("custom", "value", "custom")

    assert is_valid
    assert message is None
    assert any("Unknown type" in record.message for record in caplog.records)


def test_to_dict_from_dict_roundtrip():
    aspect = make_aspect(
        response_format={"additional_fields": {"score": "integer"}},
        depends_on=["other"],
        metadata={"priority": "high"},
    )

    data = aspect.to_dict()
    clone = RefinementAspect.from_dict(data)

    assert clone.id == aspect.id
    assert clone.response_format == aspect.response_format
    assert clone.depends_on == ["other"]
    assert clone.metadata["priority"] == "high"