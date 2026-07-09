"""Family history domain repository.

Port of the LangGraph prototype tools in ``agents/family_history/tools/tools.py``.

Repositories return the INTERNAL projection (:class:`FamilyHistoryCriteriaResult`).
Callers who cross the orchestrator boundary call ``.to_public()`` on the
model to obtain the privacy-stripped projection (Design ADR-017 / §11.7).

DuckDB → Postgres SQL: ``CAST(x AS VARCHAR)`` for dates becomes
``to_char(x, 'YYYY-MM-DD')`` (produces the same ISO string).
"""

from __future__ import annotations

from typing import Any

from egp_maf.services.repositories.base import BaseRepository
from egp_maf.state.clinician_context import ClinicianContext
from egp_maf.state.results.family_history import (
    FamilyHistoryCriteriaResult,
    FamilyHistoryKey,
    KinshipHistoryAnnotation,
)

# ── SQL ──────────────────────────────────────────────────────────────

_SQL_EXPLORE = """
    SELECT patient_id, disease_name, criteria_name, meets_threshold
    FROM patient_kinship_history
    WHERE patient_id = %s
    ORDER BY disease_name, criteria_name
"""

_SQL_SEARCH_TEMPLATE = """
    SELECT disease_name, criteria_name, description, source
    FROM kinship_history_annotations
    {where}
    ORDER BY disease_name, criteria_name
"""

_SQL_GET_TEMPLATE = """
    SELECT
        pkh.patient_id,
        pkh.disease_name,
        pkh.criteria_name,
        pkh.affected_relative_count,
        pkh.total_relatives_searched,
        pkh.meets_threshold,
        pkh.search_context_notes,
        to_char(pkh.last_observed_diagnosis_in_database, 'YYYY-MM-DD')
            AS last_observed_diagnosis_in_database,
        kha.description AS criteria_description,
        kha.source      AS criteria_source
    FROM patient_kinship_history pkh
    LEFT JOIN kinship_history_annotations kha
        ON pkh.disease_name  = kha.disease_name
       AND pkh.criteria_name = kha.criteria_name
    {where}
    ORDER BY pkh.disease_name, pkh.criteria_name
"""

# Fields on the JOINed row that populate the internal
# FamilyHistoryCriteriaResult. Kept in the provenance record so audit
# reviewers can trace every field to its source row.
_GET_FIELDS_DERIVED: list[str] = [
    "disease_name",
    "criteria_name",
    "affected_relative_count",
    "total_relatives_searched",
    "meets_threshold",
    "search_context_notes",
    "last_observed_diagnosis_in_database",
    "criteria_description",
    "criteria_source",
]
_GET_SOURCE_TABLE = "patient_kinship_history LEFT JOIN kinship_history_annotations"
_GET_TOOL_NAME = "get_patient_family_history"


class FamilyHistoryRepository(BaseRepository):
    """Read-only access to patient kinship / family history data."""

    async def explore_patient_family_history(
        self,
        ctx: ClinicianContext,
        patient_id: str,
    ) -> list[FamilyHistoryKey]:
        self._authorize(ctx, patient_id)
        rows = await self._fetch_all(_SQL_EXPLORE, [patient_id])
        return [
            FamilyHistoryKey(
                disease_name=row["disease_name"],
                criteria_name=row["criteria_name"],
                meets_threshold=bool(row["meets_threshold"]),
            )
            for row in rows
        ]

    async def search_family_history_annotations(
        self,
        ctx: ClinicianContext,  # noqa: ARG002 — reference-only lookup
        *,
        criteria_name: str | None = None,
        disease_name: str | None = None,
    ) -> list[KinshipHistoryAnnotation]:
        conditions: list[str] = []
        params: list[Any] = []
        if criteria_name is not None:
            conditions.append("criteria_name = %s")
            params.append(criteria_name)
        if disease_name is not None:
            conditions.append("disease_name ILIKE %s")
            params.append(f"%{disease_name}%")
        where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
        rows = await self._fetch_all(_SQL_SEARCH_TEMPLATE.format(where=where), params)
        return [KinshipHistoryAnnotation.model_validate(row) for row in rows]

    async def get_patient_family_history(
        self,
        ctx: ClinicianContext,
        patient_id: str,
        *,
        disease_name: str | None = None,
        criteria_name: str | None = None,
    ) -> list[FamilyHistoryCriteriaResult]:
        """Return internal :class:`FamilyHistoryCriteriaResult`s.

        Callers who need the orchestrator-facing (privacy-stripped) view
        call ``.to_public()`` on each returned object.
        """
        self._authorize(ctx, patient_id)

        conditions: list[str] = ["pkh.patient_id = %s"]
        params: list[Any] = [patient_id]
        if disease_name is not None:
            conditions.append("pkh.disease_name = %s")
            params.append(disease_name)
        if criteria_name is not None:
            conditions.append("pkh.criteria_name = %s")
            params.append(criteria_name)
        where = "WHERE " + " AND ".join(conditions)

        rows = await self._fetch_all(_SQL_GET_TEMPLATE.format(where=where), params)

        tool_parameters: dict[str, Any] = {"patient_id": patient_id}
        if disease_name is not None:
            tool_parameters["disease_name"] = disease_name
        if criteria_name is not None:
            tool_parameters["criteria_name"] = criteria_name

        results: list[FamilyHistoryCriteriaResult] = []
        for row in rows:
            provenance = self._build_provenance(
                tool_name=_GET_TOOL_NAME,
                tool_parameters=tool_parameters,
                source_table=_GET_SOURCE_TABLE,
                source_row=row,
                fields_derived=_GET_FIELDS_DERIVED,
            )
            results.append(
                FamilyHistoryCriteriaResult(
                    disease_name=row["disease_name"],
                    criteria_name=row["criteria_name"],
                    affected_relative_count=row.get("affected_relative_count"),
                    total_relatives_searched=row.get("total_relatives_searched"),
                    search_context_notes=row.get("search_context_notes"),
                    last_observed_diagnosis_in_database=row.get(
                        "last_observed_diagnosis_in_database"
                    ),
                    meets_threshold=bool(row["meets_threshold"]),
                    criteria_description=row.get("criteria_description"),
                    criteria_source=row.get("criteria_source"),
                    provenance=[provenance],
                )
            )
        return results
