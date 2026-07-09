"""Agent state for the PGX (pharmacogenomics) subagent."""
from __future__ import annotations
from typing import List, Optional
from pydantic import BaseModel, Field
from datetime import datetime

from agents.shared.state.tool_execution import ToolExecution
from agents.pgx.state.schemas import PGXResultList


class PGXAgentState(BaseModel):
    """
    Full internal state of the PGX subagent.
    Not passed to the orchestrator — use PGXStateOutput for that.
    """

    # ── Inputs ────────────────────────────────────────────────────
    patient_id: str = Field(..., description="Patient to retrieve PGX data for.")
    query_context: Optional[str] = Field(
        None,
        description="Original user query for LLM interpretation context."
    )
    requested_genes: Optional[List[str]] = Field(
        None,
        description="Filter PGX results to these genes only."
    )

    # ── Outputs ───────────────────────────────────────────────────
    output: Optional[PGXResultList] = Field(
        None,
        description="Final structured output. Populated on successful completion."
    )

    # ── Execution audit ───────────────────────────────────────────
    tool_executions: List[ToolExecution] = Field(
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


class PGXStateOutput(BaseModel):
    """
    Slim output passed up to OrchestratorState.
    All PGX fields are appropriate for the report agent — no privacy stripping needed.
    """
    output: Optional[PGXResultList] = Field(None)
    status: str = Field(..., description="complete | failed | partial")
    errors: List[str] = Field(default_factory=list)

    @classmethod
    def from_agent_state(
        cls,
        agent_state: PGXAgentState,
        expected_patient_id: str,
    ) -> PGXStateOutput:
        if agent_state.output and agent_state.output.patient_id != expected_patient_id:
            raise ValueError(
                f"PGX agent patient_id mismatch. "
                f"Expected {expected_patient_id}, "
                f"got {agent_state.output.patient_id}"
            )
        return cls(
            output=agent_state.output,
            status=agent_state.status,
            errors=agent_state.errors,
        )


# Alias — used by graph.py for tool execution audit trail typing
PGXToolExecution = ToolExecution
