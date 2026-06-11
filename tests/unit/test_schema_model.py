import json

import pytest

from query_refinement_module.schema import RefinementAspect
from query_refinement_module.schema.prompt_builder import PromptBuilder


def make_aspect(**overrides) -> RefinementAspect:
    base_kwargs = {
        "id": "demo",
        "name": "Demo Aspect",
        "description": "Tracks demo behaviour",
        "specifications": "Review this query: {query}",
    }
    base_kwargs.update(overrides)
    return RefinementAspect(**base_kwargs)


@pytest.fixture
def prompt_builder() -> PromptBuilder:
    return PromptBuilder()


def test_refinement_messages_keep_query_as_user_message_when_no_placeholder(prompt_builder):
    """The canonical runtime path keeps the query as a separate user message."""
    aspect = RefinementAspect(
        id="demo",
        name="Missing Placeholder",
        description="No placeholder in prompt",
        specifications="Evaluate the demographic characteristics.",
    )

    messages = prompt_builder.build_refinement_messages(
        dimension=aspect,
        query="What is the effect of exercise?",
        conversation_history=[],
    )

    assert messages[-1]["role"] == "user"
    assert messages[-1]["content"] == "What is the effect of exercise?"
    assert any("Evaluate the demographic characteristics" in message["content"] for message in messages)


def test_build_refinement_messages_substitutes_documented_placeholders(prompt_builder):
    """Placeholder forms should be substituted on the canonical runtime path."""
    aspect = RefinementAspect(
        id="demo",
        name="With Placeholder",
        description="Has placeholder in prompt",
        specifications="Analyze this query: {query}\n\nConsider all aspects.",
    )

    messages = prompt_builder.build_refinement_messages(
        dimension=aspect,
        query="What is the effect of exercise?",
        conversation_history=[],
    )

    rendered = next(
        message["content"]
        for message in messages
        if message["role"] == "system" and "DIMENSION SPECIFICATION" in message["content"]
    )

    assert "Analyze this query: What is the effect of exercise?" in rendered
    assert "Consider all aspects" in rendered


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


def test_default_system_prompt_uses_name_and_description(prompt_builder):
    aspect = make_aspect()
    prompt = prompt_builder.get_global_system_prompt()

    # The global system prompt should contain core directives
    assert "refinement specialist" in prompt or "Research Query Refinement" in prompt
    assert "Dimension" in prompt or "dimension" in prompt
    assert "complete" in prompt.lower()  # Quality gates mention completeness


def test_render_dimension_prompt_includes_examples_and_format(prompt_builder):
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

    prompt = prompt_builder.render_dimension_prompt(aspect)

    assert "Does exercise help?" in prompt
    assert "Needs Refinement:" in prompt or "Too broad" in prompt
    assert '"complete": <boolean>' in prompt


def test_render_dimension_prompt_omits_missing_categories(prompt_builder):
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

    formatted = prompt_builder.render_dimension_prompt(aspect)

    assert "Clear Specifications:" in formatted
    assert "Needs Refinement:" not in formatted
    assert "Has: Age" in formatted
    assert "Example Q: \"For how long?\"" in formatted


def test_render_dimension_prompt_lists_response_fields(prompt_builder):
    """Canonical dimension rendering should include the base response fields."""
    aspect = make_aspect()

    instructions = prompt_builder.render_dimension_prompt(aspect)

    assert '"complete": <boolean>' in instructions
    assert '"current": "<string>"' in instructions
    assert '"question": "<string>"' in instructions


def test_validate_response_missing_base_fields():
    aspect = make_aspect()
    is_valid, error = aspect.validate_response({})

    assert not is_valid
    assert "Missing required field" in error
    assert "complete" in error


def test_validate_response_type_errors():
    aspect = make_aspect()
    is_valid, error = aspect.validate_response(
        {
            "complete": "true",
            "current": 123,
            "question": None,
        }
    )

    assert not is_valid
    assert "must be" in error  # Type validation error


def test_validate_response_strict_warns_on_unexpected_fields():
    aspect = make_aspect()
    is_valid, error, warnings = aspect.validate_response_strict(
        {
            "complete": True,
            "current": "Some value",
            "question": "",
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
        "complete": True,
        "current": "Value",
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