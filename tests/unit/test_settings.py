import pytest

from query_refinement_module.settings import LLMSettings


def _clear_env(monkeypatch):
    for key in {
        "LLM_MODEL",
        "LLM_API_KEY",
        "LLM_API_BASE",
        "LLM_TEMPERATURE",
        "LLM_MAX_OUTPUT_TOKENS",
        "LLM_CONTEXT_WINDOW",
        "LLM_COMPLETION_KWARGS",
        "LLM_ENABLE_PROMPT_CACHING",
        "LLM_CONSTRAINED_DECODING",
        "LLM_PROVIDER_PRESET",
    }:
        monkeypatch.delenv(key, raising=False)


def test_from_env_parses_values(monkeypatch):
    _clear_env(monkeypatch)
    monkeypatch.setenv("LLM_MODEL", "openai/gpt-4o-mini")
    monkeypatch.setenv("LLM_API_KEY", "sk-test")
    monkeypatch.setenv("LLM_API_BASE", "https://example.com")
    monkeypatch.setenv("LLM_TEMPERATURE", "0.3")
    monkeypatch.setenv("LLM_MAX_OUTPUT_TOKENS", "256")
    monkeypatch.setenv(
        "LLM_COMPLETION_KWARGS",
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

    _clear_env(monkeypatch)
    monkeypatch.setenv("LLM_MODEL", "openai/gpt-4o-mini")
    monkeypatch.setenv("LLM_TEMPERATURE", env_value)

    if env_value.strip():
        with pytest.raises(ValueError):
            LLMSettings.from_env()
    else:
        settings = LLMSettings.from_env()
        assert settings.temperature == 0.0


def test_from_env_missing_model_requires(monkeypatch):
    _clear_env(monkeypatch)

    with pytest.raises(RuntimeError):
        LLMSettings.from_env()


def test_from_env_missing_model_allowed_when_optional(monkeypatch):
    _clear_env(monkeypatch)

    settings = LLMSettings.from_env(require_model=False)
    assert settings.model == ""


def test_from_env_invalid_max_tokens(monkeypatch):
    _clear_env(monkeypatch)
    monkeypatch.setenv("LLM_MODEL", "openai/gpt-4o-mini")
    monkeypatch.setenv("LLM_MAX_OUTPUT_TOKENS", "not-an-int")

    with pytest.raises(ValueError):
        LLMSettings.from_env()


@pytest.mark.parametrize("raw", ["not-json", "[]", "123"])
def test_from_env_invalid_completion_kwargs(monkeypatch, raw):
    _clear_env(monkeypatch)
    monkeypatch.setenv("LLM_MODEL", "openai/gpt-4o-mini")
    monkeypatch.setenv("LLM_COMPLETION_KWARGS", raw)

    with pytest.raises(ValueError):
        LLMSettings.from_env()


def test_from_env_defaults_when_missing(monkeypatch):
    _clear_env(monkeypatch)
    monkeypatch.setenv("LLM_MODEL", "openai/gpt-4o-mini")

    settings = LLMSettings.from_env()

    assert settings.temperature == 0.0
    assert settings.max_tokens == 4096
    assert settings.completion_kwargs == {}
    assert settings.api_base is None
    assert settings.enable_prompt_caching is False


def test_from_env_infers_ollama_defaults(monkeypatch):
    _clear_env(monkeypatch)
    monkeypatch.delenv("LLM_ENABLE_PROMPT_CACHING", raising=False)
    monkeypatch.setenv("LLM_MODEL", "ollama/qwen2.5:72b")

    settings = LLMSettings.from_env()

    assert settings.api_base == "http://localhost:11434"
    assert settings.completion_kwargs == {"num_ctx": 16384, "timeout": 1800.0}
    assert settings.enable_prompt_caching is False


def test_from_env_explicit_ollama_overrides_win(monkeypatch):
    _clear_env(monkeypatch)
    monkeypatch.setenv("LLM_MODEL", "ollama/qwen2.5:72b")
    monkeypatch.setenv("LLM_API_BASE", "http://ollama.internal:11434")
    monkeypatch.setenv("LLM_COMPLETION_KWARGS", '{"num_ctx": 8192}')

    settings = LLMSettings.from_env()

    assert settings.api_base == "http://ollama.internal:11434"
    assert settings.completion_kwargs == {"num_ctx": 8192, "timeout": 1800.0}


def test_from_env_infers_anthropic_prompt_caching(monkeypatch):
    _clear_env(monkeypatch)
    monkeypatch.delenv("LLM_ENABLE_PROMPT_CACHING", raising=False)
    monkeypatch.setenv("LLM_MODEL", "anthropic/claude-sonnet-4-6")

    settings = LLMSettings.from_env()

    assert settings.enable_prompt_caching is True
    assert settings.max_tokens == 4096


def test_from_env_infers_openai_defaults(monkeypatch):
    _clear_env(monkeypatch)
    monkeypatch.setenv("LLM_MODEL", "openai/gpt-4o")

    settings = LLMSettings.from_env()

    assert settings.enable_prompt_caching is False
    assert settings.api_base is None
    assert settings.max_tokens == 4096


def test_context_window_override_applies_to_ollama(monkeypatch):
    _clear_env(monkeypatch)
    monkeypatch.setenv("LLM_MODEL", "ollama/qwen2.5:72b")
    monkeypatch.setenv("LLM_CONTEXT_WINDOW", "32768")

    settings = LLMSettings.from_env()

    assert settings.completion_kwargs == {"num_ctx": 32768, "timeout": 1800.0}


def test_context_window_override_respects_explicit_completion_kwargs(monkeypatch):
    _clear_env(monkeypatch)
    monkeypatch.setenv("LLM_MODEL", "ollama/qwen2.5:72b")
    monkeypatch.setenv("LLM_CONTEXT_WINDOW", "32768")
    monkeypatch.setenv("LLM_COMPLETION_KWARGS", '{"num_ctx": 8192}')

    settings = LLMSettings.from_env()

    assert settings.completion_kwargs == {"num_ctx": 8192, "timeout": 1800.0}


def test_explicit_completion_timeout_overrides_ollama_default(monkeypatch):
    _clear_env(monkeypatch)
    monkeypatch.setenv("LLM_MODEL", "ollama/qwen2.5:72b")
    monkeypatch.setenv(
        "LLM_COMPLETION_KWARGS",
        '{"num_ctx": 8192, "timeout": 900.0}',
    )

    settings = LLMSettings.from_env()

    assert settings.completion_kwargs == {"num_ctx": 8192, "timeout": 900.0}


def test_context_window_override_rejected_for_openai(monkeypatch):
    _clear_env(monkeypatch)
    monkeypatch.setenv("LLM_MODEL", "openai/gpt-4o")
    monkeypatch.setenv("LLM_CONTEXT_WINDOW", "32768")

    with pytest.raises(ValueError, match="LLM_CONTEXT_WINDOW"):
        LLMSettings.from_env()


def test_provider_kwargs_returns_copy(monkeypatch):
    _clear_env(monkeypatch)
    monkeypatch.setenv("LLM_MODEL", "openai/gpt-4o-mini")
    monkeypatch.setenv("LLM_COMPLETION_KWARGS", "{\"top_p\": 0.5}")

    settings = LLMSettings.from_env()
    provider_kwargs = settings.as_provider_kwargs()

    provider_kwargs["default_completion_kwargs"]["top_p"] = 0.9

    assert settings.completion_kwargs["top_p"] == 0.5


def test_analyzer_kwargs_returns_copy(monkeypatch):
    _clear_env(monkeypatch)
    monkeypatch.setenv("LLM_MODEL", "openai/gpt-4o-mini")
    monkeypatch.setenv("LLM_TEMPERATURE", "0.4")
    monkeypatch.setenv("LLM_MAX_OUTPUT_TOKENS", "512")
    monkeypatch.setenv("LLM_COMPLETION_KWARGS", "{\"presence_penalty\": 1}")

    settings = LLMSettings.from_env()
    analyzer_kwargs = settings.as_analyzer_kwargs()

    analyzer_kwargs["completion_kwargs"]["presence_penalty"] = 0

    assert settings.temperature == pytest.approx(0.4)
    assert settings.max_tokens == 512
    assert settings.completion_kwargs["presence_penalty"] == 1


# ---------------------------------------------------------------------------
# Rate-limit env vars
# ---------------------------------------------------------------------------

def _clear_rate_limit_env(monkeypatch):
    for key in {
        "LLM_PROVIDER_RATE_LIMIT_RPM",
        "LLM_PROVIDER_RATE_LIMIT_TPM",
        "LLM_PROVIDER_MAX_CONCURRENT",
        "LLM_PROVIDER_ADAPTIVE_RATE_LIMIT",
        "LLM_PROVIDER_ADAPTIVE_DECREASE_FACTOR",
        "LLM_PROVIDER_ADAPTIVE_INCREASE_FACTOR",
        "LLM_PROVIDER_ADAPTIVE_INCREASE_INTERVAL",
    }:
        monkeypatch.delenv(key, raising=False)


def test_rate_limit_defaults_when_absent(monkeypatch):
    _clear_env(monkeypatch)
    _clear_rate_limit_env(monkeypatch)
    monkeypatch.setenv("LLM_MODEL", "ollama/qwen2.5:72b")

    settings = LLMSettings.from_env()

    assert settings.rate_limit_rpm == 0
    assert settings.rate_limit_tpm is None
    assert settings.max_concurrent_requests == 20
    assert settings.adaptive_rate_limit is False


def test_openai_cloud_rate_limit_defaults(monkeypatch):
    _clear_env(monkeypatch)
    _clear_rate_limit_env(monkeypatch)
    monkeypatch.setenv("LLM_MODEL", "openai/gpt-4o")

    settings = LLMSettings.from_env()

    assert settings.rate_limit_rpm == 500
    assert settings.rate_limit_tpm == 30000
    assert settings.max_concurrent_requests == 10


def test_self_hosted_openai_compatible_defaults(monkeypatch):
    _clear_env(monkeypatch)
    _clear_rate_limit_env(monkeypatch)
    monkeypatch.setenv("LLM_MODEL", "openai/meta-llama/Llama-3.1-8B-Instruct")
    monkeypatch.setenv("LLM_API_BASE", "http://localhost:8000/v1")

    settings = LLMSettings.from_env()

    assert settings.rate_limit_rpm == 0
    assert settings.rate_limit_tpm is None
    assert settings.max_concurrent_requests == 20


def test_rate_limit_env_vars_parsed_from_canonical_provider_names(monkeypatch):
    _clear_env(monkeypatch)
    _clear_rate_limit_env(monkeypatch)
    monkeypatch.setenv("LLM_MODEL", "anthropic/claude-sonnet-4-5")
    monkeypatch.setenv("LLM_PROVIDER_RATE_LIMIT_RPM", "50")
    monkeypatch.setenv("LLM_PROVIDER_RATE_LIMIT_TPM", "40000")
    monkeypatch.setenv("LLM_PROVIDER_MAX_CONCURRENT", "5")
    monkeypatch.setenv("LLM_PROVIDER_ADAPTIVE_RATE_LIMIT", "true")
    monkeypatch.setenv("LLM_PROVIDER_ADAPTIVE_DECREASE_FACTOR", "0.7")
    monkeypatch.setenv("LLM_PROVIDER_ADAPTIVE_INCREASE_FACTOR", "1.1")
    monkeypatch.setenv("LLM_PROVIDER_ADAPTIVE_INCREASE_INTERVAL", "30")

    settings = LLMSettings.from_env()

    assert settings.rate_limit_rpm == 50
    assert settings.rate_limit_tpm == 40000
    assert settings.max_concurrent_requests == 5
    assert settings.adaptive_rate_limit is True
    assert settings.adaptive_decrease_factor == pytest.approx(0.7)
    assert settings.adaptive_increase_factor == pytest.approx(1.1)
    assert settings.adaptive_increase_interval == 30


def test_as_provider_kwargs_includes_rate_limit_config(monkeypatch):
    """as_provider_kwargs builds a RateLimitConfig when RPM > 0."""
    from query_refinement_module.interfaces import RateLimitConfig

    _clear_env(monkeypatch)
    _clear_rate_limit_env(monkeypatch)
    monkeypatch.setenv("LLM_MODEL", "anthropic/claude-sonnet-4-5")
    monkeypatch.setenv("LLM_PROVIDER_RATE_LIMIT_RPM", "50")
    monkeypatch.setenv("LLM_PROVIDER_RATE_LIMIT_TPM", "40000")

    settings = LLMSettings.from_env()
    kwargs = settings.as_provider_kwargs()

    rate_cfg = kwargs["rate_limit_config"]
    assert isinstance(rate_cfg, RateLimitConfig)
    assert rate_cfg.requests_per_minute == 50
    assert rate_cfg.tokens_per_minute == 40000


def test_as_provider_kwargs_propagates_adaptive_tuning(monkeypatch):
    _clear_env(monkeypatch)
    _clear_rate_limit_env(monkeypatch)
    monkeypatch.setenv("LLM_MODEL", "anthropic/claude-sonnet-4-5")
    monkeypatch.setenv("LLM_PROVIDER_RATE_LIMIT_RPM", "50")
    monkeypatch.setenv("LLM_PROVIDER_ADAPTIVE_RATE_LIMIT", "true")
    monkeypatch.setenv("LLM_PROVIDER_ADAPTIVE_DECREASE_FACTOR", "0.75")
    monkeypatch.setenv("LLM_PROVIDER_ADAPTIVE_INCREASE_FACTOR", "1.2")
    monkeypatch.setenv("LLM_PROVIDER_ADAPTIVE_INCREASE_INTERVAL", "45")

    settings = LLMSettings.from_env()
    kwargs = settings.as_provider_kwargs()

    rate_cfg = kwargs["rate_limit_config"]
    assert rate_cfg.adaptive_backoff is True
    assert rate_cfg.adaptive_decrease_factor == pytest.approx(0.75)
    assert rate_cfg.adaptive_increase_factor == pytest.approx(1.2)
    assert rate_cfg.adaptive_increase_interval == 45


def test_as_provider_kwargs_no_rate_limit_config_when_rpm_zero(monkeypatch):
    """as_provider_kwargs returns None rate_limit_config when RPM is 0 (local model default)."""
    _clear_env(monkeypatch)
    _clear_rate_limit_env(monkeypatch)
    monkeypatch.setenv("LLM_MODEL", "ollama/qwen2.5:72b")

    settings = LLMSettings.from_env()
    kwargs = settings.as_provider_kwargs()

    assert kwargs["rate_limit_config"] is None


def test_as_provider_kwargs_max_concurrent_propagated(monkeypatch):
    _clear_env(monkeypatch)
    _clear_rate_limit_env(monkeypatch)
    monkeypatch.setenv("LLM_MODEL", "ollama/qwen2.5:72b")
    monkeypatch.setenv("LLM_PROVIDER_MAX_CONCURRENT", "8")

    settings = LLMSettings.from_env()
    kwargs = settings.as_provider_kwargs()

    assert kwargs["max_concurrent_requests"] == 8

