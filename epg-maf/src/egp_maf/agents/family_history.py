"""Family-history specialist — port of ``agents/family_history/graph/graph.py``.

Two things unique to this specialist:

1. **Privacy strip at StateOutput construction.** :meth:`to_slot_output`
   calls :meth:`FamilyHistoryResultList.to_public` before wrapping. The
   :class:`FamilyHistoryStateOutput` payload type is
   :class:`FamilyHistoryResultListPublic` — the three privacy fields are
   *absent from the type entirely* (not merely null). This is the
   contract Design §11.7 / ADR-017 enforces.

2. **Programmatic derived field** ``diseases_meeting_threshold`` — set of
   ``disease_name``s where ``meets_threshold`` is True.

Provenance matches on the composite ``(disease_name, criteria_name)``
key.
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
from egp_maf.agents.state_outputs import FamilyHistoryStateOutput
from egp_maf.agents.tool_shims import build_family_history_tools
from egp_maf.services.provenance import ProvenanceService
from egp_maf.services.repositories import FamilyHistoryRepository
from egp_maf.state.clinician_context import ClinicianContext
from egp_maf.state.results.family_history import (
    FamilyHistoryCriteriaResult,
    FamilyHistoryResultList,
)

_TOOL_SOURCE_TABLE: dict[str, str] = {
    "get_patient_family_history": (
        "patient_kinship_history LEFT JOIN kinship_history_annotations"
    ),
}
_TOOL_FIELDS_DERIVED: dict[str, list[str]] = {
    "get_patient_family_history": [
        "disease_name",
        "criteria_name",
        "meets_threshold",
        "last_observed_diagnosis_in_database",
        "criteria_description",
        "criteria_source",
    ],
}


class FamilyHistorySpecialist(SpecialistBase[FamilyHistoryResultList]):
    """Retrieves + interprets family history criteria records.

    Public-projection strip is applied at StateOutput construction.
    """

    name = "family_history"

    def __init__(
        self,
        *,
        system_prompt: str,
        interpretation_model_name: str,
        repository: FamilyHistoryRepository,
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
            "Retrieve all available family history records for this patient."
        )

    def build_tools(
        self,
        ctx: ClinicianContext,
        patient_id: str,
    ) -> list[FunctionTool]:
        return build_family_history_tools(self._repo, ctx, patient_id)

    def build_extraction_instruction(self, patient_id: str) -> str:
        return (
            f"Based on the tool results above, populate the "
            f"FamilyHistoryResultList for patient '{patient_id}'. For each "
            f"family history record populate all threshold fields "
            f"(disease_name, criteria_name, affected_relative_count, "
            f"total_relatives_searched, meets_threshold, "
            f"search_context_notes, last_observed_diagnosis_in_database) "
            f"from the patient data columns; populate criteria_description "
            f"and criteria_source from the annotation JOIN columns; write "
            f"a 1-2 sentence clinical interpretation — if "
            f"search_context_notes indicates an incomplete search, "
            f"explicitly qualify the result (e.g. 'Threshold not met; "
            f"however, 0 eligible females over 30 were included — result "
            f"may underestimate risk'). Write a 'summary' field covering "
            f"the overall family history picture."
        )

    @property
    def response_schema(self) -> type[FamilyHistoryResultList]:
        return FamilyHistoryResultList

    async def build_provenance(
        self,
        *,
        result_list: FamilyHistoryResultList,
        tool_calls: list[ToolCall],
        ctx: ClinicianContext,
        patient_id: str,
    ) -> FamilyHistoryResultList:
        def _row_matches_result(
            row: dict[str, Any], result: FamilyHistoryCriteriaResult
        ) -> bool:
            return (
                row.get("disease_name") == result.disease_name
                and row.get("criteria_name") == result.criteria_name
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
        result_list: FamilyHistoryResultList,
        patient_id: str,
    ) -> FamilyHistoryResultList:
        result_list.patient_id = patient_id
        result_list.diseases_meeting_threshold = sorted(
            {
                r.disease_name
                for r in result_list.results
                if r.meets_threshold and r.disease_name
            }
        )
        return result_list

    def to_slot_output(
        self,
        result_list: FamilyHistoryResultList | None,
        *,
        status: str,
        errors: list[str],
    ) -> BaseModel:
        """Apply the privacy strip.

        Payload type is :class:`FamilyHistoryResultListPublic` — the three
        private fields are absent from the type, and stripped from every
        :attr:`DBProvenance.source_row`. See
        :meth:`FamilyHistoryResultList.to_public` (W03).
        """
        public_payload = result_list.to_public() if result_list is not None else None
        return FamilyHistoryStateOutput(
            output=public_payload,
            status=status,  # type: ignore[arg-type]
            errors=list(errors),
        )
