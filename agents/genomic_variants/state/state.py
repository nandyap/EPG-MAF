"""
Agent state for the genomic variants subagent.
"""
from __future__ import annotations
from typing import List, Optional
from pydantic import BaseModel, Field
from datetime import datetime

from agents.shared.state.tool_execution import ToolExecution         # ✅ shared
from agents.genomic_variants.state.schemas import GenomicVariantsResultList


class GenomicVariantsAgentState(BaseModel):
    """
    Full internal state of the genomic variants subagent.
    Not passed to the orchestrator — use GenomicVariantsStateOutput for that.
    """

    # ── Inputs ────────────────────────────────────────────────────
    patient_id: str = Field(..., description="Patient to retrieve variants for.")
    query_context: Optional[str] = Field(
        None,
        description="Original user query for LLM interpretation context."
    )

    # Filters — all optional, None means retrieve all
    requested_diseases: Optional[List[str]] = Field(
        None,
        description="Filter variants to these disease names only."
    )
    requested_genes: Optional[List[str]] = Field(
        None,
        description="Filter variants to these genes only."
    )
    requested_variant_types: Optional[List[str]] = Field(   # ✅ typo fixed
        None,
        description="Filter to these variant types only. e.g. ['missense', 'cnv']"
    )
    requested_pathogenicity: Optional[List[str]] = Field(
        None,
        description=(
            "Filter to these pathogenicity classes only. "
            "e.g. ['Pathogenic', 'Likely Pathogenic']"
        )
    )

    # ── Outputs ───────────────────────────────────────────────────
    output: Optional[GenomicVariantsResultList] = Field(
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


class GenomicVariantsStateOutput(BaseModel):
    """
    Slim output passed up to OrchestratorState.
    Strips execution internals.
    """
    output: Optional[GenomicVariantsResultList] = Field(None)
    status: str = Field(..., description="complete | failed | partial")
    errors: List[str] = Field(default_factory=list)

    @classmethod
    def from_agent_state(
        cls,
        agent_state: GenomicVariantsAgentState,
        expected_patient_id: str,
    ) -> GenomicVariantsStateOutput:
        if agent_state.output and agent_state.output.patient_id != expected_patient_id:
            raise ValueError(
                f"Genomic variants agent patient_id mismatch. "
                f"Expected {expected_patient_id}, "
                f"got {agent_state.output.patient_id}"
            )
        return cls(
            output=agent_state.output,
            status=agent_state.status,
            errors=agent_state.errors,
        )


# Alias — used by graph.py for tool execution audit trail typing
GenomicVariantsToolExecution = ToolExecution