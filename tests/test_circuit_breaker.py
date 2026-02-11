"""
Tests for circuit breaker implementation.

Validates circuit breaker behavior for LLM provider protection.
"""
import asyncio
import pytest
import time
from unittest.mock import AsyncMock, patch

from query_refinement_module.providers.circuit_breaker import (
    CircuitBreaker,
    CircuitBreakerConfig,
    CircuitBreakerOpen,
    CircuitBreakerRegistry,
    CircuitState,
)


class TestCircuitBreaker:
    """Test circuit breaker state transitions and behavior."""
    
    @pytest.mark.asyncio
    async def test_initial_state_closed(self):
        """Circuit breaker should start in CLOSED state."""
        cb = CircuitBreaker("test", CircuitBreakerConfig())
        assert cb.state == CircuitState.CLOSED
        assert cb.metrics.failure_count == 0
        assert cb.metrics.success_count == 0
    
    @pytest.mark.asyncio
    async def test_successful_call(self):
        """Successful calls should pass through and be counted."""
        cb = CircuitBreaker("test", CircuitBreakerConfig())
        
        async def success_func():
            return "success"
        
        result = await cb.call(success_func)
        assert result == "success"
        assert cb.state == CircuitState.CLOSED
        assert cb.metrics.success_count == 1
        assert cb.metrics.total_calls == 1
    
    @pytest.mark.asyncio
    async def test_failure_counted(self):
        """Failed calls should be counted."""
        cb = CircuitBreaker("test", CircuitBreakerConfig(failure_threshold=3))
        
        async def failing_func():
            raise RuntimeError("API error")
        
        # Should fail but not open circuit yet
        with pytest.raises(RuntimeError):
            await cb.call(failing_func)
        
        assert cb.state == CircuitState.CLOSED
        assert cb.metrics.failure_count == 1
        assert cb.metrics.total_calls == 1
    
    @pytest.mark.asyncio
    async def test_circuit_opens_after_threshold(self):
        """Circuit should open after failure threshold is reached."""
        cb = CircuitBreaker("test", CircuitBreakerConfig(failure_threshold=3))
        
        async def failing_func():
            raise RuntimeError("API error")
        
        # Fail 3 times to reach threshold
        for i in range(3):
            with pytest.raises(RuntimeError):
                await cb.call(failing_func)
        
        assert cb.state == CircuitState.OPEN
        assert cb.metrics.opened_at is not None
    
    @pytest.mark.asyncio
    async def test_circuit_rejects_when_open(self):
        """Open circuit should reject calls immediately."""
        cb = CircuitBreaker("test", CircuitBreakerConfig(failure_threshold=2))
        
        async def failing_func():
            raise RuntimeError("API error")
        
        # Open the circuit
        for i in range(2):
            with pytest.raises(RuntimeError):
                await cb.call(failing_func)
        
        assert cb.state == CircuitState.OPEN
        
        # Next call should be rejected immediately
        async def any_func():
            return "should not execute"
        
        with pytest.raises(CircuitBreakerOpen) as exc_info:
            await cb.call(any_func)
        
        assert "test" in str(exc_info.value)
        assert cb.metrics.rejected_calls == 1
    
    @pytest.mark.asyncio
    async def test_circuit_transitions_to_half_open(self):
        """Circuit should transition to HALF_OPEN after recovery timeout."""
        cb = CircuitBreaker(
            "test", 
            CircuitBreakerConfig(
                failure_threshold=2,
                recovery_timeout=0.1  # 100ms for fast test
            )
        )
        
        async def failing_func():
            raise RuntimeError("API error")
        
        # Open the circuit
        for i in range(2):
            with pytest.raises(RuntimeError):
                await cb.call(failing_func)
        
        assert cb.state == CircuitState.OPEN
        
        # Wait for recovery timeout
        await asyncio.sleep(0.15)
        
        # Next call should trigger transition to half-open
        async def success_func():
            return "recovered"
        
        result = await cb.call(success_func)
        assert result == "recovered"
        assert cb.state == CircuitState.HALF_OPEN
    
    @pytest.mark.asyncio
    async def test_circuit_closes_after_successful_recovery(self):
        """Circuit should close after success threshold in HALF_OPEN state."""
        cb = CircuitBreaker(
            "test",
            CircuitBreakerConfig(
                failure_threshold=2,
                recovery_timeout=0.1,
                success_threshold=2
            )
        )
        
        async def failing_func():
            raise RuntimeError("API error")
        
        # Open the circuit
        for i in range(2):
            with pytest.raises(RuntimeError):
                await cb.call(failing_func)
        
        assert cb.state == CircuitState.OPEN
        
        # Wait for recovery timeout
        await asyncio.sleep(0.15)
        
        # Make successful calls to close circuit
        async def success_func():
            return "recovered"
        
        await cb.call(success_func)
        assert cb.state == CircuitState.HALF_OPEN
        
        await cb.call(success_func)
        assert cb.state == CircuitState.CLOSED
        assert cb.metrics.failure_count == 0
    
    @pytest.mark.asyncio
    async def test_half_open_reopens_on_failure(self):
        """Circuit should reopen immediately if call fails in HALF_OPEN state."""
        cb = CircuitBreaker(
            "test",
            CircuitBreakerConfig(
                failure_threshold=2,
                recovery_timeout=0.1
            )
        )
        
        async def failing_func():
            raise RuntimeError("API error")
        
        # Open the circuit
        for i in range(2):
            with pytest.raises(RuntimeError):
                await cb.call(failing_func)
        
        assert cb.state == CircuitState.OPEN
        
        # Wait for recovery timeout
        await asyncio.sleep(0.15)
        
        # Fail during half-open - should reopen immediately
        with pytest.raises(RuntimeError):
            await cb.call(failing_func)
        
        assert cb.state == CircuitState.OPEN
    
    @pytest.mark.asyncio
    async def test_failure_window(self):
        """Old failures outside window should not count toward threshold."""
        cb = CircuitBreaker(
            "test",
            CircuitBreakerConfig(
                failure_threshold=3,
                failure_window=0.2  # 200ms window
            )
        )
        
        async def failing_func():
            raise RuntimeError("API error")
        
        # Fail once
        with pytest.raises(RuntimeError):
            await cb.call(failing_func)
        
        # Wait for failure to age out
        await asyncio.sleep(0.25)
        
        # These two failures alone shouldn't open circuit
        with pytest.raises(RuntimeError):
            await cb.call(failing_func)
        with pytest.raises(RuntimeError):
            await cb.call(failing_func)
        
        # Circuit should still be closed (first failure aged out)
        assert cb.state == CircuitState.CLOSED


