"""Test: :class:`DBProvenance` carries trace/span ids from active OTEL span
(Design §20.6, F10.5 acceptance)."""

from __future__ import annotations

import pytest

from egp_maf.services.provenance import ProvenanceService
from egp_maf.telemetry.otel import get_current_trace_and_span_ids
from egp_maf.telemetry.spans import specialist_span

pytestmark = pytest.mark.unit


class TestProvenanceTraceCorrelation:
    def test_provenance_gets_trace_and_span_when_inside_span(
        self, telemetry_exporter: object  # noqa: ARG002 — installs SDK
    ) -> None:
        service = ProvenanceService(
            otel_context_provider=get_current_trace_and_span_ids
        )
        with specialist_span("prs"):
            prov = service.build(
                tool_name="get_patient_prs",
                tool_parameters={"patient_id": "P1"},
                source_table="patient_prs JOIN prs_annotations",
                source_row={"prs_name": "PRS_1", "prs_score": 1.0},
                fields_derived=["prs_score"],
            )
        assert prov.trace_id is not None
        assert prov.span_id is not None
        assert len(prov.trace_id) == 32
        assert len(prov.span_id) == 16

    def test_provenance_has_null_ids_outside_span(self) -> None:
        service = ProvenanceService(
            otel_context_provider=get_current_trace_and_span_ids
        )
        prov = service.build(
            tool_name="get_patient_prs",
            tool_parameters={"patient_id": "P1"},
            source_table="patient_prs JOIN prs_annotations",
            source_row={"prs_name": "PRS_1"},
            fields_derived=["prs_score"],
        )
        assert prov.trace_id is None
        assert prov.span_id is None

    def test_provenance_never_raises_from_context_provider(self) -> None:
        """A broken OTEL context provider must not take down provenance."""

        def _broken() -> tuple[str | None, str | None]:
            raise RuntimeError("otel is on fire")

        service = ProvenanceService(otel_context_provider=_broken)
        prov = service.build(
            tool_name="get_patient_prs",
            tool_parameters={},
            source_table="x",
            source_row={},
            fields_derived=[],
        )
        assert prov.trace_id is None
        assert prov.span_id is None
