"""Genomic variants domain repository.

Port of the LangGraph prototype tools in ``agents/genomic_variants/tools/tools.py``.

``get_patient_genomic_variants`` builds :class:`GenomicVariantResult`s with:

- ``sample_data`` from patient_variants columns
- ``core_annotations`` from variant_annotations top-level columns (with the
  ``warn_unknown_values`` soft validator firing per-record)
- ``extended_annotations`` from the deterministic
  :func:`parse_annotations_json` (Design ADR-006 — never LLM parsing)

Provenance is attached at query time. ``explore`` and ``search`` return
plain keys / annotation rows with no provenance (Discovery §5.7).
"""

from __future__ import annotations

from typing import Any

from egp_maf.services.repositories.base import BaseRepository
from egp_maf.state.clinician_context import ClinicianContext
from egp_maf.state.results.genomic_variants import (
    GenomicVariantResult,
    VariantAnnotation,
    VariantCoreAnnotations,
    VariantKey,
    VariantSampleData,
    parse_annotations_json,
)

# ── SQL ──────────────────────────────────────────────────────────────

_SQL_EXPLORE = """
    SELECT patient_id, variant_id, genotype
    FROM patient_variants
    WHERE patient_id = %s
    ORDER BY variant_id
"""

_SQL_SEARCH_TEMPLATE = """
    SELECT variant_id, gene, variant_type, pathogenicity,
           pathogenicity_source, disease_name, inheritance,
           notes, annotations_json
    FROM variant_annotations
    {where}
    ORDER BY gene, pathogenicity
"""

_SQL_GET_TEMPLATE = """
    SELECT
        pv.variant_id,
        pv.genotype,
        pv.sequencing_platform,
        pv.variant_caller,
        pv.call_quality,
        va.gene,
        va.variant_type,
        va.pathogenicity,
        va.pathogenicity_source,
        va.disease_name,
        va.inheritance,
        va.annotations_json,
        va.notes
    FROM patient_variants pv
    LEFT JOIN variant_annotations va ON pv.variant_id = va.variant_id
    {where}
"""

_GET_FIELDS_DERIVED: list[str] = [
    "variant_id",
    "genotype",
    "sequencing_platform",
    "variant_caller",
    "call_quality",
    "gene",
    "variant_type",
    "pathogenicity",
    "pathogenicity_source",
    "disease_name",
    "inheritance",
    "annotations_json",
    "notes",
]
_GET_SOURCE_TABLE = "patient_variants LEFT JOIN variant_annotations"
_GET_TOOL_NAME = "get_patient_genomic_variants"


