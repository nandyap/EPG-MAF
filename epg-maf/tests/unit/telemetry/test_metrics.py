"""Tests for :mod:`egp_maf.telemetry.metrics`."""

from __future__ import annotations

import pytest
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import InMemoryMetricReader

from egp_maf.telemetry.metrics import (
    METRIC_NAMES,
    MetricEmitter,
    NullMetricEmitter,
    OtelMetricEmitter,
)

pytestmark = pytest.mark.unit


def _emitter_with_reader() -> tuple[OtelMetricEmitter, InMemoryMetricReader]:
    reader = InMemoryMetricReader()
    provider = MeterProvider(metric_readers=[reader])
    meter = provider.get_meter("test")
    return OtelMetricEmitter(meter), reader


def _collected_metric_names(reader: InMemoryMetricReader) -> set[str]:
    data = reader.get_metrics_data()
    if data is None:
        return set()
    names: set[str] = set()
    for rm in data.resource_metrics:
        for sm in rm.scope_metrics:
            for metric in sm.metrics:
                names.add(metric.name)
    return names


class TestMetricNames:
    def test_exactly_ten_metrics(self) -> None:
        assert len(METRIC_NAMES) == 10

    def test_expected_names(self) -> None:
        assert METRIC_NAMES == frozenset(
            {
                "egp.turn.count",
                "egp.turn.duration_ms",
                "egp.specialist.duration_ms",
                "egp.specialist.failed",
                "egp.tool.duration_ms",
                "egp.llm.tokens.prompt",
                "egp.llm.tokens.completion",
                "egp.db.pool.utilisation",
                "egp.rate_limit.hit",
                "egp.prompt.fallback",
            }
        )


class TestNullEmitter:
    def test_all_methods_are_noops(self) -> None:
        emitter: MetricEmitter = NullMetricEmitter()
        # Nothing raises.
        emitter.emit_turn(outcome="ok", duration_ms=100, cache_hit=False)
        emitter.emit_specialist(domain="prs", status="completed", duration_ms=50)
        emitter.emit_specialist_failed(domain="prs", error_class="RuntimeError")
        emitter.emit_tool(tool="get_patient_prs", duration_ms=12)
        emitter.emit_llm_tokens(model="gpt-4o", prompt_tokens=100, completion_tokens=50)
        emitter.emit_db_pool_utilisation(in_use=3, total=10)
        emitter.emit_rate_limit_hit(upstream="compass")
        emitter.emit_prompt_fallback(prompt_name="prs_agent")


class TestOtelEmitter:
    def test_turn_metric_recorded(self) -> None:
        emitter, reader = _emitter_with_reader()
        emitter.emit_turn(outcome="ok", duration_ms=250, cache_hit=True)
        names = _collected_metric_names(reader)
        assert "egp.turn.count" in names
        assert "egp.turn.duration_ms" in names

    def test_specialist_metrics_recorded(self) -> None:
        emitter, reader = _emitter_with_reader()
        emitter.emit_specialist(domain="prs", status="completed", duration_ms=200)
        emitter.emit_specialist_failed(domain="pgx", error_class="RuntimeError")
        names = _collected_metric_names(reader)
        assert "egp.specialist.duration_ms" in names
        assert "egp.specialist.failed" in names

    def test_llm_token_counters_recorded(self) -> None:
        emitter, reader = _emitter_with_reader()
        emitter.emit_llm_tokens(model="gpt-4o", prompt_tokens=128, completion_tokens=64)
        names = _collected_metric_names(reader)
        assert "egp.llm.tokens.prompt" in names
        assert "egp.llm.tokens.completion" in names

    def test_prompt_fallback_recorded(self) -> None:
        emitter, reader = _emitter_with_reader()
        emitter.emit_prompt_fallback(prompt_name="prs_agent")
        names = _collected_metric_names(reader)
        assert "egp.prompt.fallback" in names
