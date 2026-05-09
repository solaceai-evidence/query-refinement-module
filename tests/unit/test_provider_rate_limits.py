"""Tests for LiteLLMProvider rate limit handling and retry logic."""

from unittest.mock import patch
import pytest

from query_refinement_module.providers import LiteLLMProvider
from query_refinement_module.interfaces import RateLimitExceeded


class RateLimitError(Exception):
    """Mock rate limit error."""
    pass


class MockLiteLLMError(Exception):
    """Mock litellm error with status code."""
    def __init__(self, message, status_code=None):
        super().__init__(message)
        self.status_code = status_code


@pytest.fixture
def mock_litellm_module():
    """Mock the litellm module."""
    with patch('query_refinement_module.providers.llm.litellm') as mock:
        yield mock


def test_provider_retries_on_rate_limit_error(mock_litellm_module):
    """Test that provider retries on rate limit errors."""
    provider = LiteLLMProvider(default_model="gpt-3.5-turbo")
    
    # First two calls fail with rate limit, third succeeds
    mock_litellm_module.completion.side_effect = [
        MockLiteLLMError("Rate limit exceeded", status_code=429),
        MockLiteLLMError("Rate limit exceeded", status_code=429),
        {
            "choices": [{"message": {"content": "Success"}}],
            "usage": {"total_tokens": 10, "prompt_tokens": 5, "completion_tokens": 5},
            "id": "test-id",
        }
    ]
    
    with patch('query_refinement_module.providers.llm.time.sleep'):  # Don't actually sleep in tests
        result = provider.complete("Test prompt")
    
    assert result.context == "Success"
    assert mock_litellm_module.completion.call_count == 3


def test_provider_raises_rate_limit_exceeded_after_max_retries(mock_litellm_module):
    """Test that provider raises RateLimitExceeded after exhausting retries."""
    provider = LiteLLMProvider(default_model="gpt-3.5-turbo")
    
    # All calls fail with rate limit
    mock_litellm_module.completion.side_effect = MockLiteLLMError(
        "Rate limit exceeded, retry after 60 seconds",
        status_code=429
    )
    
    with patch('query_refinement_module.providers.llm.time.sleep'):
        with pytest.raises(RateLimitExceeded) as exc_info:
            provider.complete("Test prompt")
    
    assert "Rate limit exceeded" in str(exc_info.value)
    assert exc_info.value.retry_after == 60.0
    assert exc_info.value.limit_type == "provider"
    assert mock_litellm_module.completion.call_count == 4  # initial + 3 retries


def test_provider_extracts_retry_after_from_error_message():
    """Test extraction of retry_after from error messages directly."""
    provider = LiteLLMProvider(default_model="gpt-3.5-turbo")
    
    # Test various retry_after formats
    test_cases = [
        ("Rate limit exceeded, retry after 30 seconds", 30.0),
        ("Too many requests, wait 45.5 seconds", 45.5),
        ("retry_after: 120", 120.0),
    ]
    
    for error_msg, expected_retry in test_cases:
        error = MockLiteLLMError(error_msg, status_code=429)
        result = provider._extract_retry_after(error)
        assert result == expected_retry, f"Failed for message: {error_msg}"


def test_provider_uses_exponential_backoff_when_no_retry_after(mock_litellm_module):
    """Test exponential backoff when retry_after is not specified."""
    provider = LiteLLMProvider(default_model="gpt-3.5-turbo")
    
    mock_litellm_module.completion.side_effect = [
        MockLiteLLMError("Rate limit", status_code=429),
        MockLiteLLMError("Rate limit", status_code=429),
        {
            "choices": [{"message": {"content": "Success"}}],
            "usage": {"total_tokens": 10},
            "id": "test-id",
        }
    ]
    
    sleep_calls = []
    def mock_sleep(duration):
        sleep_calls.append(duration)
    
    with patch('query_refinement_module.providers.llm.time.sleep', side_effect=mock_sleep):
        provider.complete("Test prompt")
    
    # Should use exponential backoff: 1.0, 2.0
    assert len(sleep_calls) == 2
    assert sleep_calls[0] == 1.0
    assert sleep_calls[1] == 2.0


def test_provider_handles_503_service_unavailable():
    """Test that 503 errors are detected as rate limit errors."""
    provider = LiteLLMProvider(default_model="gpt-3.5-turbo")
    
    # Error message must contain "503" to be detected
    error = MockLiteLLMError("Service unavailable: 503", status_code=503)
    assert provider._is_rate_limit_error(error)


def test_provider_raises_non_rate_limit_errors_immediately(mock_litellm_module):
    """Test that non-rate-limit errors are raised without retry."""
    provider = LiteLLMProvider(default_model="gpt-3.5-turbo")
    
    mock_litellm_module.completion.side_effect = ValueError("Invalid model")
    
    with pytest.raises(ValueError, match="Invalid model"):
        provider.complete("Test prompt")
    
    # Should not retry on non-rate-limit errors
    assert mock_litellm_module.completion.call_count == 1


