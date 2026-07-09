"""Unit tests for :class:`egp_maf.services.provenance.ProvenanceService`."""

from __future__ import annotations

from datetime import datetime, timezone

from egp_maf.services.provenance import ProvenanceService


class TestProvenanceServiceBuild:
    def test_produces_valid_record(self) -> None:
        svc = ProvenanceService()
        record = svc.build(
            tool_name="get_patient_prs",
            tool_parameters={"patient_id": "P001"},
            source_table="patient_prs JOIN prs_annotations",
            source_row={"prs_name": "PRS_AD_001", "percentile": 82},
            fields_derived=["prs_name", "percentile"],
        )
        assert record.tool_name == "get_patient_prs"
        assert record.fields_derived == ["prs_name", "percentile"]

    def test_time_source_is_used(self) -> None:
        fixed = datetime(2026, 7, 9, 10, 0, 0, tzinfo=timezone.utc)
        svc = ProvenanceService(time_source=lambda: fixed)
        record = svc.build(
            tool_name="x",
            tool_parameters={},
            source_table="t",
            source_row={},
            fields_derived=[],
        )
        assert record.retrieved_at == fixed

    def test_inputs_are_copied(self) -> None:
        svc = ProvenanceService()
        params = {"patient_id": "P001"}
        row = {"prs_name": "PRS_AD_001"}
        fields = ["prs_name"]
        record = svc.build(
            tool_name="x",
            tool_parameters=params,
            source_table="t",
            source_row=row,
            fields_derived=fields,
        )
        # Mutate the inputs — the record must not reflect the change.
        params["patient_id"] = "P999"
        row["prs_name"] = "OTHER"
        fields.append("gene")

        assert record.tool_parameters == {"patient_id": "P001"}
        assert record.source_row == {"prs_name": "PRS_AD_001"}
        assert record.fields_derived == ["prs_name"]


class TestOtelContextProvider:
    def test_provider_populates_ids(self) -> None:
        svc = ProvenanceService(otel_context_provider=lambda: ("t-1", "s-1"))
        record = svc.build(
            tool_name="x",
            tool_parameters={},
            source_table="t",
            source_row={},
            fields_derived=[],
        )
        assert record.trace_id == "t-1"
        assert record.span_id == "s-1"

    def test_provider_exception_is_swallowed(self) -> None:
        def bad_provider() -> tuple[str | None, str | None]:
            raise RuntimeError("no active span")

        svc = ProvenanceService(otel_context_provider=bad_provider)
        record = svc.build(
            tool_name="x",
            tool_parameters={},
            source_table="t",
            source_row={},
            fields_derived=[],
        )
        assert record.trace_id is None
        assert record.span_id is None

    def test_no_provider_leaves_ids_none(self) -> None:
        svc = ProvenanceService()
        record = svc.build(
            tool_name="x",
            tool_parameters={},
            source_table="t",
            source_row={},
            fields_derived=[],
        )
        assert record.trace_id is None
        assert record.span_id is None
