from __future__ import annotations
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field
from datetime import datetime

from agents.prs.state.schemas import PRSResult, PRSResultList
from agents.shared.state.tool_execution import ToolExecution


class PRSAgentState(BaseModel):
    """
    Full internal state of the PRS subagent.

    Contains everything the agent needs to run and everything needed
    to debug it afterward. The tool_executions field is the full audit
    trail of every tool call made, whether successful or not.

    Not passed to the orchestrator — use PRSStateOutput for that.
    """

    # ── Inputs — set by orchestrator before agent runs ─────────────
    patient_id: str = Field(
        ...,
        description="Patient to retrieve PRS data for."
    )
    query_context: Optional[str] = Field(
        None,
        description="Original user query. Passed to LLM for interpretation context."
    )
    requested_diseases: Optional[List[str]] = Field(
        None,
        description=(
            "If None, retrieve all PRS scores for this patient. "
            "If set, filter to these disease names only."
        )
    )

    # ── Outputs — populated by agent ──────────────────────────────
    output: Optional[PRSResultList] = Field(
        None,
        description="Final structured output. Populated on successful completion."
    )

    # ── Execution audit — internal only ───────────────────────────
    tool_executions: List[ToolExecution] = Field(
        default_factory=list,
        description=(
            "Ordered list of every tool call made during this agent run. "
            "Includes failed calls. Used for debugging and auditing."
        )
    )

    # ── Agent lifecycle ────────────────────────────────────────────
    status: str = Field(
        "pending",
        description="pending | running | complete | failed | partial"
    )
    errors: List[str] = Field(
        default_factory=list,
        description="Accumulated error messages. Non-empty does not always mean failed "
                    "— partial results are possible."
    )
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None


class PRSStateOutput(BaseModel):
    """
    Slim output passed up to OrchestratorState.

    Strips all execution internals — the orchestrator only needs
    the results, summary, and whether the agent succeeded.
    tool_executions stays inside PRSAgentState for debugging.
    """
    output: Optional[PRSResultList] = Field(
        None,
        description="Structured PRS results. None if agent failed entirely."
    )
    status: str = Field(
        ...,
        description="complete | failed | partial"
    )
    errors: List[str] = Field(
        default_factory=list,
        description="Any errors encountered. Populated on failed or partial runs."
    )

    @classmethod
    def from_agent_state(cls, agent_state: PRSAgentState) -> PRSStateOutput:
        """
        Convenience constructor — extract the orchestrator-facing
        slice from a completed PRSAgentState.
        """
        return cls(
            output=agent_state.output,
            status=agent_state.status,
            errors=agent_state.errors
        )


# Type alias so graph.py can import PRSToolExecution — it is the shared ToolExecution.
PRSToolExecution = ToolExecution