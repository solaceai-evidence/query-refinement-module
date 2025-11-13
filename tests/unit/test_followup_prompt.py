from query_refinement_module.prompt.followup_prompt import (
    UNIVERSAL_FOLLOWUP_PROMPT,
    UNIVERSAL_FOLLOWUP_PROMPT_CONCISE,
)


def test_universal_followup_prompt_formats_values():
    rendered = UNIVERSAL_FOLLOWUP_PROMPT.format(
        aspect_name="Population",
        aspect_description="Target group",
        original_query="Study on asthma",
        conversation_history="Q: question\nA: answer",
        latest_answer="Adults",
    )

    assert "Population" in rendered
    assert "Target group" in rendered
    assert "Study on asthma" in rendered
    assert "Adults" in rendered
    assert '"is_complete": true' in rendered
    assert "suggested_options" in rendered


def test_universal_followup_prompt_concise_formats_values():
    rendered = UNIVERSAL_FOLLOWUP_PROMPT_CONCISE.format(
        original_query="Heart disease",
        aspect_name="Intervention",
        aspect_description="Treatment details",
        conversation_history="Q: previous\nA: answer",
        latest_answer="Statins",
    )

    assert "Heart disease" in rendered
    assert "Intervention" in rendered
    assert "Treatment details" in rendered
    assert "Statins" in rendered
    assert '"is_complete": true/false' in rendered
    assert rendered.count('{') == rendered.count('}')