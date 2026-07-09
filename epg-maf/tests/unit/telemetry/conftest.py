"""Shared fixtures for :mod:`egp_maf.telemetry` tests.

OTEL's :func:`opentelemetry.trace.set_tracer_provider` only accepts
the first call in the process — subsequent invocations log a warning
and silently no-op. So the pattern for testing our spans is: set the
provider **once**, then clear the in-memory exporter between tests.
"""

from __future__ import annotations

import pytest
from opentelemetry import metrics as _metrics
from opentelemetry import trace as _trace
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import InMemoryMetricReader
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
    InMemorySpanExporter,
)

# ── Session-scoped: install the SDK once, share across tests ─────────

_SESSION_EXPORTER: InMemorySpanExporter | None = None
_SESSION_METRIC_READER: InMemoryMetricReader | None = None


def _ensure_session_provider() -> tuple[InMemorySpanExporter, InMemoryMetricReader]:
    global _SESSION_EXPORTER, _SESSION_METRIC_READER
    if _SESSION_EXPORTER is None or _SESSION_METRIC_READER is None:
        exporter = InMemorySpanExporter()
        reader = InMemoryMetricReader()
        tp = TracerProvider()
        tp.add_span_processor(SimpleSpanProcessor(exporter))
        _trace.set_tracer_provider(tp)
        mp = MeterProvider(metric_readers=[reader])
        _metrics.set_meter_provider(mp)
        _SESSION_EXPORTER = exporter
        _SESSION_METRIC_READER = reader
    return _SESSION_EXPORTER, _SESSION_METRIC_READER


@pytest.fixture
def telemetry_exporter() -> InMemorySpanExporter:
    exporter, _ = _ensure_session_provider()
    exporter.clear()
    return exporter


@pytest.fixture
def telemetry_metric_reader() -> InMemoryMetricReader:
    _, reader = _ensure_session_provider()
    return reader
