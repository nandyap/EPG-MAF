"""Genomic-variants specialist — port of ``agents/genomic_variants/graph/graph.py``.

Two design deviations from other specialists:

- **``annotations_json`` is decomposed in Python, not by the LLM** — the
  tool shim already returns typed sub-models (Design ADR-006 / W03's
  :func:`parse_annotations_json`). The LLM never parses JSON.
- ``pathogenic_count`` is derived programmatically (parity with
  ``agents/genomic_variants/graph/graph.py:146-152``) using the same
  ``{"Pathogenic", "Likely Pathogenic"}`` set as the prototype.

Provenance matches on ``variant_id``.
"""

from __future__ import annotations

from typing import Any

from agent_framework import FunctionTool
from pydantic import BaseModel

from egp_maf.agents.base import (
    SpecialistBase,
    ToolCall,
    attach_provenance_to_results,
    backfill_provenance_from_repository,
    normalise_key_part,
)
from egp_maf.agents.state_outputs import GenomicVariantsStateOutput
from egp_maf.agents.tool_shims import build_genomic_variants_tools
from egp_maf.services.provenance import ProvenanceService
from egp_maf.services.repositories import GenomicVariantsRepository
from egp_maf.state.clinician_context import ClinicianContext
from egp_maf.state.results.genomic_variants import (
    GenomicVariantResult,
    GenomicVariantsResultList,
)

_PATHOGENIC = frozenset({"Pathogenic", "Likely Pathogenic"})

_TOOL_SOURCE_TABLE: dict[str, str] = {
    "get_patient_genomic_variants": "patient_variants LEFT JOIN variant_annotations",
}
_TOOL_FIELDS_DERIVED: dict[str, list[str]] = {
    "get_patient_genomic_variants": [
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
    ],
}


class GenomicVariantsSpecialist(SpecialistBase[GenomicVariantsResultList]):
    """Retrieves and interprets genomic variants."""

    name = "genomic_variants"

    def __init__(
        self,
        *,
        system_prompt: str,
        interpretation_model_name: str,
        repository: GenomicVariantsRepository,
        provenance_service: ProvenanceService,
    ) -> None:
        super().__init__(
            system_prompt=system_prompt,
            interpretation_model_name=interpretation_model_name,
        )
        self._repo = repository
        self._provenance_service = provenance_service

    def _default_scope_line(self) -> str:
        return "Retrieve all available variants for this patient."

    def build_tools(
        self,
        ctx: ClinicianContext,
        patient_id: str,
    ) -> list[FunctionTool]:
        return build_genomic_variants_tools(self._repo, ctx, patient_id)

    def build_extraction_instruction(self, patient_id: str) -> str:
        return (
            f"Based on the tool results above, populate a "
            f"GenomicVariantsResultList for patient '{patient_id}'. Each "
            f"tool result row already contains typed sample_data, "
            f"core_annotations and extended_annotations sub-models — copy "
            f"them into each variant result unchanged. Write a 1-2 sentence "
            f"clinical interpretation in the 'interpretation' field "
            f"explaining the variant's pathogenicity and clinical "
            f"significance. Write a 'summary' field covering the overall "
            f"variant picture for this patient."
        )

    @property
    def response_schema(self) -> type[GenomicVariantsResultList]:
        return GenomicVariantsResultList

    async def build_provenance(
        self,
        *,
        result_list: GenomicVariantsResultList,
        tool_calls: list[ToolCall],
        ctx: ClinicianContext,
        patient_id: str,
    ) -> GenomicVariantsResultList:
        def _row_matches_result(
            row: dict[str, Any], result: GenomicVariantResult
        ) -> bool:
            return row.get("variant_id") == result.variant_id

        attach_provenance_to_results(
            results=result_list.results,
            tool_calls=tool_calls,
            tool_source_table=_TOOL_SOURCE_TABLE,
            tool_fields_derived=_TOOL_FIELDS_DERIVED,
            row_matches_result=_row_matches_result,
            provenance_builder=self._provenance_service.build,
        )

        # The agent can answer from explore + search alone (both return
        # the variant id and its annotations), so get_patient_genomic_
        # variants — the only provenance-bearing tool — is frequently
        # never called. Observed live 2026-08-25.
        await backfill_provenance_from_repository(
            domain="genomic_variants",
            patient_id=patient_id,
            results=result_list.results,
            fetch_rows=lambda: self._repo.get_patient_genomic_variants(
                ctx, patient_id
            ),
            key_of=lambda r: (normalise_key_part(r.variant_id),),
        )
        return result_list

    def apply_derived_fields(
        self,
        result_list: GenomicVariantsResultList,
        patient_id: str,
    ) -> GenomicVariantsResultList:
        """Prototype parity: derive ``patient_id`` + ``pathogenic_count``
        programmatically."""
        result_list.patient_id = patient_id
        result_list.pathogenic_count = sum(
            1
            for r in result_list.results
            if r.core_annotations is not None
            and r.core_annotations.pathogenicity in _PATHOGENIC
        )
        return result_list

    def to_slot_output(
        self,
        result_list: GenomicVariantsResultList | None,
        *,
        status: str,
        errors: list[str],
    ) -> BaseModel:
        return GenomicVariantsStateOutput(
            output=result_list,
            status=status,  # type: ignore[arg-type]
            errors=list(errors),
        )
