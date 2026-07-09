"""PGX specialist — port of ``agents/pgx/graph/graph.py``.

Programmatic derived fields on :class:`PGXResultList` (parity with the
prototype's ``agents/pgx/graph/graph.py:109-125``):

- ``genes_assessed`` — sorted unique ``gene`` across all results.
- ``drugs_with_recommendations`` — sorted unique ``drug`` where a
  ``recommendation`` was populated (LEFT-JOIN-null-safe).
- ``patient_id`` — set from the run's ``patient_id``, not the LLM.

Provenance matches on the composite ``(gene, drug)`` key so a patient
with multiple drug rows for the same gene gets a provenance record per
row.
"""

from __future__ import annotations

from typing import Any

from agent_framework import FunctionTool
from pydantic import BaseModel

from egp_maf.agents.base import (
    SpecialistBase,
    ToolCall,
    attach_provenance_to_results,
)
from egp_maf.agents.state_outputs import PGXStateOutput
from egp_maf.agents.tool_shims import build_pgx_tools
from egp_maf.services.provenance import ProvenanceService
from egp_maf.services.repositories import PGXRepository
from egp_maf.state.clinician_context import ClinicianContext
from egp_maf.state.results.pgx import PGXDrugResult, PGXResultList

_TOOL_SOURCE_TABLE: dict[str, str] = {
    "get_patient_pgx": "patient_pgx_status LEFT JOIN pgx_annotations",
}
_TOOL_FIELDS_DERIVED: dict[str, list[str]] = {
    "get_patient_pgx": [
        "gene",
        "diplotype",
        "phenotype",
        "drug",
        "recommendation",
        "summary",
        "source",
    ],
}


class PGXSpecialist(SpecialistBase[PGXResultList]):
    """Retrieves and interprets pharmacogenomics recommendations."""

    name = "pgx"

    def __init__(
        self,
        *,
        system_prompt: str,
        interpretation_model_name: str,
        repository: PGXRepository,
        provenance_service: ProvenanceService,
    ) -> None:
        super().__init__(
            system_prompt=system_prompt,
            interpretation_model_name=interpretation_model_name,
        )
        self._repo = repository
        self._provenance_service = provenance_service

    def _default_scope_line(self) -> str:
        return (
            "Retrieve all available pharmacogenomic gene-drug pairs "
            "for this patient."
        )

    def build_tools(
        self,
        ctx: ClinicianContext,
        patient_id: str,
    ) -> list[FunctionTool]:
        return build_pgx_tools(self._repo, ctx, patient_id)

    def build_extraction_instruction(self, patient_id: str) -> str:
        return (
            f"Based on the tool results above, populate the PGXResultList "
            f"for patient '{patient_id}'. For each gene-drug result write "
            f"a 1-2 sentence clinical interpretation of what the patient's "
            f"phenotype means for this drug and what the recommendation "
            f"implies. Write a 'summary' covering the overall PGX picture "
            f"across all drugs assessed."
        )

    @property
    def response_schema(self) -> type[PGXResultList]:
        return PGXResultList

    async def build_provenance(
        self,
        *,
        result_list: PGXResultList,
        tool_calls: list[ToolCall],
        ctx: ClinicianContext,
        patient_id: str,
    ) -> PGXResultList:
        def _row_matches_result(row: dict[str, Any], result: PGXDrugResult) -> bool:
            return (
                row.get("gene") == result.gene
                and row.get("drug") == result.drug
            )

        attach_provenance_to_results(
            results=result_list.results,
            tool_calls=tool_calls,
            tool_source_table=_TOOL_SOURCE_TABLE,
            tool_fields_derived=_TOOL_FIELDS_DERIVED,
            row_matches_result=_row_matches_result,
            provenance_builder=self._provenance_service.build,
        )
        return result_list

    def apply_derived_fields(
        self,
        result_list: PGXResultList,
        patient_id: str,
    ) -> PGXResultList:
        """Prototype parity: derive ``patient_id``, ``genes_assessed``,
        ``drugs_with_recommendations`` programmatically — LLM never fills
        these."""
        result_list.patient_id = patient_id
        result_list.genes_assessed = sorted({r.gene for r in result_list.results if r.gene})
        result_list.drugs_with_recommendations = sorted(
            {
                r.drug
                for r in result_list.results
                if r.drug and r.recommendation is not None
            }
        )
        return result_list

    def to_slot_output(
        self,
        result_list: PGXResultList | None,
        *,
        status: str,
        errors: list[str],
    ) -> BaseModel:
        return PGXStateOutput(
            output=result_list,
            status=status,  # type: ignore[arg-type]
            errors=list(errors),
        )
