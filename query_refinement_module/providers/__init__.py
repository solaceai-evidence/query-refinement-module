"""
Providers package for query refinement module.

This package contains LLM, tracing, and storage provider implementations.
Extracted from monolithic providers.py as part of v2.0.0 Phase 4 refactoring.

Backward compatibility: All public classes are re-exported from this __init__.py
so existing imports like `from query_refinement_module.providers import LiteLLMProvider`
will continue to work without modification.
"""

# Re-export tracing providers
from .tracing import (
    ConsoleTracing,
    FileTracingProvider,
    NoOpTracingProvider,
    TraceEventEmitter,
)

# Re-export storage providers
from .storage import (
    ConcurrentSessionStorage,
    InMemorySessionStorage,
    RedisSessionStorage,
)

# Re-export LLM provider
from .llm import LiteLLMProvider

__all__ = [
    # Tracing providers
    "NoOpTracingProvider",
    "ConsoleTracing",
    "FileTracingProvider",
    "TraceEventEmitter",
    # Storage providers
    "InMemorySessionStorage",
    "RedisSessionStorage",
    "ConcurrentSessionStorage",
    # LLM provider
    "LiteLLMProvider",
]
