"""Tests for metric logging in tracing providers."""

import json
import tempfile
from pathlib import Path
from query_refinement_module.providers import (
    NoOpTracingProvider,
    ConsoleTracing,
    FileTracingProvider,
    TraceEventEmitter,
)


def test_noop_tracing_log_metric_does_nothing():
    """NoOp tracing provider should silently ignore metrics."""
    provider = NoOpTracingProvider()
    # Should not raise
    provider.log_metric("test.metric", 42.5, unit="seconds")


def test_console_tracing_log_metric(capsys):
    """Console tracing should print metrics to stdout."""
    provider = ConsoleTracing()
    provider.log_metric("parallel.execution_time", 1.234, unit="seconds", metadata={"foo": "bar"})
    
    captured = capsys.readouterr()
    assert "[METRIC]" in captured.out
    assert "parallel.execution_time" in captured.out
    assert "1.234" in captured.out
    assert "seconds" in captured.out
    assert "foo" in captured.out


def test_file_tracing_log_metric():
    """File tracing should write metrics to a separate JSONL file."""
    with tempfile.TemporaryDirectory() as tmpdir:
        provider = FileTracingProvider(tmpdir)
        provider.log_metric(
            "parallel.success_rate",
            95.5,
            unit="percent",
            metadata={"num_aspects": 20}
        )
        
        metrics_file = Path(tmpdir) / "trace_metrics.log"
        assert metrics_file.exists()
        
        with metrics_file.open("r") as f:
            lines = f.readlines()
        
        assert len(lines) == 1
        metric = json.loads(lines[0])
        
        assert metric["metric"] == "parallel.success_rate"
        assert metric["value"] == 95.5
        assert metric["unit"] == "percent"
        assert metric["metadata"]["num_aspects"] == 20
        assert "timestamp" in metric


def test_trace_event_emitter_metric_method():
    """TraceEventEmitter should safely emit metrics through providers."""
    with tempfile.TemporaryDirectory() as tmpdir:
        provider = FileTracingProvider(tmpdir)
        emitter = TraceEventEmitter(provider)
        
        emitter.metric("test.metric", 123.45, unit="ms", metadata={"key": "value"})
        
        metrics_file = Path(tmpdir) / "trace_metrics.log"
        assert metrics_file.exists()
        
        with metrics_file.open("r") as f:
            metric = json.loads(f.read())
        
        assert metric["metric"] == "test.metric"
        assert metric["value"] == 123.45


def test_trace_event_emitter_metric_without_provider():
    """TraceEventEmitter should handle missing provider gracefully."""
    emitter = TraceEventEmitter(None)
    # Should not raise
    emitter.metric("test.metric", 42.0)


def test_trace_event_emitter_metric_swallows_errors():
    """TraceEventEmitter should not propagate provider errors."""
    
    class BrokenProvider(ConsoleTracing):
        def log_metric(self, *args, **kwargs):
            raise RuntimeError("Provider error")
    
    provider = BrokenProvider()
    emitter = TraceEventEmitter(provider)
    
    # Should not raise
    emitter.metric("test.metric", 42.0)


def test_file_tracing_metric_with_no_unit():
    """File tracing should handle metrics without units."""
    with tempfile.TemporaryDirectory() as tmpdir:
        provider = FileTracingProvider(tmpdir)
        provider.log_metric("parallel.avg_concurrency", 3.5)
        
        metrics_file = Path(tmpdir) / "trace_metrics.log"
        with metrics_file.open("r") as f:
            metric = json.loads(f.read())
        
        assert metric["metric"] == "parallel.avg_concurrency"
        assert metric["value"] == 3.5
        assert metric["unit"] == ""
