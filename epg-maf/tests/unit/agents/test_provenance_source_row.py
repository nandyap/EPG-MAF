"""``source_row`` must be a database row, not a re-serialised result.

Every ``get_patient_*`` repository method builds a :class:`DBProvenance`
at query time from the genuine SQL row (ADR-005). The tool shim then
serialises the whole result — provenance included — into the ReAct tool
output, so the authentic record arrives at
``attach_provenance_to_results`` already inside the row.

It used to be ignored. The ReAct path rebuilt a record with
``source_row=dict(row)``, where ``row`` was that serialised *result
object* — so the audit panel showed ``interpretation``,
``interpretation_model`` and a nested copy of the provenance record under
a heading reading "Database row as retrieved", while omitting real
columns such as ``patient_id``. ``6e1faed`` hid those keys in the UI;
this asserts they are not produced in the first place.

Every pre-existing test passed a bare dict as ``tool_output``, which
carries no provenance — so all of them exercised the fallback and none of
them would have caught this. The fixtures here are built the way the
runtime builds them: a real result model, serialised exactly as
``tool_shims._rows`` serialises it.
"""

from __future__ import annotations

import pytest

from egp_maf.agents.base import ToolCall, attach_provenance_to_results
from egp_maf.agents.family_history import (
    _TOOL_FIELDS_DERIVED,
    _TOOL_SOURCE_TABLE,
)
from egp_maf.state.provenance import DBProvenance
from egp_maf.state.results.family_history import FamilyHistoryCriteriaResult

pytestmark = pytest.mark.unit

# The exact row Postgres returns for the Lynch syndrome case observed on
# 2026-08-26 — note ``patient_id``, which is a column but not a field on
# FamilyHistoryCriteriaResult, so it exists only on this side.
_SQL_ROW = {
    "patient_id": "HG00099",
    "disease_name": "Lynch Syndrome",
    "criteria_name": "Amsterdam II",
    "affected_relative_count": 3,
    "total_relatives_searched": 8,
    "search_context_notes": None,
    "meets_threshold": True,
    "last_observed_diagnosis_in_database": "2025-01-01",
    "criteria_description": ">=3 relatives with Lynch-associated cancer",
    "criteria_source": "NCCN",
}


def _repository_result() -> FamilyHistoryCriteriaResult:
    """What the repository returns: the result plus its query-time record."""
    return FamilyHistoryCriteriaResult(
        disease_name=_SQL_ROW["disease_name"],
        criteria_name=_SQL_ROW["criteria_name"],
        affected_relative_count=_SQL_ROW["affected_relative_count"],
        total_relatives_searched=_SQL_ROW["total_relatives_searched"],
        meets_threshold=True,
        last_observed_diagnosis_in_database=_SQL_ROW[
            "last_observed_diagnosis_in_database"
        ],
        criteria_description=_SQL_ROW["criteria_description"],
        criteria_source=_SQL_ROW["criteria_source"],
        provenance=[
            DBProvenance(
                tool_name="get_patient_family_history",
                tool_parameters={"patient_id": "HG00099"},
                source_table=(
                    "patient_kinship_history LEFT JOIN kinship_history_annotations"
                ),
                source_row=dict(_SQL_ROW),
                fields_derived=list(
                    _TOOL_FIELDS_DERIVED["get_patient_family_history"]
                ),
            )
        ],
    )


def _tool_call() -> ToolCall:
    """The ReAct trace entry, serialised as ``tool_shims._rows`` does it."""
    return ToolCall(
        tool_name="get_patient_family_history",
        # The LLM's own call: no patient_id, which the shim binds itself.
        tool_parameters={"disease_name": "Lynch syndrome"},
        tool_output=[_repository_result().model_dump(mode="json")],
    )


def _extracted_result() -> FamilyHistoryCriteriaResult:
    """What the extraction pass produces — same casing as the row here, so
    the matcher succeeds and this test isolates ``source_row``."""
    return FamilyHistoryCriteriaResult(
        disease_name="Lynch Syndrome",
        criteria_name="Amsterdam II",
        meets_threshold=True,
        interpretation="Meets Amsterdam II criteria.",
    )


def _attach() -> FamilyHistoryCriteriaResult:
    result = _extracted_result()
    attach_provenance_to_results(
        results=[result],
        tool_calls=[_tool_call()],
        tool_source_table=_TOOL_SOURCE_TABLE,
        tool_fields_derived=_TOOL_FIELDS_DERIVED,
        row_matches_result=lambda row, r: (
            row.get("disease_name") == r.disease_name
            and row.get("criteria_name") == r.criteria_name
        ),
    )
    return result


class TestSourceRowIsADatabaseRow:
    def test_llm_authored_keys_are_absent(self) -> None:
        """The regression itself: model prose under a database heading."""
        source_row = _attach().provenance[0].source_row

        assert "interpretation" not in source_row
        assert "interpretation_model" not in source_row

    def test_provenance_is_not_nested_inside_itself(self) -> None:
        source_row = _attach().provenance[0].source_row

        assert "provenance" not in source_row

    def test_real_columns_survive(self) -> None:
        """``patient_id`` is a column but not a model field, so it is
        present only when the record came from the repository."""
        source_row = _attach().provenance[0].source_row

        assert source_row["patient_id"] == "HG00099"
        assert source_row["disease_name"] == "Lynch Syndrome"

    def test_tool_parameters_are_the_repositorys(self) -> None:
        """The LLM's call omits ``patient_id`` — the shim binds it. The
        repository's record is the more complete account of the query."""
        provenance = _attach().provenance[0]

        assert provenance.tool_parameters == {"patient_id": "HG00099"}

    def test_privacy_strip_still_applies(self) -> None:
        """The genuine row carries the privacy columns, so ``to_public``
        must still remove them — a real row is *more* sensitive than the
        serialised model was, not less."""
        result = _attach()

        assert "affected_relative_count" in result.provenance[0].source_row

        public = result.to_public()

        for key in (
            "affected_relative_count",
            "total_relatives_searched",
            "search_context_notes",
        ):
            assert key not in public.provenance[0].source_row

    def test_falls_back_when_row_carries_no_provenance(self) -> None:
        """Bare dicts must still work: that is every other test's fixture,
        and the ``explore``/``search`` shape at runtime."""
        result = _extracted_result()
        attach_provenance_to_results(
            results=[result],
            tool_calls=[
                ToolCall(
                    tool_name="get_patient_family_history",
                    tool_parameters={"patient_id": "HG00099"},
                    tool_output=[
                        {
                            "disease_name": "Lynch Syndrome",
                            "criteria_name": "Amsterdam II",
                        }
                    ],
                )
            ],
            tool_source_table=_TOOL_SOURCE_TABLE,
            tool_fields_derived=_TOOL_FIELDS_DERIVED,
            row_matches_result=lambda row, r: (
                row.get("disease_name") == r.disease_name
            ),
        )

        assert len(result.provenance) == 1
        assert result.provenance[0].source_row["disease_name"] == "Lynch Syndrome"
