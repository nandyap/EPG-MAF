"""State schema for the main orchestration agent."""

from __future__ import annotations

from typing import Annotated, Literal, Optional

from langchain_core.messages import AnyMessage
from langgraph.graph.message import add_messages
from typing_extensions import TypedDict

from agents.prs.state.state import PRSStateOutput
from agents.genomic_variants.state.state import GenomicVariantsStateOutput
from agents.family_history.state.state import FamilyHistoryStateOutput
from agents.pgx.state.state import PGXStateOutput
from agents.phenotype.state.state import PhenotypeStateOutput


class OrchestrationAgentState(TypedDict, total=False):
    # --- Input fields (set at invocation) ---
    patient_id: str
    clinician_id: str
    conversation_id: str
    original_query: str
    clinician_specialty: Optional[str]
    
    # --- Optional filters (passed through to subagents) ---
    requested_diseases: Optional[list[str]]
    requested_genes: Optional[list[str]]

    # --- Conversation channel (for router LLM) ---
    messages: Annotated[list[AnyMessage], add_messages]

    # --- Router decision (set by router node each step) ---
    next: Literal["prs_agent", "genomic_variants_agent", "family_history_agent", "pgx_agent", "phenotype_agent", "end"] | None

    # --- Subagent outputs ---
    prs: PRSStateOutput | None
    genomic_variants: GenomicVariantsStateOutput | None
    family_history: FamilyHistoryStateOutput | None
    pgx: PGXStateOutput | None
    phenotype: PhenotypeStateOutput | None

    # --- Completion tracking (subagent nodes append their name here) ---
    agents_completed: list[str]
