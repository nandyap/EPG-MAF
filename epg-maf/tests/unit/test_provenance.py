"""Unit tests for :class:`egp_maf.state.provenance.DBProvenance`."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from egp_maf.state.provenance import DBProvenance, find_provenance_for_field


def _sample_record(**overrides: object) -> DBProvenance:
    kwargs: dict[str, object] = {
        "tool_name": "get_patient_prs",
        "tool_parameters": {"patient_id": "P001"},
        "source_table": "patient_prs JOIN prs_annotations",
        "source_row": {"prs_name": "PRS_AD_001", "prs_score": 0.42, "percentile": 82},
        "fields_derived": ["prs_score", "percentile"],
    }
    kwargs.update(overrides)
    return DBProvenance(**kwargs)  # type: ignore[arg-type]


class TestConstruction:
    def test_minimal(self) -> None:
        r = _sample_record()
        assert r.tool_name == "get_patient_prs"
        assert r.fields_derived == ["prs_score", "percentile"]
        assert r.trace_id is None
        assert r.span_id is None

    def test_retrieved_at_defaults_to_utc(self) -> None:
        r = _sample_record()
        assert r.retrieved_at.tzinfo is not None

    def test_retrieved_at_override(self) -> None:
        ts = datetime(2026, 7, 9, 12, 0, 0, tzinfo=timezone.utc)
        r = _sample_record(retrieved_at=ts)
        assert r.retrieved_at == ts

    def test_extra_fields_rejected(self) -> None:
        with pytest.raises(ValidationError):
            DBProvenance(
                tool_name="t",
                tool_parameters={},
                source_table="x",
                source_row={},
                fields_derived=[],
                unexpected="boom",  # type: ignore[call-arg]
            )

    def test_frozen(self) -> None:
        r = _sample_record()
        with pytest.raises(ValidationError):
            r.tool_name = "other"  # type: ignore[misc]


class TestJsonRoundTrip:
    def test_round_trip(self) -> None:
        r = _sample_record()
        payload = r.model_dump(mode="json")
        r2 = DBProvenance.model_validate(payload)
        assert r2 == r


class TestFindProvenanceForField:
    def test_returns_matching_record(self) -> None:
        r1 = _sample_record(fields_derived=["percentile"])
        r2 = _sample_record(fields_derived=["prs_score"])
        result = find_provenance_for_field([r1, r2], "prs_score")
        assert result is r2

    def test_returns_none_when_missing(self) -> None:
        r1 = _sample_record(fields_derived=["percentile"])
        assert find_provenance_for_field([r1], "gene") is None

    def test_returns_first_match(self) -> None:
        r1 = _sample_record(fields_derived=["prs_score", "percentile"])
        r2 = _sample_record(fields_derived=["prs_score"])
        assert find_provenance_for_field([r1, r2], "prs_score") is r1


class TestTraceCorrelation:
    def test_optional_ids_can_be_set(self) -> None:
        r = _sample_record(trace_id="abc123", span_id="def456")
        assert r.trace_id == "abc123"
        assert r.span_id == "def456"
