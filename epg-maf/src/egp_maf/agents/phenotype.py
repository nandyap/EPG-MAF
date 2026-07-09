"""Phenotype specialist — port of ``agents/phenotype/graph/graph.py``.

Two-tool contract (no annotation table exists for diagnoses).
Programmatic derived field: ``relevant_disease_names`` from the
LLM-filled ``relevant_to_query`` flag on each result (parity with
prototype ``agents/phenotype/graph/graph.py:113-116``).

Provenance matches on the disease-name column of the grouped SQL
(``COALESCE(disease_name, term)`` — the tool_shim returns rows already
under the alias ``disease_name``).
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
from egp_maf.agents.state_outputs import PhenotypeStateOutput
from egp_maf.agents.tool_shims import build_phenotype_tools
from egp_maf.services.provenance import ProvenanceService
from egp_maf.services.repositories import PhenotypeRepository
from egp_maf.state.clinician_context import ClinicianContext
from egp_maf.state.results.phenotype import (
    PhenotypeDiseaseResult,
    PhenotypeResultList,
)

_TOOL_SOURCE_TABLE: dict[str, str] = {
    "get_patient_diagnoses": "diagnoses",
}
_TOOL_FIELDS_DERIVED: dict[str, list[str]] = {
    "get_patient_diagnoses": [
        "disease_name",
        "encounter_count",
        "first_encounter_date",
        "last_encounter_date",
        "codes",
        "terms",
        "code_types",
    ],
}


class PhenotypeSpecialist(SpecialistBase[PhenotypeResultList]):
    """Retrieves and interprets phenotype (diagnosis) history."""

    name = "phenotype"

    def __init__(
        self,
        *,
        system_prompt: str,
        interpretation_model_name: str,
        repository: PhenotypeRepository,
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
            "Retrieve all available diagnoses for this patient, grouped "
            "by disease."
        )

    def build_tools(
        self,
        ctx: ClinicianContext,
        patient_id: str,
    ) -> list[FunctionTool]:
        return build_phenotype_tools(self._repo, ctx, patient_id)

    def build_extraction_instruction(self, patient_id: str) -> str:
        return (
            f"Based on the tool results above, populate the PhenotypeResultList "
            f"for patient '{patient_id}'. For each disease group: set "
            f"'relevant_to_query' true only when the disease is directly "
            f"relevant to the user query; write a 1-2 sentence clinical "
            f"interpretation only when 'relevant_to_query' is true. Write "
            f"a 'summary' covering the overall diagnosis picture."
        )

    @property
    def response_schema(self) -> type[PhenotypeResultList]:
        return PhenotypeResultList

    async def build_provenance(
        self,
        *,
        result_list: PhenotypeResultList,
        tool_calls: list[ToolCall],
        ctx: ClinicianContext,
        patient_id: str,
    ) -> PhenotypeResultList:
        def _row_matches_result(
            row: dict[str, Any], result: PhenotypeDiseaseResult
        ) -> bool:
            return row.get("disease_name") == result.disease_name

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
        result_list: PhenotypeResultList,
        patient_id: str,
    ) -> PhenotypeResultList:
        """Prototype parity: derive ``patient_id`` + ``relevant_disease_names``
        programmatically."""
        result_list.patient_id = patient_id
        result_list.relevant_disease_names = [
            r.disease_name for r in result_list.results if r.relevant_to_query
        ]
        return result_list

    def to_slot_output(
        self,
        result_list: PhenotypeResultList | None,
        *,
        status: str,
        errors: list[str],
    ) -> BaseModel:
        return PhenotypeStateOutput(
            output=result_list,
            status=status,  # type: ignore[arg-type]
            errors=list(errors),
        )