def test_provider_parses_rate_limit_headers():
    """Test parsing of rate limit headers from response."""
    provider = LiteLLMProvider(default_model="gpt-3.5-turbo")
    
    headers = {
        "X-RateLimit-Remaining": "45",
        "X-RateLimit-Limit": "50",
        "X-RateLimit-Reset": "1609459200",
        "Retry-After": "30",
    }
    
    rate_limit_info = provider._parse_rate_limit_headers(headers)
    
    assert rate_limit_info["requests_remaining"] == 45
    assert rate_limit_info["requests_limit"] == 50
    assert rate_limit_info["reset_time"] == 1609459200.0
    assert rate_limit_info["retry_after"] == 30.0


def test_provider_handles_case_insensitive_headers():
    """Test that header parsing is case-insensitive."""
    provider = LiteLLMProvider(default_model="gpt-3.5-turbo")
    
    headers = {
        "x-ratelimit-remaining": "10",
        "X-RATELIMIT-LIMIT": "50",
        "Retry-AFTER": "15",
    }
    
    rate_limit_info = provider._parse_rate_limit_headers(headers)
    
    assert rate_limit_info["requests_remaining"] == 10
    assert rate_limit_info["requests_limit"] == 50
    assert rate_limit_info["retry_after"] == 15.0


def test_provider_handles_invalid_header_values():
    """Test that invalid header values are ignored gracefully."""
    provider = LiteLLMProvider(default_model="gpt-3.5-turbo")
    
    headers = {
        "X-RateLimit-Remaining": "invalid",
        "X-RateLimit-Limit": "not-a-number",
        "X-RateLimit-Reset": "1609459200",  # Valid
    }
    
    rate_limit_info = provider._parse_rate_limit_headers(headers)
    
    # Invalid values should be skipped
    assert "requests_remaining" not in rate_limit_info
    assert "requests_limit" not in rate_limit_info
    # Valid value should be present
    assert rate_limit_info["reset_time"] == 1609459200.0


def test_provider_includes_token_usage_in_metadata(mock_litellm_module):
    """Test that token usage is included in completion metadata."""
    provider = LiteLLMProvider(default_model="gpt-3.5-turbo")
    
    mock_litellm_module.completion.return_value = {
        "choices": [{"message": {"content": "Response"}}],
        "usage": {
            "total_tokens": 100,
            "prompt_tokens": 30,
            "completion_tokens": 70,
        },
        "id": "test-id",
    }
    
    result = provider.complete("Test prompt")
    
    assert result.metadata["usage"]["total_tokens"] == 100
    assert result.metadata["prompt_tokens"] == 30
    assert result.metadata["completion_tokens"] == 70


def test_is_rate_limit_error_detection():
    """Test rate limit error detection logic."""
    provider = LiteLLMProvider(default_model="gpt-3.5-turbo")
    
    # Should detect rate limit errors
    assert provider._is_rate_limit_error(Exception("Rate limit exceeded"))
    assert provider._is_rate_limit_error(Exception("HTTP 429 Too Many Requests"))
    assert provider._is_rate_limit_error(Exception("Quota exceeded for this model"))


def test_provider_uses_openai_cloud_defaults_when_unspecified():
    provider = LiteLLMProvider(default_model="openai/gpt-4o")

    assert provider._max_concurrent == 10
    assert provider._rate_limiter is not None


def test_provider_disables_cloud_rate_limits_for_openai_compatible_api_base():
    provider = LiteLLMProvider(
        default_model="openai/meta-llama/Llama-3.1-8B-Instruct",
        api_base="http://localhost:8000/v1",
    )

    assert provider._rate_limiter is None
    assert provider._is_rate_limit_error(Exception("Service temporarily unavailable: 503"))
    assert provider._is_rate_limit_error(MockLiteLLMError("RateLimitError occurred"))
    
    # Should not detect non-rate-limit errors
    assert not provider._is_rate_limit_error(Exception("Invalid API key"))
    assert not provider._is_rate_limit_error(ValueError("Bad request: 400"))


def test_extract_retry_after_patterns():
    """Test various retry_after extraction patterns."""
    provider = LiteLLMProvider(default_model="gpt-3.5-turbo")
    
    test_cases = [
        ("Please retry after 45 seconds", 45.0),
        ("Retry after 30.5 seconds please", 30.5),
        ("retry_after: 120", 120.0),
        ("Please wait 60 seconds before retrying", 60.0),
        ("No retry information here", None),
    ]
    
    for error_msg, expected in test_cases:
        result = provider._extract_retry_after(Exception(error_msg))
        assert result == expected, f"Failed for message: {error_msg}"


