import logging
from contextlib import contextmanager
from typing import Any, Optional, Dict

__all__ = [
    "NoOpTracingProvider",
    "ConsoleTracing",
    "TraceEventEmitter",
]

from .interfaces import TracingProviderInterface

# ========
# Tracing Utilities
# ========
logger = logging.getLogger(__name__)


class TraceEventEmitter:
    """Helper that safely emits events through a tracing provider implementation."""

    def __init__(self, tracing_provider: Optional[TracingProviderInterface]) -> None:
        self._provider = tracing_provider

    def emit(
        self,
        event_name: str,
        level: str = "info",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        provider = self._provider

        if not provider:
            return

        if not hasattr(provider, "log_event") or not hasattr(provider, "is_enabled"):
            logger.debug(
                "Tracing provider %s does not support event logging",
                type(provider).__name__,
            )
            return

        try:
            if provider.is_enabled():
                provider.log_event(event_name, level=level, metadata=metadata)
        except Exception:  # pragma: no cover - tracing must not break core logic
            logger.debug(
                "Tracing provider %s failed to log event '%s'",
                type(provider).__name__,
                event_name,
                exc_info=True,
            )


# ========
# Tracing Providers
# ========
class NoOpTracingProvider(TracingProviderInterface):
    """Simple no-op tracing provider for when tracing is disabled."""
    
    @contextmanager
    def trace_operation(self, name, operation_type = "function", metadata = None):
        yield
    
    def log_event(self, event_name, level = "info", metadata = None):
        pass

    def is_enabled(self) -> bool:
        return False

class ConsoleTracing(TracingProviderInterface):
    """A simple tracing provider that logs tracing information to the console."""
    
    @contextmanager
    def trace_operation(self, name: str, operation_type: str = "function", metadata: Optional[Dict[str, Any]] = None):
        print(f"[TRACE START] {operation_type.upper()}: {name} | Metadata: {metadata}")
        try:
            yield
            print(f"[TRACE END] {operation_type.upper()}: {name} - SUCCESS")
        except Exception as e:
            print(f"[TRACE END] {operation_type.upper()}: {name} - ERROR: {e}")
            raise
    
    def log_event(self, event_name: str, level: str = "info", metadata: Optional[Dict[str, Any]] = None):
        print(f"[EVENT] Level: {level.upper()} | Event: {event_name} | Metadata: {metadata}")

    def is_enabled(self) -> bool:
        return True
    


