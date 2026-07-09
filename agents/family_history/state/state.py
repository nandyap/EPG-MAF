"""
Agent state for the genomic variants subagent.
"""
from __future__ import annotations
from typing import List, Optional
from pydantic import BaseModel, Field
from datetime import datetime

from agents.shared.state.tool_execution import ToolExecution         # ✅ shared
from agents.family_history.state.schemas import (
    FamilyHistoryResultList,
    FamilyHistoryCriteriaResultPublic,
    FamilyHistoryResultListPublic,
)


class FamilyHistoryAgentState(BaseModel):
    """
    Full internal state of the family history subagent.
    Not passed to the orchestrator — use FamilyHistoryStateOutput for that.
    """

    # ── Inputs ────────────────────────────────────────────────────
    patient_id: str = Field(..., description="Patient to retrieve family history for.")
    query_context: Optional[str] = Field(
        None,
        description="Original user query for LLM interpretation context."
    )

    # Filters — all optional, None means retrieve all
    requested_diseases: Optional[List[str]] = Field(
        None,
        description="Filter family history to these disease names only."
    )

    # ── Outputs ───────────────────────────────────────────────────
    output: Optional[FamilyHistoryResultList] = Field(
        None,
        description="Final structured output. Populated on successful completion."
    )

    # ── Execution audit ───────────────────────────────────────────
    tool_executions: List[ToolExecution] = Field(           # ✅ shared class
        default_factory=list,
        description=(
            "Ordered list of every tool call made during this agent run. "
            "Includes failed calls."
        )
    )

    # ── Lifecycle ─────────────────────────────────────────────────
    status: str = Field(
        "pending",
        description="pending | running | complete | failed | partial"
    )
    errors: List[str] = Field(default_factory=list)
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None


class FamilyHistoryStateOutput(BaseModel):
    """
    Slim output passed up to OrchestratorState.
    Uses FamilyHistoryResultListPublic — fields that are not needed
    downstream are absent entirely, not nulled.
    The full data remains in FamilyHistoryAgentState for audit purposes only.
    """
    output: Optional[FamilyHistoryResultListPublic] = Field(None)
    status: str = Field(..., description="complete | failed | partial")
    errors: List[str] = Field(default_factory=list)

    @classmethod
    def from_agent_state(
        cls,
        agent_state: FamilyHistoryAgentState,
        expected_patient_id: str,
    ) -> FamilyHistoryStateOutput:
        if agent_state.output and agent_state.output.patient_id != expected_patient_id:
            raise ValueError(
                f"Family history agent patient_id mismatch. "
                f"Expected {expected_patient_id}, "
                f"got {agent_state.output.patient_id}"
            )
        output = agent_state.output
        if output is not None:
            output = _strip_privacy_fields(output)
        return cls(
            output=output,
            status=agent_state.status,
            errors=agent_state.errors,
        )


# Alias — used by graph.py for tool execution audit trail typing
FamilyHistoryToolExecution = ToolExecution


# ── Privacy stripping ────────────────────────────────────────────────
# Fields omitted from the public output entirely.
# relationship_degree, threshold_type, threshold_value: structural details
#   captured in criteria_description and interpretation text.
# affected_relative_count, total_relatives_searched, search_context_notes:
#   aggregate search-context data used internally for qualified interpretations.

_STRIP_FROM_SOURCE_ROW: frozenset[str] = frozenset({
    "affected_relative_count",
    "total_relatives_searched",
    "search_context_notes",
})


def _strip_privacy_fields(output: FamilyHistoryResultList) -> FamilyHistoryResultListPublic:
    """
    Converts FamilyHistoryResultList → FamilyHistoryResultListPublic,
    projecting only the fields present on FamilyHistoryCriteriaResultPublic
    and stripping the same keys from provenance source_rows.
    Does not mutate the original.
    """
    public_results: list[FamilyHistoryCriteriaResultPublic] = []
    for r in output.results:
        stripped_provenance = [
            p.model_copy(update={
                "source_row": {
                    k: v for k, v in p.source_row.items()
                    if k not in _STRIP_FROM_SOURCE_ROW
                }
            })
            for p in r.provenance
        ]
        public_results.append(FamilyHistoryCriteriaResultPublic(
            disease_name=r.disease_name,
            criteria_name=r.criteria_name,
            meets_threshold=r.meets_threshold,
            criteria_description=r.criteria_description,
            criteria_source=r.criteria_source,
            interpretation=r.interpretation,
            interpretation_model=r.interpretation_model,
            provenance=stripped_provenance,
        ))
    return FamilyHistoryResultListPublic(
        patient_id=output.patient_id,
        results=public_results,
        diseases_meeting_threshold=output.diseases_meeting_threshold,
        summary=output.summary,
        summary_model=output.summary_model,
    )