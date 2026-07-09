"""Tests for :mod:`egp_maf.telemetry.phi_safe`."""

from __future__ import annotations

import pytest
from opentelemetry import trace
from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
    InMemorySpanExporter,
)

from egp_maf.telemetry.phi_safe import ForbiddenAttributeError, safe_set_attribute

pytestmark = pytest.mark.unit


class TestSafeSetAttribute:
    def test_allowed_attribute_is_set(
        self, telemetry_exporter: InMemorySpanExporter
    ) -> None:
        tracer = trace.get_tracer("test")
        with tracer.start_as_current_span("s") as span:
            safe_set_attribute(span, "specialist.name", "prs")
        collected = telemetry_exporter.get_finished_spans()
        assert len(collected) == 1
        assert collected[0].attributes["specialist.name"] == "prs"

    def test_forbidden_attribute_raises(
        self, telemetry_exporter: InMemorySpanExporter
    ) -> None:
        tracer = trace.get_tracer("test")
        with tracer.start_as_current_span("s") as span:
            with pytest.raises(ForbiddenAttributeError):
                safe_set_attribute(span, "prompt_text", "hello")
            with pytest.raises(ForbiddenAttributeError):
                safe_set_attribute(span, "search_context_notes", "x")

    def test_unknown_attribute_silently_dropped(
        self, telemetry_exporter: InMemorySpanExporter
    ) -> None:
        """Unknown-but-not-forbidden names are ignored (surface as
        missing attributes in dashboards)."""
        tracer = trace.get_tracer("test")
        with tracer.start_as_current_span("s") as span:
            safe_set_attribute(span, "unknown.name", "value")
        collected = telemetry_exporter.get_finished_spans()
        assert "unknown.name" not in (collected[0].attributes or {})

    def test_none_value_dropped(
        self, telemetry_exporter: InMemorySpanExporter
    ) -> None:
        tracer = trace.get_tracer("test")
        with tracer.start_as_current_span("s") as span:
            safe_set_attribute(span, "specialist.name", None)
        collected = telemetry_exporter.get_finished_spans()
        assert "specialist.name" not in (collected[0].attributes or {})