class GenomicVariantsRepository(BaseRepository):
    """Read-only access to genomic variant data."""

    async def explore_patient_genomic_variants(
        self,
        ctx: ClinicianContext,
        patient_id: str,
    ) -> list[VariantKey]:
        self._authorize(ctx, patient_id)
        rows = await self._fetch_all(_SQL_EXPLORE, [patient_id])
        return [
            VariantKey(variant_id=row["variant_id"], genotype=row.get("genotype"))
            for row in rows
        ]

    async def search_variant_annotations(
        self,
        ctx: ClinicianContext,  # noqa: ARG002 — reference-only lookup
        *,
        variant_id: str | None = None,
        gene: str | None = None,
        pathogenicity: str | None = None,
        disease_name: str | None = None,
    ) -> list[VariantAnnotation]:
        conditions: list[str] = []
        params: list[Any] = []
        if variant_id is not None:
            conditions.append("variant_id = %s")
            params.append(variant_id)
        if gene is not None:
            conditions.append("gene ILIKE %s")
            params.append(f"%{gene}%")
        if pathogenicity is not None:
            conditions.append("pathogenicity ILIKE %s")
            params.append(f"%{pathogenicity}%")
        if disease_name is not None:
            conditions.append("disease_name ILIKE %s")
            params.append(f"%{disease_name}%")
        where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
        rows = await self._fetch_all(_SQL_SEARCH_TEMPLATE.format(where=where), params)
        return [
            VariantAnnotation(
                variant_id=row["variant_id"],
                gene=row["gene"],
                variant_type=row.get("variant_type"),
                pathogenicity=row.get("pathogenicity"),
                pathogenicity_source=row.get("pathogenicity_source"),
                disease_name=row.get("disease_name"),
                inheritance=row.get("inheritance"),
                notes=row.get("notes"),
                annotations_json=row.get("annotations_json"),
            )
            for row in rows
        ]

    async def get_patient_genomic_variants(
        self,
        ctx: ClinicianContext,
        patient_id: str,
        *,
        variant_id: str | None = None,
        disease_name: str | None = None,
        gene: str | None = None,
        variant_type: str | None = None,
        pathogenicity: str | None = None,
    ) -> list[GenomicVariantResult]:
        """Return composed :class:`GenomicVariantResult`s with typed annotations."""
        self._authorize(ctx, patient_id)

        conditions: list[str] = ["pv.patient_id = %s"]
        params: list[Any] = [patient_id]
        if variant_id is not None:
            conditions.append("pv.variant_id = %s")
            params.append(variant_id)
        # Disease names, gene symbols, variant types and pathogenicity
        # classes are supplied by the LLM, which re-types them rather than
        # passing through the exact string the database returned. ``=`` is
        # therefore the wrong operator: ``pathogenicity = 'pathogenic'``
        # matches nothing, because the CHECK constraint stores
        # ``'Pathogenic'``. The query succeeds and returns zero rows, so
        # the specialist reports the patient has no such variants — a
        # false negative that looks exactly like a true one.
        #
        # ``ILIKE`` without wildcards is still an exact comparison, just
        # case-insensitive. ``search_variant_annotations`` already uses it
        # for the same field; this makes the two agree.
        #
        # ``variant_id`` above is deliberately left case-sensitive: it is
        # an opaque identifier copied verbatim, and a case difference
        # there would signal a genuinely different record.
        if disease_name is not None:
            conditions.append("va.disease_name ILIKE %s")
            params.append(disease_name)
        if gene is not None:
            conditions.append("va.gene ILIKE %s")
            params.append(gene)
        if variant_type is not None:
            conditions.append("va.variant_type ILIKE %s")
            params.append(variant_type)
        if pathogenicity is not None:
            conditions.append("va.pathogenicity ILIKE %s")
            params.append(pathogenicity)
        where = "WHERE " + " AND ".join(conditions)

        rows = await self._fetch_all(_SQL_GET_TEMPLATE.format(where=where), params)

        tool_parameters: dict[str, Any] = {"patient_id": patient_id}
        for name, value in (
            ("variant_id", variant_id),
            ("disease_name", disease_name),
            ("gene", gene),
            ("variant_type", variant_type),
            ("pathogenicity", pathogenicity),
        ):
            if value is not None:
                tool_parameters[name] = value

        results: list[GenomicVariantResult] = []
        for row in rows:
            provenance = self._build_provenance(
                tool_name=_GET_TOOL_NAME,
                tool_parameters=tool_parameters,
                source_table=_GET_SOURCE_TABLE,
                source_row=row,
                fields_derived=_GET_FIELDS_DERIVED,
            )
            sample = VariantSampleData(
                genotype=row.get("genotype"),
                sequencing_platform=row.get("sequencing_platform"),
                variant_caller=row.get("variant_caller"),
                call_quality=row.get("call_quality"),
            )
            core = VariantCoreAnnotations(
                gene=row.get("gene"),
                variant_type=row.get("variant_type"),
                pathogenicity=row.get("pathogenicity"),
                disease_name=row.get("disease_name"),
                notes=row.get("notes"),
            )
            extended = parse_annotations_json(row.get("annotations_json"))
            results.append(
                GenomicVariantResult(
                    variant_id=row["variant_id"],
                    sample_data=sample,
                    core_annotations=core,
                    extended_annotations=extended,
                    provenance=[provenance],
                )
            )
        return results
