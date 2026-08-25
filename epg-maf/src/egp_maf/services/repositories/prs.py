"""PRS domain repository.

Port of the LangGraph prototype tools in ``agents/prs/tools/tools.py``.
Three methods mirror the prototype's ``@tool``s one-for-one, but return
typed :mod:`egp_maf.state.results.prs` models instead of dicts.

Provenance is built at query time inside :meth:`get_patient_prs`
(Design §11.7). ``explore`` and ``search`` don't build provenance —
consistent with prototype behaviour (Discovery §5.7).
"""

from __future__ import annotations

from typing import Any

from egp_maf.services.repositories.base import BaseRepository
from egp_maf.state.clinician_context import ClinicianContext
from egp_maf.state.results.prs import PRSAnnotation, PRSKey, PRSResult

# ── SQL — verbatim port of the prototype, Postgres-adjusted ──────────
# ? → %s. Everything else unchanged (ILIKE is native Postgres).

_SQL_EXPLORE = """
    SELECT patient_id, prs_name, disease_name, risk_band
    FROM patient_prs
    WHERE patient_id = %s
    ORDER BY disease_name
"""

_SQL_SEARCH_TEMPLATE = """
    SELECT prs_name, disease_name, source, notes
    FROM prs_annotations
    {where}
    ORDER BY disease_name
"""

_SQL_GET_TEMPLATE = """
    SELECT pp.patient_id, pp.prs_name, pp.disease_name, pp.prs_score,
           pp.percentile, pp.risk_band,
           pa.source, pa.notes AS metadata_notes
    FROM patient_prs pp
    LEFT JOIN prs_annotations pa ON pp.prs_name = pa.prs_name
    WHERE {where}
"""

# Fields on the JOINed row that become PRSResult DB-sourced fields.
_GET_FIELDS_DERIVED: list[str] = [
    "prs_name",
    "disease_name",
    "prs_score",
    "percentile",
    "risk_band",
    "source",
    "metadata_notes",
]
_GET_SOURCE_TABLE = "patient_prs JOIN prs_annotations"
_GET_TOOL_NAME = "get_patient_prs"


class PRSRepository(BaseRepository):
    """Read-only access to PRS data."""

    async def explore_patient_prs(
        self,
        ctx: ClinicianContext,
        patient_id: str,
    ) -> list[PRSKey]:
        """Return the PRS keys recorded for the patient. No JOIN, no provenance."""
        self._authorize(ctx, patient_id)
        rows = await self._fetch_all(_SQL_EXPLORE, [patient_id])
        return [
            PRSKey(
                prs_name=row["prs_name"],
                disease_name=row["disease_name"],
                risk_band=row.get("risk_band"),
            )
            for row in rows
        ]

    async def search_prs_annotations(
        self,
        ctx: ClinicianContext,  # noqa: ARG002 — reference-only lookup; still take ctx for symmetry
        *,
        prs_name: str | None = None,
        disease_name: str | None = None,
    ) -> list[PRSAnnotation]:
        """Look up reference rows in ``prs_annotations``. No patient scope."""
        conditions: list[str] = []
        params: list[Any] = []
        if prs_name is not None:
            conditions.append("prs_name ILIKE %s")
            params.append(prs_name)
        if disease_name is not None:
            conditions.append("disease_name ILIKE %s")
            params.append(f"%{disease_name}%")
        where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
        rows = await self._fetch_all(_SQL_SEARCH_TEMPLATE.format(where=where), params)
        return [PRSAnnotation.model_validate(row) for row in rows]

    async def get_patient_prs(
        self,
        ctx: ClinicianContext,
        patient_id: str,
        *,
        prs_name: str | None = None,
        disease_name: str | None = None,
    ) -> list[PRSResult]:
        """Return typed :class:`PRSResult`s with construction-time provenance."""
        self._authorize(ctx, patient_id)

        conditions: list[str] = ["pp.patient_id = %s"]
        params: list[Any] = [patient_id]
        if prs_name is not None:
            conditions.append("pp.prs_name = %s")
            params.append(prs_name)
        if disease_name is not None:
            conditions.append("pp.disease_name = %s")
            params.append(disease_name)
        where = " AND ".join(conditions)

        rows = await self._fetch_all(_SQL_GET_TEMPLATE.format(where=where), params)
        tool_parameters: dict[str, Any] = {"patient_id": patient_id}
        if prs_name is not None:
            tool_parameters["prs_name"] = prs_name
        if disease_name is not None:
            tool_parameters["disease_name"] = disease_name

        results: list[PRSResult] = []
        for row in rows:
            provenance = self._build_provenance(
                tool_name=_GET_TOOL_NAME,
                tool_parameters=tool_parameters,
                source_table=_GET_SOURCE_TABLE,
                source_row=row,
                fields_derived=_GET_FIELDS_DERIVED,
            )
            results.append(
                PRSResult(
                    prs_name=row["prs_name"],
                    disease_name=row["disease_name"],
                    prs_score=row["prs_score"],
                    percentile=row.get("percentile"),
                    risk_band=row.get("risk_band"),
                    source=row.get("source"),
                    metadata_notes=row.get("metadata_notes"),
                    provenance=[provenance],
                )
            )
        return results
