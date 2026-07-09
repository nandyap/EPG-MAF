"""Tests for :mod:`egp_maf.telemetry.otel`."""

from __future__ import annotations

import os

import pytest

from egp_maf.config.settings import Settings
from egp_maf.telemetry.otel import (
    TelemetryProvider,
    build_telemetry_provider,
    get_current_trace_and_span_ids,
)

pytestmark = pytest.mark.unit

os.environ.setdefault("LLM_API_KEY", "test")


def _settings() -> Settings:
    return Settings()  # type: ignore[call-arg]


class TestBuildTelemetryProvider:
    def test_returns_provider_with_resource(self) -> None:
        provider = build_telemetry_provider(_settings())
        assert isinstance(provider, TelemetryProvider)
        # Resource carries the service metadata.
        assert provider.resource.attributes["service.name"] == "egp-window"
        assert provider.resource.attributes["service.namespace"] == "egp-maf"
        provider.shutdown()

    def test_shutdown_is_idempotent(self) -> None:
        provider = build_telemetry_provider(_settings())
        provider.shutdown()
        provider.shutdown()  # must not raise

    def test_span_exporter_is_in_memory_by_default(self) -> None:
        from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
            InMemorySpanExporter,
        )

        provider = build_telemetry_provider(_settings())
        try:
            assert isinstance(provider.span_exporter, InMemorySpanExporter)
        finally:
            provider.shutdown()


class TestGetCurrentTraceAndSpanIds:
    def test_no_active_span_returns_none_pair(self) -> None:
        trace_id, span_id = get_current_trace_and_span_ids()
        # Outside any span: both None.
        assert (trace_id is None) == (span_id is None)

    def test_inside_a_span_returns_populated_ids(
        self, telemetry_exporter: object  # noqa: ARG002 — installs SDK
    ) -> None:
        from egp_maf.telemetry.spans import specialist_span

        with specialist_span("prs"):
            trace_id, span_id = get_current_trace_and_span_ids()
        assert trace_id is not None
        assert span_id is not None
        assert len(trace_id) == 32  # 128-bit hex
        assert len(span_id) == 16  # 64-bit hex
