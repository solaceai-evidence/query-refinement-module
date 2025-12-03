import json

import pytest

from query_refinement_module.schema.model import RefinementAspect


def make_aspect(**overrides) -> RefinementAspect:
    base_kwargs = {
        "id": "demo",
        "name": "Demo Aspect",
        "description": "Tracks demo behaviour",
        "analysis_prompt": "Review this query: {query}",
    }
    base_kwargs.update(overrides)
    return RefinementAspect(**base_kwargs)


def test_refinement_aspect_injects_query_when_no_placeholder():
    """Test that query is injected at the beginning if {query} placeholder is missing."""
    aspect = RefinementAspect(
        id="demo",
        name="Missing Placeholder",
        description="No placeholder in prompt",
        analysis_prompt="Evaluate the demographic characteristics.",
    )
    
    user_prompt = aspect.get_user_prompt("What is the effect of exercise?")
    
    # Should start with explicit query statement
    assert user_prompt.startswith("Review this query: What is the effect of exercise?")
    # Should still include the analysis prompt
    assert "Evaluate the demographic characteristics" in user_prompt


def test_refinement_aspect_uses_placeholder_when_present():
    """Test that query placeholder is properly substituted when present in analysis_prompt."""
    aspect = RefinementAspect(
        id="demo",
        name="With Placeholder",
        description="Has placeholder in prompt",
        analysis_prompt="Analyze this query: {query}\n\nConsider all aspects.",
    )
    
    user_prompt = aspect.get_user_prompt("What is the effect of exercise?")
    
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
            "needs_refinement": True,
            "explanation": "All good",
            "suggested_question": "Clarify?",
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
        make_aspect(examples={"unsupported": [{"query": "Example"}]})
    assert "Invalid example categories" in str(excinfo.value)


def test_examples_validation_rejects_non_string_fields():
    with pytest.raises(ValueError):
        make_aspect(
            examples={
                "clear": [
                    {
                        "query": "Example",
                        "explanation": 42,  # type: ignore[arg-type]
                    }
                ]
            }
        )


def test_default_system_prompt_uses_name_and_description():
    aspect = make_aspect()
    prompt = aspect.get_system_prompt()

    assert "Demo Aspect" in prompt
    assert "Tracks demo behaviour" in prompt
    assert "asking targeted, clarifying questions" in prompt


def test_get_user_prompt_includes_examples_and_format():
    aspect = make_aspect(
        examples={
            "needs_refinement": [
                {
                    "query": "Does exercise help?",
                    "issue": "Too broad",
                    "suggested_question": "What type of exercise?",
                }
            ]
        },
        response_format={"additional_fields": {"confidence": "float"}},
    )

    prompt = aspect.get_user_prompt("Sample query")

    assert "Sample query" in prompt
    assert "NEEDS REFINEMENT:" in prompt
    assert "confidence" in prompt
    assert "float" in prompt


def test_get_prompts_returns_system_and_user_prompts():
    aspect = make_aspect(system_prompt="Be concise.")
    system_prompt, user_prompt = aspect.get_prompts("Query text")

    assert system_prompt == "Be concise."
    assert "Query text" in user_prompt


def test_format_examples_omits_missing_categories():
    aspect = make_aspect(
        examples={
            "clear": [
                {
                    "query": "Specific example",
                    "explanation": "Complete",
                }
            ],
            "partial": [
                {
                    "query": "Missing",
                    "has": "Age",
                    "missing": "Duration",
                    "suggested_question": "For how long?",
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

    assert "needs_refinement" in instructions
    assert "priority" in instructions
    assert "Low/Medium/High" in instructions
    assert json.loads(
        instructions.split("```json\n", 1)[1].split("\n```", 1)[0]
    )["priority"] == "<string>"


def test_validate_response_missing_base_fields():
    aspect = make_aspect()
    is_valid, error = aspect.validate_response({})

    assert not is_valid
    assert "Missing required base fields" in error


def test_validate_response_type_errors():
    aspect = make_aspect()
    is_valid, error = aspect.validate_response(
        {
            "needs_refinement": "true",
            "explanation": 123,
            "suggested_question": None,
        }
    )

    assert not is_valid
    assert "must be a boolean" in error
    assert "must be a string" in error


def test_validate_response_strict_warns_on_unexpected_fields():
    aspect = make_aspect()
    is_valid, error, warnings = aspect.validate_response_strict(
        {
            "needs_refinement": False,
            "explanation": "All set",
            "suggested_question": "",
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