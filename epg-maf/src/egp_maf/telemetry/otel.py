"""OTEL SDK bootstrap.

Owns the process-wide :class:`TracerProvider` + :class:`MeterProvider`.
Idempotent: safe to construct multiple times, safe to call ``shutdown``
multiple times. In unit tests we use :class:`InMemorySpanExporter` so
tests can assert on emitted spans without a network call.

Production wiring will add the Azure Monitor OTLP exporter alongside
this SDK setup (deploy-time config; not shipped in W08 to keep the
runtime dependency footprint small). W08 exposes an
:attr:`TelemetryProvider.tracer_provider` hook so the exporter is a
single :meth:`add_span_processor` call away.
"""

from __future__ import annotations

import atexit
import logging
from typing import Any

from opentelemetry import metrics as _otel_metrics
from opentelemetry import trace as _otel_trace
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import (
    InMemoryMetricReader,
    MetricReader,
)
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import (
    BatchSpanProcessor,
    SimpleSpanProcessor,
    SpanExporter,
)
from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
    InMemorySpanExporter,
)
from opentelemetry.trace import Span, get_current_span

from egp_maf.config.settings import Settings

_logger = logging.getLogger(__name__)


class TelemetryProvider:
    """Owns the OTEL :class:`TracerProvider` + :class:`MeterProvider`.

    Constructed once at DI startup. Not attached as global providers by
    default — callers who want :func:`opentelemetry.trace.get_tracer`
    to use *this* provider must call :meth:`install_globally`. Unit
    tests skip that step so each test can build a fresh provider
    without polluting the process-global state.
    """

    def __init__(
        self,
        *,
        resource: Resource,
        tracer_provider: TracerProvider,
        meter_provider: MeterProvider,
        span_exporter: SpanExporter | None,
        metric_reader: MetricReader,
    ) -> None:
        self._resource = resource
        self._tracer_provider = tracer_provider
        self._meter_provider = meter_provider
        self._span_exporter = span_exporter
        self._metric_reader = metric_reader
        self._installed_globally = False
        self._shut_down = False

    # ── Public API ──────────────────────────────────────────────────

    @property
    def tracer_provider(self) -> TracerProvider:
        return self._tracer_provider

    @property
    def meter_provider(self) -> MeterProvider:
        return self._meter_provider

    @property
    def resource(self) -> Resource:
        return self._resource

    @property
    def span_exporter(self) -> SpanExporter | None:
        """The primary in-memory / test exporter — production adds
        additional processors alongside via
        :meth:`tracer_provider.add_span_processor`."""
        return self._span_exporter

    @property
    def metric_reader(self) -> MetricReader:
        return self._metric_reader

    def install_globally(self) -> None:
        """Attach this provider to the ``opentelemetry`` global providers.

        Called once by production startup; not called from unit tests
        (each test gets its own :class:`TelemetryProvider`).
        """
        if self._installed_globally:
            return
        _otel_trace.set_tracer_provider(self._tracer_provider)
        _otel_metrics.set_meter_provider(self._meter_provider)
        self._installed_globally = True
        atexit.register(self.shutdown)
        _logger.info(
            "telemetry.installed_globally",
            extra={
                "service.name": self._resource.attributes.get("service.name"),
                "service.version": self._resource.attributes.get("service.version"),
            },
        )

    def shutdown(self) -> None:
        """Flush all exporters and shut them down. Idempotent."""
        if self._shut_down:
            return
        try:
            self._tracer_provider.shutdown()
        except Exception:  # noqa: BLE001 — shutdown must never fail
            _logger.exception("telemetry.tracer_shutdown_failed")
        try:
            self._meter_provider.shutdown()
        except Exception:  # noqa: BLE001
            _logger.exception("telemetry.meter_shutdown_failed")
        self._shut_down = True

    # ── Test helpers ────────────────────────────────────────────────

    def collected_spans(self) -> list[Any]:
        """Return all spans captured by the in-memory exporter.

        Only meaningful when the provider was built with the default
        :class:`InMemorySpanExporter` (unit tests). Returns an empty
        list otherwise.
        """
        exporter = self._span_exporter
        if isinstance(exporter, InMemorySpanExporter):
            return list(exporter.get_finished_spans())
        return []

    def clear_captured(self) -> None:
        """Drop captured spans + collected metric points. Test-only."""
        if isinstance(self._span_exporter, InMemorySpanExporter):
            self._span_exporter.clear()


# ── Factory ─────────────────────────────────────────────────────────


def build_telemetry_provider(
    settings: Settings,
    *,
    span_exporter: SpanExporter | None = None,
    metric_reader: MetricReader | None = None,
) -> TelemetryProvider:
    """Construct a :class:`TelemetryProvider` from :class:`Settings`.

    Defaults are safe for unit tests: an :class:`InMemorySpanExporter`
    behind a :class:`SimpleSpanProcessor` and an
    :class:`InMemoryMetricReader`. Production overrides both by
    supplying real exporters via the ``span_exporter`` / ``metric_reader``
    kwargs, or by attaching additional processors to
    :attr:`TelemetryProvider.tracer_provider` after construction.
    """
    resource = Resource.create(
        {
            "service.name": "egp-window",
            "service.version": settings.service_version,
            "service.namespace": "egp-maf",
            "deployment.environment": settings.env,
        }
    )

    resolved_span_exporter: SpanExporter = span_exporter or InMemorySpanExporter()
    resolved_metric_reader: MetricReader = (
        metric_reader if metric_reader is not None else InMemoryMetricReader()
    )

    tracer_provider = TracerProvider(resource=resource)
    # SimpleSpanProcessor is best for tests (synchronous flush).
    # Production callers replace with BatchSpanProcessor + real
    # exporter via :meth:`add_span_processor`. Both remain compatible
    # with the primary in-memory exporter attached here.
    if isinstance(resolved_span_exporter, InMemorySpanExporter):
        tracer_provider.add_span_processor(
            SimpleSpanProcessor(resolved_span_exporter)
        )
    else:
        tracer_provider.add_span_processor(
            BatchSpanProcessor(resolved_span_exporter)
        )

    meter_provider = MeterProvider(
        resource=resource,
        metric_readers=[resolved_metric_reader],
    )

    return TelemetryProvider(
        resource=resource,
        tracer_provider=tracer_provider,
        meter_provider=meter_provider,
        span_exporter=resolved_span_exporter,
        metric_reader=resolved_metric_reader,
    )


# ── OTEL context helper for the ProvenanceService ───────────────────


def get_current_trace_and_span_ids() -> tuple[str | None, str | None]:
    """Return the ``(trace_id, span_id)`` of the currently-active OTEL
    span, or ``(None, None)`` when no span is active.

    Used by :class:`egp_maf.services.provenance.ProvenanceService` to
    stamp :class:`DBProvenance` records with the correlation ids
    Design §20.6 requires. Non-throwing — a broken OTEL setup should
    never take down provenance construction.
    """
    try:
        span = get_current_span()
    except Exception:  # noqa: BLE001 — defensive
        return None, None

    if span is None or not _is_span_recording(span):
        return None, None

    context = span.get_span_context()
    if not context or not context.is_valid:
        return None, None
    trace_id = f"{context.trace_id:032x}"
    span_id = f"{context.span_id:016x}"
    return trace_id, span_id


def _is_span_recording(span: Span) -> bool:
    """OTEL's ``NonRecordingSpan`` doesn't have :meth:`is_recording`;
    guard with ``hasattr``."""
    return bool(getattr(span, "is_recording", lambda: False)())
