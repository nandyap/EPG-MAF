"""State schema for the chat agent."""

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


class ChatAgentState(TypedDict, total=False):
    # --- Session context (injected at graph invocation) ---
    patient_id: str
    clinician_id: str
    conversation_id: str
    clinician_specialty: Optional[str]

    # --- Current turn (overwritten each turn from latest HumanMessage) ---
    original_query: str

    # --- Conversation history (accumulated via add_messages across turns) ---
    messages: Annotated[list[AnyMessage], add_messages]

    # --- Chat routing decision (set by chat_router each turn) ---
    next_action: Literal["run_main_agent", "respond_directly"]

    # --- Orchestration filters (passed through to main agent) ---
    requested_diseases: Optional[list[str]]
    requested_genes: Optional[list[str]]

    # --- Subagent outputs (accumulated across turns; selectively reset by chat_router) ---
    prs: PRSStateOutput | None
    genomic_variants: GenomicVariantsStateOutput | None
    family_history: FamilyHistoryStateOutput | None
    pgx: PGXStateOutput | None
    phenotype: PhenotypeStateOutput | None

    # --- Completion tracking (accumulated across turns; selectively reset by chat_router) ---
    agents_completed: list[str]
