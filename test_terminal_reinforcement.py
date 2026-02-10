#!/usr/bin/env python3
"""
Quick validation tests for terminal reinforcement implementation.
"""
from query_refinement_module.core import QueryRefinementManager
from query_refinement_module.interfaces import LLMProviderInterface, TracingProviderInterface
from query_refinement_module.settings import LLMSettings


class DummyLLM(LLMProviderInterface):
    def complete(self, **kwargs):
        raise NotImplementedError
    
    def get_model_info(self):
        return {"model": "dummy", "version": "1.0"}


class DummyTracing(TracingProviderInterface):
    def create_trace(self, **kwargs):
        raise NotImplementedError

    def finalize_trace(self, **kwargs):
        raise NotImplementedError

    def add_error(self, **kwargs):
        raise NotImplementedError
    
    def trace_operation(self, name, operation_type="function", metadata=None):
        from contextlib import contextmanager
        @contextmanager
        def dummy_context():
            yield
        return dummy_context()
    
    def log_event(self, event_name, level="info", metadata=None):
        pass
    
    def is_enabled(self):
        return False


def test_settings():
    """Test that LLMSettings has the hardcoded threshold."""
    settings = LLMSettings(model='test', api_key='test')
    assert settings.terminal_reinforcement_threshold == 3, \
        f"Expected threshold=3, got {settings.terminal_reinforcement_threshold}"
    print("✓ Test 1: LLMSettings has hardcoded threshold=3")


def test_manager_no_threshold():
    """Test QueryRefinementManager with no threshold parameter."""
    mgr = QueryRefinementManager(
        llm_provider=DummyLLM(),
        tracing_provider=DummyTracing()
    )
    assert mgr.terminal_reinforcement_threshold == 3, \
        f"Expected default threshold=3, got {mgr.terminal_reinforcement_threshold}"
    print(f"✓ Test 2: Manager with no threshold → defaults to {mgr.terminal_reinforcement_threshold}")


def test_manager_explicit_threshold():
    """Test QueryRefinementManager with explicit threshold."""
    mgr = QueryRefinementManager(
        llm_provider=DummyLLM(),
        tracing_provider=DummyTracing(),
        terminal_reinforcement_threshold=5
    )
    assert mgr.terminal_reinforcement_threshold == 5, \
        f"Expected threshold=5, got {mgr.terminal_reinforcement_threshold}"
    print(f"✓ Test 3: Manager with explicit threshold=5 → set to {mgr.terminal_reinforcement_threshold}")


def test_manager_none_threshold():
    """Test QueryRefinementManager with None threshold (should fallback to 3)."""
    mgr = QueryRefinementManager(
        llm_provider=DummyLLM(),
        tracing_provider=DummyTracing(),
        terminal_reinforcement_threshold=None
    )
    assert mgr.terminal_reinforcement_threshold == 3, \
        f"Expected fallback threshold=3, got {mgr.terminal_reinforcement_threshold}"
    print(f"✓ Test 4: Manager with threshold=None → fallback to {mgr.terminal_reinforcement_threshold}")


if __name__ == '__main__':
    print("=" * 60)
    print("Terminal Reinforcement Implementation Validation")
    print("=" * 60)
    print()
    
    test_settings()
    test_manager_no_threshold()
    test_manager_explicit_threshold()
    test_manager_none_threshold()
    
    print()
    print("=" * 60)
    print("✅ All validation tests PASSED!")
    print("=" * 60)