def test_provider_logs_retry_attempts(mock_litellm_module, caplog):
    """Test that retry attempts are logged."""
    import logging
    caplog.set_level(logging.WARNING)
    
    provider = LiteLLMProvider(default_model="gpt-3.5-turbo")
    
    mock_litellm_module.completion.side_effect = [
        MockLiteLLMError("Rate limit", status_code=429),
        {
            "choices": [{"message": {"content": "Success"}}],
            "usage": {"total_tokens": 10},
            "id": "test-id",
        }
    ]
    
    with patch('query_refinement_module.providers.llm.time.sleep'):
        provider.complete("Test prompt")
    
    # Check that retry was logged
    assert any("Rate limit hit, retrying" in record.message for record in caplog.records)


# ---------------------------------------------------------------------------
# TokenBucketRateLimiter wiring (proactive pre-request limiting)
# ---------------------------------------------------------------------------

def test_provider_creates_rate_limiter_for_explicit_rpm_config():
    """When rate_limit_config with RPM > 0 is passed, a TokenBucketRateLimiter is created."""
    from query_refinement_module.interfaces import RateLimitConfig
    from query_refinement_module.rate_limiter import TokenBucketRateLimiter

    config = RateLimitConfig(requests_per_minute=60)
    provider = LiteLLMProvider(
        default_model="anthropic/claude-sonnet-4-5",
        rate_limit_config=config,
    )

    assert provider._rate_limiter is not None
    assert isinstance(provider._rate_limiter, TokenBucketRateLimiter)
    assert provider._rate_limiter.config.requests_per_minute == 60


def test_provider_no_rate_limiter_when_rpm_zero():
    """Passing rate_limit_config with rpm=0 keeps _rate_limiter as None."""
    from query_refinement_module.interfaces import RateLimitConfig

    config = RateLimitConfig(requests_per_minute=0)
    provider = LiteLLMProvider(
        default_model="ollama/qwen2.5:72b",
        rate_limit_config=config,
    )

    assert provider._rate_limiter is None


def test_provider_no_rate_limiter_for_unlimited():
    """RateLimitConfig.unlimited() results in no rate limiter."""
    from query_refinement_module.interfaces import RateLimitConfig

    provider = LiteLLMProvider(
        default_model="ollama/qwen2.5:72b",
        rate_limit_config=RateLimitConfig.unlimited(),
    )

    assert provider._rate_limiter is None


def test_provider_auto_selects_provider_defaults_for_claude():
    """Without explicit rate_limit_config, claude-* models get a proactive rate limiter."""
    from query_refinement_module.rate_limiter import TokenBucketRateLimiter

    provider = LiteLLMProvider(default_model="claude-3-5-sonnet-20241022")

    assert provider._rate_limiter is not None
    assert isinstance(provider._rate_limiter, TokenBucketRateLimiter)
    assert provider._rate_limiter.config.requests_per_minute == 50


def test_provider_auto_selects_provider_defaults_for_openai_prefixed_models():
    """Without explicit rate_limit_config, openai/* models get OpenAI-specific defaults."""
    from query_refinement_module.rate_limiter import TokenBucketRateLimiter

    provider = LiteLLMProvider(default_model="openai/gpt-4o")

    assert provider._rate_limiter is not None
    assert isinstance(provider._rate_limiter, TokenBucketRateLimiter)
    assert provider._rate_limiter.config.requests_per_minute == 500


def test_provider_no_rate_limiter_for_local_model_by_default():
    """ollama/llama models have unlimited defaults → no proactive limiter."""
    provider = LiteLLMProvider(default_model="ollama/qwen2.5:72b")

    assert provider._rate_limiter is None


def test_provider_semaphore_respects_max_concurrent():
    """max_concurrent_requests parameter wires through to the asyncio.Semaphore."""
    provider = LiteLLMProvider(default_model="ollama/qwen2.5:72b", max_concurrent_requests=5)

    assert provider._semaphore._value == 5


@pytest.mark.asyncio
async def test_provider_rate_limiter_acquire_called_on_complete_async(mock_litellm_module):
    """complete_async calls rate_limiter.acquire() before dispatching the LLM call."""
    from unittest.mock import AsyncMock
    from query_refinement_module.interfaces import RateLimitConfig

    mock_litellm_module.acompletion = AsyncMock(return_value={
        "choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}],
        "usage": {"total_tokens": 5, "prompt_tokens": 3, "completion_tokens": 2},
        "id": "test-id",
    })

    config = RateLimitConfig(requests_per_minute=600)
    provider = LiteLLMProvider(
        default_model="anthropic/claude-sonnet-4-5",
        rate_limit_config=config,
    )
    acquire_calls = []

    original_acquire = provider._rate_limiter.acquire

    async def spy_acquire(*args, **kwargs):
        acquire_calls.append(True)
        return await original_acquire(*args, **kwargs)

    provider._rate_limiter.acquire = spy_acquire

    await provider.complete_async("hello")

    assert len(acquire_calls) == 1
