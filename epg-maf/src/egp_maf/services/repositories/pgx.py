"""PGX domain repository.

Port of the LangGraph prototype tools in ``agents/pgx/tools/tools.py``.
"""

from __future__ import annotations

from typing import Any

from egp_maf.services.repositories.base import BaseRepository
from egp_maf.state.clinician_context import ClinicianContext
from egp_maf.state.results.pgx import PGXAnnotation, PGXDrugResult, PGXKey

# ── SQL ──────────────────────────────────────────────────────────────

_SQL_EXPLORE = """
    SELECT patient_id, gene, diplotype, phenotype
    FROM patient_pgx_status
    WHERE patient_id = %s
    ORDER BY gene
"""

_SQL_SEARCH_TEMPLATE = """
    SELECT gene, phenotype, drug, recommendation, summary, source
    FROM pgx_annotations
    {where}
    ORDER BY gene, drug
"""

_SQL_GET_TEMPLATE = """
    SELECT pps.patient_id, pps.gene, pps.diplotype, pps.phenotype,
           pa.drug, pa.recommendation, pa.summary, pa.source
    FROM patient_pgx_status pps
    LEFT JOIN pgx_annotations pa
        ON pps.gene = pa.gene
       AND pps.phenotype = pa.phenotype
    {where}
    ORDER BY pps.gene, pa.drug
"""

_GET_FIELDS_DERIVED: list[str] = [
    "gene",
    "diplotype",
    "phenotype",
    "drug",
    "recommendation",
    "summary",
    "source",
]
_GET_SOURCE_TABLE = "patient_pgx_status LEFT JOIN pgx_annotations"
_GET_TOOL_NAME = "get_patient_pgx"


class PGXRepository(BaseRepository):
    """Read-only access to pharmacogenomics data."""

    async def explore_patient_pgx(
        self,
        ctx: ClinicianContext,
        patient_id: str,
    ) -> list[PGXKey]:
        self._authorize(ctx, patient_id)
        rows = await self._fetch_all(_SQL_EXPLORE, [patient_id])
        return [
            PGXKey(
                gene=row["gene"],
                diplotype=row.get("diplotype"),
                phenotype=row.get("phenotype"),
            )
            for row in rows
        ]

    async def search_pgx_annotations(
        self,
        ctx: ClinicianContext,  # noqa: ARG002 — reference-only lookup
        *,
        gene: str | None = None,
        phenotype: str | None = None,
        drug: str | None = None,
    ) -> list[PGXAnnotation]:
        conditions: list[str] = []
        params: list[Any] = []
        if gene is not None:
            conditions.append("gene = %s")
            params.append(gene)
        if phenotype is not None:
            conditions.append("phenotype = %s")
            params.append(phenotype)
        if drug is not None:
            conditions.append("drug ILIKE %s")
            params.append(f"%{drug}%")
        where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
        rows = await self._fetch_all(_SQL_SEARCH_TEMPLATE.format(where=where), params)
        return [PGXAnnotation.model_validate(row) for row in rows]

    async def get_patient_pgx(
        self,
        ctx: ClinicianContext,
        patient_id: str,
        *,
        gene: str | None = None,
    ) -> list[PGXDrugResult]:
        self._authorize(ctx, patient_id)

        conditions: list[str] = ["pps.patient_id = %s"]
        params: list[Any] = [patient_id]
        if gene is not None:
            conditions.append("pps.gene = %s")
            params.append(gene)
        where = "WHERE " + " AND ".join(conditions)

        rows = await self._fetch_all(_SQL_GET_TEMPLATE.format(where=where), params)
        tool_parameters: dict[str, Any] = {"patient_id": patient_id}
        if gene is not None:
            tool_parameters["gene"] = gene

        results: list[PGXDrugResult] = []
        for row in rows:
            provenance = self._build_provenance(
                tool_name=_GET_TOOL_NAME,
                tool_parameters=tool_parameters,
                source_table=_GET_SOURCE_TABLE,
                source_row=row,
                fields_derived=_GET_FIELDS_DERIVED,
            )
            results.append(
                PGXDrugResult(
                    gene=row["gene"],
                    drug=row.get("drug"),
                    diplotype=row.get("diplotype"),
                    phenotype=row.get("phenotype"),
                    recommendation=row.get("recommendation"),
                    summary=row.get("summary"),
                    source=row.get("source"),
                    provenance=[provenance],
                )
            )
        return results
