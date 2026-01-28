"""Tests for system prompt caching functionality."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from query_refinement_module.providers import LiteLLMProvider
from query_refinement_module.interfaces import LLMCompletionResult


@pytest.mark.asyncio
async def test_prompt_caching_enabled_adds_cache_control():
    """Test that cache_control is added to system message when caching is enabled."""
    provider = LiteLLMProvider(
        default_model="anthropic/claude-sonnet-4-20250514",
        enable_prompt_caching=True
    )
    
    # Mock litellm.acompletion
    mock_response = {
        "choices": [{"message": {"content": "test response"}}],
        "usage": {"total_tokens": 100},
        "id": "test-id"
    }
    
    with patch('query_refinement_module.providers.llm.litellm') as mock_litellm:
        mock_litellm.acompletion = AsyncMock(return_value=mock_response)
        
        result = await provider.complete_async(
            user_prompt="Test user prompt",
            system_prompt="Test system prompt",
            cache_system_prompt=True
        )
        
        # Verify the call was made
        assert mock_litellm.acompletion.called
        call_args = mock_litellm.acompletion.call_args
        messages = call_args.kwargs['messages']
        
        # Check that system message has cache_control
        system_message = messages[0]
        assert system_message['role'] == 'system'
        assert system_message['content'] == 'Test system prompt'
        assert 'cache_control' in system_message
        assert system_message['cache_control'] == {'type': 'ephemeral'}


@pytest.mark.asyncio
async def test_prompt_caching_disabled_no_cache_control():
    """Test that cache_control is not added when caching is disabled."""
    provider = LiteLLMProvider(
        default_model="anthropic/claude-sonnet-4-20250514",
        enable_prompt_caching=False
    )
    
    mock_response = {
        "choices": [{"message": {"content": "test response"}}],
        "usage": {"total_tokens": 100},
        "id": "test-id"
    }
    
    with patch('query_refinement_module.providers.llm.litellm') as mock_litellm:
        mock_litellm.acompletion = AsyncMock(return_value=mock_response)
        
        result = await provider.complete_async(
            user_prompt="Test user prompt",
            system_prompt="Test system prompt",
            cache_system_prompt=True  # Requested but disabled at provider level
        )
        
        # Verify the call was made
        assert mock_litellm.acompletion.called
        call_args = mock_litellm.acompletion.call_args
        messages = call_args.kwargs['messages']
        
        # Check that system message does NOT have cache_control
        system_message = messages[0]
        assert system_message['role'] == 'system'
        assert system_message['content'] == 'Test system prompt'
        assert 'cache_control' not in system_message


@pytest.mark.asyncio
async def test_prompt_caching_not_requested():
    """Test that cache_control is not added when not requested."""
    provider = LiteLLMProvider(
        default_model="anthropic/claude-sonnet-4-20250514",
        enable_prompt_caching=True
    )
    
    mock_response = {
        "choices": [{"message": {"content": "test response"}}],
        "usage": {"total_tokens": 100},
        "id": "test-id"
    }
    
    with patch('query_refinement_module.providers.llm.litellm') as mock_litellm:
        mock_litellm.acompletion = AsyncMock(return_value=mock_response)
        
        result = await provider.complete_async(
            user_prompt="Test user prompt",
            system_prompt="Test system prompt",
            cache_system_prompt=False  # Explicitly not requested
        )
        
        # Verify the call was made
        assert mock_litellm.acompletion.called
        call_args = mock_litellm.acompletion.call_args
        messages = call_args.kwargs['messages']
        
        # Check that system message does NOT have cache_control
        system_message = messages[0]
        assert system_message['role'] == 'system'
        assert system_message['content'] == 'Test system prompt'
        assert 'cache_control' not in system_message


@pytest.mark.asyncio
async def test_prompt_caching_without_system_prompt():
    """Test that caching works correctly when no system prompt is provided."""
    provider = LiteLLMProvider(
        default_model="anthropic/claude-sonnet-4-20250514",
        enable_prompt_caching=True
    )
    
    mock_response = {
        "choices": [{"message": {"content": "test response"}}],
        "usage": {"total_tokens": 100},
        "id": "test-id"
    }
    
    with patch('query_refinement_module.providers.llm.litellm') as mock_litellm:
        mock_litellm.acompletion = AsyncMock(return_value=mock_response)
        
        result = await provider.complete_async(
            user_prompt="Test user prompt",
            system_prompt=None,  # No system prompt
            cache_system_prompt=True
        )
        
        # Verify the call was made
        assert mock_litellm.acompletion.called
        call_args = mock_litellm.acompletion.call_args
        messages = call_args.kwargs['messages']
        
        # Check that only user message exists
        assert len(messages) == 1
        assert messages[0]['role'] == 'user'
        assert messages[0]['content'] == 'Test user prompt'


def test_llm_settings_enable_prompt_caching_default():
    """Test that LLMSettings defaults to enable_prompt_caching=True."""
    from query_refinement_module.settings import LLMSettings
    
    settings = LLMSettings(model="test-model")
    assert settings.enable_prompt_caching is True


def test_llm_settings_enable_prompt_caching_false():
    """Test that LLMSettings respects enable_prompt_caching=False."""
    from query_refinement_module.settings import LLMSettings
    
    settings = LLMSettings(model="test-model", enable_prompt_caching=False)
    assert settings.enable_prompt_caching is False


def test_llm_settings_as_provider_kwargs_includes_caching():
    """Test that as_provider_kwargs includes enable_prompt_caching."""
    from query_refinement_module.settings import LLMSettings
    
    settings = LLMSettings(model="test-model", enable_prompt_caching=False)
    kwargs = settings.as_provider_kwargs()
    
    assert 'enable_prompt_caching' in kwargs
    assert kwargs['enable_prompt_caching'] is False


def test_parse_bool_helper():
    """Test the _parse_bool helper function."""
    from query_refinement_module.settings import _parse_bool
    
    # True values
    assert _parse_bool("true", False) is True
    assert _parse_bool("True", False) is True
    assert _parse_bool("TRUE", False) is True
    assert _parse_bool("1", False) is True
    assert _parse_bool("yes", False) is True
    assert _parse_bool("on", False) is True
    
    # False values
    assert _parse_bool("false", True) is False
    assert _parse_bool("False", True) is False
    assert _parse_bool("FALSE", True) is False
    assert _parse_bool("0", True) is False
    assert _parse_bool("no", True) is False
    assert _parse_bool("off", True) is False
    
    # Empty/None returns default
    assert _parse_bool("", True) is True
    assert _parse_bool("", False) is False
    assert _parse_bool(None, True) is True
    assert _parse_bool(None, False) is False
    
    # Unrecognized values return default
    assert _parse_bool("maybe", True) is True
    assert _parse_bool("maybe", False) is False
