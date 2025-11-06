import pytest

from query_refinement_module.settings import LLMSettings


def test_from_env_parses_values(monkeypatch):
    monkeypatch.setenv("QUERY_REFINEMENT_LLM_MODEL", "openai/gpt-4o-mini")
    monkeypatch.setenv("QUERY_REFINEMENT_LLM_API_KEY", "sk-test")
    monkeypatch.setenv("QUERY_REFINEMENT_LLM_API_BASE", "https://example.com")
    monkeypatch.setenv("QUERY_REFINEMENT_LLM_TEMPERATURE", "0.3")
    monkeypatch.setenv("QUERY_REFINEMENT_LLM_MAX_TOKENS", "256")
    monkeypatch.setenv(
        "QUERY_REFINEMENT_LLM_COMPLETION_KWARGS",
        '{"top_p": 0.8, "response_format": {"type": "json_object"}}',
    )

    settings = LLMSettings.from_env()

    assert settings.model == "openai/gpt-4o-mini"
    assert settings.api_key == "sk-test"
    assert settings.api_base == "https://example.com"
    assert settings.temperature == pytest.approx(0.3)
    assert settings.max_tokens == 256
    assert settings.completion_kwargs == {
        "top_p": 0.8,
        "response_format": {"type": "json_object"},
    }


@pytest.mark.parametrize("env_value", ["not-a-number", "", "   "])
def test_from_env_invalid_temperature(monkeypatch, env_value):
    """Invalid temperature values should raise a ValueError."""

    monkeypatch.setenv("QUERY_REFINEMENT_LLM_MODEL", "openai/gpt-4o-mini")
    monkeypatch.setenv("QUERY_REFINEMENT_LLM_TEMPERATURE", env_value)

    if env_value.strip():
        with pytest.raises(ValueError):
            LLMSettings.from_env()
    else:
        settings = LLMSettings.from_env()
        assert settings.temperature == 0.0
