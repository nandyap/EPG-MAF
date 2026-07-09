"""ProvenanceService — factory for :class:`DBProvenance` records.

Centralising construction here means:

- Every Repository builds provenance the same way (single call site).
- When W08 wires OpenTelemetry, we only edit this file to attach
  ``trace_id`` / ``span_id`` from the active span.
- Unit tests can inject a deterministic clock via ``time_source``.

Design references:

- Design §11.7 — Provenance moved into the Repository (construction-time truth).
- Design §20.6 — Provenance ↔ trace correlation.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any

from egp_maf.state.provenance import DBProvenance


class ProvenanceService:
    """Builds :class:`DBProvenance` records with consistent metadata.

    Parameters
    ----------
    time_source:
        Callable returning the "now" timestamp. Defaults to UTC ``now``.
        Overridden in tests for deterministic outputs.
    otel_context_provider:
        Optional callable returning ``(trace_id, span_id)`` tuples from the
        active OpenTelemetry span. Wired in W08; ``None`` in Phase 1
        foundation.
    """

    def __init__(
        self,
        *,
        time_source: Callable[[], datetime] | None = None,
        otel_context_provider: Callable[[], tuple[str | None, str | None]] | None = None,
    ) -> None:
        self._time_source = time_source or (lambda: datetime.now(timezone.utc))
        self._otel_context_provider = otel_context_provider

    def build(
        self,
        *,
        tool_name: str,
        tool_parameters: dict[str, Any],
        source_table: str,
        source_row: dict[str, Any],
        fields_derived: list[str],
    ) -> DBProvenance:
        """Return a new :class:`DBProvenance` record."""
        trace_id: str | None = None
        span_id: str | None = None
        if self._otel_context_provider is not None:
            try:
                trace_id, span_id = self._otel_context_provider()
            except Exception:
                # Never fail provenance construction because of tracing.
                trace_id, span_id = (None, None)

        return DBProvenance(
            tool_name=tool_name,
            tool_parameters=dict(tool_parameters),
            source_table=source_table,
            source_row=dict(source_row),
            fields_derived=list(fields_derived),
            retrieved_at=self._time_source(),
            trace_id=trace_id,
            span_id=span_id,
        )
