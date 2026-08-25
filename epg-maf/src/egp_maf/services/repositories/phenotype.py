"""Phenotype domain repository.

Port of the LangGraph prototype tools in ``agents/phenotype/tools/tools.py``.
Two methods (no reference-annotation table for diagnoses).

DuckDB → Postgres SQL adjustments:

- ``LIST(DISTINCT x)`` → ``array_agg(DISTINCT x)``.
- ``CAST(x AS VARCHAR)`` → ``to_char(x, 'YYYY-MM-DD')`` for dates (produces
  the same ISO string the prototype emitted).
"""

from __future__ import annotations

from typing import Any

from egp_maf.services.repositories.base import BaseRepository
from egp_maf.state.clinician_context import ClinicianContext
from egp_maf.state.results.phenotype import PhenotypeDiseaseResult, PhenotypeKey

# ── SQL ──────────────────────────────────────────────────────────────

_SQL_EXPLORE = """
    SELECT DISTINCT disease_name, term, code_type
    FROM diagnoses
    WHERE patient_id = %s
    ORDER BY disease_name NULLS LAST, term
"""

_SQL_GET_TEMPLATE = """
    SELECT
        COALESCE(disease_name, term)                              AS disease_name,
        COUNT(*)                                                   AS encounter_count,
        to_char(MIN(encounter_date), 'YYYY-MM-DD')                 AS first_encounter_date,
        to_char(MAX(encounter_date), 'YYYY-MM-DD')                 AS last_encounter_date,
        array_agg(DISTINCT code)                                   AS codes,
        array_agg(DISTINCT term)                                   AS terms,
        array_agg(DISTINCT code_type)                              AS code_types
    FROM diagnoses
    WHERE {where}
    GROUP BY COALESCE(disease_name, term)
    ORDER BY COALESCE(disease_name, term) NULLS LAST
"""

_GET_FIELDS_DERIVED: list[str] = [
    "disease_name",
    "encounter_count",
    "first_encounter_date",
    "last_encounter_date",
    "codes",
    "terms",
    "code_types",
]
_GET_SOURCE_TABLE = "diagnoses"
_GET_TOOL_NAME = "get_patient_diagnoses"


class PhenotypeRepository(BaseRepository):
    """Read-only access to diagnoses/phenotype data."""

    async def explore_patient_phenotype(
        self,
        ctx: ClinicianContext,
        patient_id: str,
    ) -> list[PhenotypeKey]:
        self._authorize(ctx, patient_id)
        rows = await self._fetch_all(_SQL_EXPLORE, [patient_id])
        return [
            PhenotypeKey(
                disease_name=row.get("disease_name"),
                term=row["term"],
                code_type=row["code_type"],
            )
            for row in rows
        ]

    async def get_patient_diagnoses(
        self,
        ctx: ClinicianContext,
        patient_id: str,
        *,
        disease_name: str | None = None,
        search_term: str | None = None,
    ) -> list[PhenotypeDiseaseResult]:
        """Grouped diagnosis retrieval — mirrors the prototype filter semantics.

        When both ``disease_name`` and ``search_term`` are given the prototype
        OR-combines: match either exact ``disease_name`` OR fuzzy any of the
        three text columns. Preserved here.
        """
        self._authorize(ctx, patient_id)

        conditions: list[str] = ["patient_id = %s"]
        params: list[Any] = [patient_id]

        if disease_name is not None and search_term is not None:
            conditions.append(
                "(disease_name ILIKE %s OR term ILIKE %s OR description ILIKE %s)"
            )
            params += [disease_name, f"%{search_term}%", f"%{search_term}%"]
        elif disease_name is not None:
            conditions.append("disease_name ILIKE %s")
            params.append(disease_name)
        elif search_term is not None:
            conditions.append(
                "(disease_name ILIKE %s OR term ILIKE %s OR description ILIKE %s)"
            )
            params += [
                f"%{search_term}%",
                f"%{search_term}%",
                f"%{search_term}%",
            ]

        where = " AND ".join(conditions)
        rows = await self._fetch_all(_SQL_GET_TEMPLATE.format(where=where), params)

        tool_parameters: dict[str, Any] = {"patient_id": patient_id}
        if disease_name is not None:
            tool_parameters["disease_name"] = disease_name
        if search_term is not None:
            tool_parameters["search_term"] = search_term

        results: list[PhenotypeDiseaseResult] = []
        for row in rows:
            provenance = self._build_provenance(
                tool_name=_GET_TOOL_NAME,
                tool_parameters=tool_parameters,
                source_table=_GET_SOURCE_TABLE,
                source_row=row,
                fields_derived=_GET_FIELDS_DERIVED,
            )
            results.append(
                PhenotypeDiseaseResult(
                    disease_name=row["disease_name"],
                    encounter_count=int(row["encounter_count"]),
                    first_encounter_date=row.get("first_encounter_date"),
                    last_encounter_date=row.get("last_encounter_date"),
                    codes=list(row.get("codes") or []),
                    terms=list(row.get("terms") or []),
                    code_types=list(row.get("code_types") or []),
                    provenance=[provenance],
                )
            )
        return results
