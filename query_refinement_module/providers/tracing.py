"""
Tracing provider implementations.

Extracted from providers.py as part of v2.0.0 Phase 4 refactoring.
"""
import json
import threading
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Dict, Optional

from ..interfaces import TracingProviderInterface
from ..tracing import get_request_id, get_trace_id


class TraceEventEmitter:
    """Helper that safely emits events and metrics through a tracing provider."""

    def __init__(self, tracing_provider: Optional[TracingProviderInterface]) -> None:
        self._provider = tracing_provider

    def emit(
        self,
        event_name: str,
        level: str = "info",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Emit a trace event. Silently fails if provider is None or disabled."""
        if not self._provider or not self._provider.is_enabled():
            return
        try:
            self._provider.log_event(event_name, level=level, metadata=metadata)
        except Exception:  # pragma: no cover - tracing must not break core logic
            pass
    
    def metric(
        self,
        metric_name: str,
        value: float,
        unit: str = "",
        metadata: Optional[Dict[str, Any]] = None
    ) -> None:
        """Emit a metric. Silently fails if provider is None or disabled."""
        if not self._provider or not self._provider.is_enabled():
            return
        try:
            self._provider.log_metric(metric_name, value, unit=unit, metadata=metadata)
        except Exception:  # pragma: no cover - metrics must not break core logic
            pass


class NoOpTracingProvider(TracingProviderInterface):
    """Simple no-op tracing provider for when tracing is disabled."""
    
    @contextmanager
    def trace_operation(self, name, operation_type = "function", metadata = None):
        yield
    
    def log_event(self, event_name, level = "info", metadata = None):
        pass
    
    def log_metric(self, metric_name: str, value: float, unit: str = "", metadata: Optional[Dict[str, Any]] = None):
        pass  # No-op: metrics are not logged when tracing is disabled

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
    
    def log_metric(self, metric_name: str, value: float, unit: str = "", metadata: Optional[Dict[str, Any]] = None):
        unit_str = f" {unit}" if unit else ""
        metadata_str = f" | Metadata: {metadata}" if metadata else ""
        print(f"[METRIC] {metric_name}: {value}{unit_str}{metadata_str}")

    def is_enabled(self) -> bool:
        return True


class FileTracingProvider(TracingProviderInterface):
    """Persist tracing operations and events to JSONL files on disk."""

    def __init__(
        self,
        log_dir: str,
        *,
        operations_filename: str = "trace_operations.log",
        events_filename: str = "trace_events.log",
    ) -> None:
        self._log_dir = Path(log_dir)
        self._log_dir.mkdir(parents=True, exist_ok=True)
        self._operations_file = self._log_dir / operations_filename
        self._events_file = self._log_dir / events_filename
        self._lock = threading.RLock()
        self._enabled = True

    @contextmanager
    def trace_operation(
        self,
        name: str,
        operation_type: str = "function",
        metadata: Optional[Dict[str, Any]] = None,
    ):
        start_payload = {
            "timestamp": self._timestamp(),
            "name": name,
            "operation_type": operation_type,
            "metadata": metadata or {},
            "event": "start",
            **self._trace_context(),
        }
        self._write_json_line(self._operations_file, start_payload)
        try:
            yield
        except Exception as exc:
            failure_payload = {
                "timestamp": self._timestamp(),
                "name": name,
                "operation_type": operation_type,
                "metadata": metadata or {},
                "event": "end",
                "status": "error",
                "error": str(exc),
                **self._trace_context(),
            }
            self._write_json_line(self._operations_file, failure_payload)
            raise
        else:
            success_payload = {
                "timestamp": self._timestamp(),
                "name": name,
                "operation_type": operation_type,
                "metadata": metadata or {},
                "event": "end",
                "status": "success",
                **self._trace_context(),
            }
            self._write_json_line(self._operations_file, success_payload)

    def log_event(
        self,
        event_name: str,
        level: str = "info",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        payload = {
            "timestamp": self._timestamp(),
            "event": event_name,
            "level": level,
            "metadata": metadata or {},
            **self._trace_context(),
        }
        self._write_json_line(self._events_file, payload)
    
    def log_metric(
        self,
        metric_name: str,
        value: float,
        unit: str = "",
        metadata: Optional[Dict[str, Any]] = None
    ) -> None:
        """Log a metric to the metrics file (separate from events)."""
        metrics_file = self._log_dir / "trace_metrics.log"
        payload = {
            "timestamp": self._timestamp(),
            "metric": metric_name,
            "value": value,
            "unit": unit,
            "metadata": metadata or {},
            **self._trace_context(),
        }
        self._write_json_line(metrics_file, payload)

    def is_enabled(self) -> bool:
        return self._enabled

    @staticmethod
    def _trace_context() -> Dict[str, str]:
        """Return current request_id and trace_id from ContextVars if set."""
        ctx: Dict[str, str] = {}
        request_id = get_request_id()
        trace_id = get_trace_id()
        if request_id:
            ctx["request_id"] = request_id
        if trace_id:
            ctx["trace_id"] = trace_id
        return ctx

    def _write_json_line(self, file_path: Path, payload: Dict[str, Any]) -> None:
        with self._lock:
            with file_path.open("a", encoding="utf-8") as fh:
                json.dump(payload, fh, ensure_ascii=True)
                fh.write("\n")

    @staticmethod
    def _timestamp() -> str:
        return datetime.now(UTC).isoformat().replace("+00:00", "Z")