class TestCircuitBreakerRegistry:
    """Test circuit breaker registry for multi-provider management."""
    
    @pytest.mark.asyncio
    async def test_registry_creates_breakers(self):
        """Registry should create circuit breakers on demand."""
        registry = CircuitBreakerRegistry()
        
        cb1 = await registry.get_breaker("openai")
        cb2 = await registry.get_breaker("anthropic")
        
        assert cb1.name == "openai"
        assert cb2.name == "anthropic"
        assert cb1 is not cb2
    
    @pytest.mark.asyncio
    async def test_registry_reuses_breakers(self):
        """Registry should reuse existing circuit breakers."""
        registry = CircuitBreakerRegistry()
        
        cb1 = await registry.get_breaker("openai")
        cb2 = await registry.get_breaker("openai")
        
        assert cb1 is cb2
    
    @pytest.mark.asyncio
    async def test_registry_get_all_metrics(self):
        """Registry should return metrics for all breakers."""
        registry = CircuitBreakerRegistry()
        
        await registry.get_breaker("openai")
        await registry.get_breaker("anthropic")
        
        metrics = registry.get_all_metrics()
        
        assert "openai" in metrics
        assert "anthropic" in metrics
        assert metrics["openai"]["state"] == "closed"
        assert metrics["anthropic"]["state"] == "closed"
    
    @pytest.mark.asyncio
    async def test_registry_with_custom_config(self):
        """Registry should apply custom config to all breakers."""
        config = CircuitBreakerConfig(
            failure_threshold=10,
            recovery_timeout=120.0
        )
        registry = CircuitBreakerRegistry(config)
        
        cb = await registry.get_breaker("test")
        
        assert cb.config.failure_threshold == 10
        assert cb.config.recovery_timeout == 120.0


class TestCircuitBreakerWithLLM:
    """Test circuit breaker integration with LLM provider."""
    
    @pytest.mark.asyncio
    async def test_llm_provider_circuit_breaker_enabled(self):
        """LLM provider should have circuit breaker when enabled."""
        from query_refinement_module.providers import LiteLLMProvider, CircuitBreakerConfig
        
        with patch('query_refinement_module.providers.llm.litellm'):
            provider = LiteLLMProvider(
                default_model="gpt-4",
                enable_circuit_breaker=True,
                circuit_breaker_config=CircuitBreakerConfig(failure_threshold=3)
            )
            
            assert provider._enable_circuit_breaker is True
            assert provider._circuit_breaker_registry is not None
    
    @pytest.mark.asyncio
    async def test_llm_provider_circuit_breaker_disabled(self):
        """LLM provider should work without circuit breaker when disabled."""
        from query_refinement_module.providers import LiteLLMProvider
        
        with patch('query_refinement_module.providers.llm.litellm'):
            provider = LiteLLMProvider(
                default_model="gpt-4",
                enable_circuit_breaker=False
            )
            
            assert provider._enable_circuit_breaker is False
            assert provider._circuit_breaker_registry is None
    
    @pytest.mark.asyncio
    async def test_llm_provider_get_metrics(self):
        """LLM provider should return circuit breaker metrics."""
        from query_refinement_module.providers import LiteLLMProvider
        
        with patch('query_refinement_module.providers.llm.litellm'):
            provider = LiteLLMProvider(
                default_model="gpt-4",
                enable_circuit_breaker=True
            )
            
            metrics = provider.get_circuit_breaker_metrics()
            
            assert metrics["circuit_breaker_enabled"] is True
            assert "providers" in metrics
    
    @pytest.mark.asyncio
    async def test_llm_provider_metrics_disabled(self):
        """LLM provider should return disabled status when circuit breaker off."""
        from query_refinement_module.providers import LiteLLMProvider
        
        with patch('query_refinement_module.providers.llm.litellm'):
            provider = LiteLLMProvider(
                default_model="gpt-4",
                enable_circuit_breaker=False
            )
            
            metrics = provider.get_circuit_breaker_metrics()
            
            assert metrics["circuit_breaker_enabled"] is False
            assert "providers" not in metrics
