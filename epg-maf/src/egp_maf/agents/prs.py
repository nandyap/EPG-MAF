"""PRS specialist — port of ``agents/prs/graph/graph.py``.

Extraction schema: :class:`PRSResultList` with LLM-filled
``interpretation`` per result and top-level ``summary``. Provenance
matches on ``prs_name`` (matching the prototype). No programmatic
derived fields at ``ResultList`` level beyond the ones the LLM fills.
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
from egp_maf.agents.state_outputs import PRSStateOutput
from egp_maf.agents.tool_shims import build_prs_tools
from egp_maf.services.provenance import ProvenanceService
from egp_maf.services.repositories import PRSRepository
from egp_maf.state.clinician_context import ClinicianContext
from egp_maf.state.results.prs import PRSResult, PRSResultList

# Only get_patient_prs is provenance-eligible (the JOIN tool). Discovery §5.7.
_TOOL_SOURCE_TABLE: dict[str, str] = {
    "get_patient_prs": "patient_prs JOIN prs_annotations",
}
_TOOL_FIELDS_DERIVED: dict[str, list[str]] = {
    "get_patient_prs": [
        "prs_name",
        "disease_name",
        "prs_score",
        "percentile",
        "risk_band",
        "source",
        "metadata_notes",
    ],
}


class PRSSpecialist(SpecialistBase[PRSResultList]):
    """Retrieves and interprets Polygenic Risk Scores."""

    name = "prs"

    def __init__(
        self,
        *,
        system_prompt: str,
        interpretation_model_name: str,
        repository: PRSRepository,
        provenance_service: ProvenanceService,
    ) -> None:
        super().__init__(
            system_prompt=system_prompt,
            interpretation_model_name=interpretation_model_name,
        )
        self._repo = repository
        self._provenance_service = provenance_service

    def _default_scope_line(self) -> str:
        return "Retrieve all available PRS scores for this patient."

    def build_tools(
        self,
        ctx: ClinicianContext,
        patient_id: str,
    ) -> list[FunctionTool]:
        return build_prs_tools(self._repo, ctx, patient_id)

    def build_extraction_instruction(self, patient_id: str) -> str:
        return (
            "Based on the tool results above, populate the PRSResultList "
            "for this patient. For each result write a 1-2 sentence clinical "
            "interpretation in the 'interpretation' field explaining what "
            "the risk band and percentile mean. Write a 'summary' covering "
            "the overall polygenic risk picture across all traits."
        )

    @property
    def response_schema(self) -> type[PRSResultList]:
        return PRSResultList

    async def build_provenance(
        self,
        *,
        result_list: PRSResultList,
        tool_calls: list[ToolCall],
        ctx: ClinicianContext,
        patient_id: str,
    ) -> PRSResultList:
        def _row_matches_result(row: dict[str, Any], result: PRSResult) -> bool:
            return row.get("prs_name") == result.prs_name

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
        result_list: PRSResultList,
        patient_id: str,
    ) -> PRSResultList:
        # No programmatic aggregates on PRSResultList — matches the prototype.
        return result_list

    def to_slot_output(
        self,
        result_list: PRSResultList | None,
        *,
        status: str,
        errors: list[str],
    ) -> BaseModel:
        return PRSStateOutput(
            output=result_list,
            status=status,  # type: ignore[arg-type]
            errors=list(errors),
        )
