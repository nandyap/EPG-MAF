"""Unit tests for the family-history privacy-strip logic.

The strip is the load-bearing PHI-safety mechanism in the target design
(Design ADR-017 / §11.7). These tests verify the two contracts:

1. Privacy-sensitive fields never appear on the public projection model.
2. The same fields are removed from every ``DBProvenance.source_row``
   attached to the public results.
"""

from __future__ import annotations

from egp_maf.state.provenance import DBProvenance
from egp_maf.state.results import (
    FamilyHistoryCriteriaResult,
    FamilyHistoryCriteriaResultPublic,
    FamilyHistoryResultList,
    FamilyHistoryResultListPublic,
)


def _sample_provenance() -> DBProvenance:
    """Provenance record containing every privacy-sensitive key in source_row."""
    return DBProvenance(
        tool_name="get_patient_family_history",
        tool_parameters={"patient_id": "P001"},
        source_table="patient_kinship_history LEFT JOIN kinship_history_annotations",
        source_row={
            "disease_name": "Breast Cancer",
            "criteria_name": "NCCN HBOC",
            "meets_threshold": False,
            # PHI-sensitive keys — MUST be stripped from public projection:
            "affected_relative_count": 0,
            "total_relatives_searched": 0,
            "search_context_notes": "0 eligible females over 30 included in search",
            "last_observed_diagnosis_in_database": "2026-06-01",
            "criteria_description": "NCCN 2024 HBOC threshold",
            "criteria_source": "NCCN 2024",
        },
        fields_derived=[
            "disease_name",
            "criteria_name",
            "meets_threshold",
            "affected_relative_count",
            "total_relatives_searched",
            "search_context_notes",
        ],
    )


def _sample_internal_result() -> FamilyHistoryCriteriaResult:
    return FamilyHistoryCriteriaResult(
        disease_name="Breast Cancer",
        criteria_name="NCCN HBOC",
        affected_relative_count=0,
        total_relatives_searched=0,
        search_context_notes="0 eligible females over 30 included in search",
        last_observed_diagnosis_in_database="2026-06-01",
        meets_threshold=False,
        criteria_description="NCCN 2024 HBOC threshold",
        criteria_source="NCCN 2024",
        provenance=[_sample_provenance()],
    )


PRIVACY_KEYS = frozenset(
    {"affected_relative_count", "total_relatives_searched", "search_context_notes"}
)


class TestSingleResultStrip:
    def test_public_projection_omits_privacy_fields(self) -> None:
        result = _sample_internal_result()
        public = result.to_public()

        assert isinstance(public, FamilyHistoryCriteriaResultPublic)
        # Fields on the public model itself. Pydantic 2.11+ requires accessing
        # ``model_fields`` from the class, not the instance.
        public_fields = set(FamilyHistoryCriteriaResultPublic.model_fields.keys())
        for key in PRIVACY_KEYS:
            assert key not in public_fields, f"privacy field {key} leaked to public model"

    def test_provenance_source_row_stripped(self) -> None:
        result = _sample_internal_result()
        public = result.to_public()
        for prov in public.provenance:
            for key in PRIVACY_KEYS:
                assert key not in prov.source_row, (
                    f"privacy field {key} still present in provenance source_row"
                )

    def test_non_privacy_fields_preserved_in_provenance(self) -> None:
        result = _sample_internal_result()
        public = result.to_public()
        prov = public.provenance[0]
        # Non-sensitive keys must remain — the audit trail otherwise dies.
        for key in (
            "disease_name",
            "criteria_name",
            "meets_threshold",
            "last_observed_diagnosis_in_database",
            "criteria_description",
            "criteria_source",
        ):
            assert key in prov.source_row, (
                f"non-privacy field {key} accidentally stripped"
            )

    def test_original_result_unchanged(self) -> None:
        """to_public MUST NOT mutate the internal result."""
        result = _sample_internal_result()
        original_prov_row = dict(result.provenance[0].source_row)
        _ = result.to_public()
        # Internal record still carries privacy fields.
        assert result.affected_relative_count == 0
        assert result.search_context_notes is not None
        assert result.provenance[0].source_row == original_prov_row


class TestListStrip:
    def test_result_list_to_public(self) -> None:
        internal = FamilyHistoryResultList.from_results(
            "P001", [_sample_internal_result(), _sample_internal_result()]
        )
        public = internal.to_public()

        assert isinstance(public, FamilyHistoryResultListPublic)
        assert len(public.results) == 2
        # Every result in the public list is the public projection.
        for r in public.results:
            assert isinstance(r, FamilyHistoryCriteriaResultPublic)
            for prov in r.provenance:
                for key in PRIVACY_KEYS:
                    assert key not in prov.source_row

    def test_diseases_meeting_threshold_carried_over(self) -> None:
        met = _sample_internal_result().model_copy(update={"meets_threshold": True})
        internal = FamilyHistoryResultList.from_results(
            "P001", [_sample_internal_result(), met]
        )
        public = internal.to_public()
        assert set(public.diseases_meeting_threshold) == {"Breast Cancer"}
