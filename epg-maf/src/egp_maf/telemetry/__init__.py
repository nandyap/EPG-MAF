"""Telemetry module — W08.

Design references:

- Design §20 (OTEL span + metric taxonomy).
- Design §20.6 (Provenance ↔ trace correlation).
- Design §10.4 (PHI-safe serialisation).

Package layout:

- :mod:`.attributes` — canonical set of allowed / forbidden attribute
  names. The load-bearing part; CI checks import from here.
- :mod:`.otel` — :class:`TelemetryProvider` that bootstraps the OTEL
  SDK (tracer + meter). Idempotent; safe to call in unit tests. Uses
  the SDK's :class:`InMemorySpanExporter` when no exporter is
  configured so tests can assert on emitted spans without a network
  call.
- :mod:`.phi_safe` — attribute-set guard raised by :mod:`.spans` when
  a caller tries to attach a forbidden key.
- :mod:`.spans` — high-level context managers per span kind
  (``workflow.request``, ``workflow.executor``, ``tool.call``,
  ``llm.call``, ``db.query``, ``repository.read``, etc.).
- :mod:`.metrics` — 10 metric instruments named in Design §20.4.

MAF autoinstrumentation for the Agent Framework spans is deliberately
out of scope in W08 — the manual spans below are the only ones the
customer-code emits. W08's :class:`TelemetryProvider` is compatible
with adding autoinstrumentation later (both would attach to the same
:class:`TracerProvider`).
"""

from egp_maf.telemetry.attributes import (
    ALLOWED_ATTRIBUTES,
    FORBIDDEN_ATTRIBUTES,
    filter_safe_attributes,
    is_forbidden_attribute,
)
from egp_maf.telemetry.metrics import (
    METRIC_NAMES,
    MetricEmitter,
    OtelMetricEmitter,
    NullMetricEmitter,
)
from egp_maf.telemetry.otel import (
    TelemetryProvider,
    build_telemetry_provider,
    get_current_trace_and_span_ids,
)
from egp_maf.telemetry.phi_safe import ForbiddenAttributeError, safe_set_attribute
from egp_maf.telemetry.spans import (
    SpanKind,
    db_span,
    llm_span,
    repository_span,
    specialist_span,
    tool_span,
    workflow_executor_span,
    workflow_request_span,
)

__all__ = [
    "ALLOWED_ATTRIBUTES",
    "FORBIDDEN_ATTRIBUTES",
    "ForbiddenAttributeError",
    "METRIC_NAMES",
    "MetricEmitter",
    "NullMetricEmitter",
    "OtelMetricEmitter",
    "SpanKind",
    "TelemetryProvider",
    "build_telemetry_provider",
    "db_span",
    "filter_safe_attributes",
    "get_current_trace_and_span_ids",
    "is_forbidden_attribute",
    "llm_span",
    "repository_span",
    "safe_set_attribute",
    "specialist_span",
    "tool_span",
    "workflow_executor_span",
    "workflow_request_span",
]
