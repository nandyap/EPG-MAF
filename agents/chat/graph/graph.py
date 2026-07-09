"""
Chat agent: routes clinician messages to the main orchestration agent when
clinical data retrieval is needed, then synthesises a focused response.

Flow (per turn):
    START → chat_router ──(run_main_agent)──→ run_main_agent → synthesize_response → END
                        ╰──(respond_directly)────────────────→ synthesize_response → END

Multi-turn:
    The graph is invoked once per user message. The checkpointer (configured in
    langgraph dev) persists ChatAgentState across turns via thread_id. Each turn:
      - chat_router extracts the latest HumanMessage as original_query.
      - Accumulated subagent outputs and agents_completed carry forward, so the main
        agent skips domains already retrieved unless chat_router resets them.
      - synthesize_response appends an AIMessage, which is persisted for next turn.
"""
from __future__ import annotations

import json
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel, Field

from agents.chat.models.model import chat_llm
from agents.chat.prompts.prompt import CHAT_ROUTER_SYSTEM, CHAT_SYNTHESIS_SYSTEM
from agents.chat.state.state import ChatAgentState
from agents.main.graph.graph import graph as main_graph


# ── Router decision model ────────────────────────────────────────────

class ChatRouterDecision(BaseModel):
    """Structured routing decision emitted by the chat router LLM."""

    needs_clinical_data: bool = Field(
        description=(
            "True if the latest message requires new clinical data from the database. "
            "False if the question can be answered from existing conversation context."
        )
    )
    reason: str = Field(description="One-sentence justification for this routing decision.")
    reset_agents: list[str] = Field(
        default_factory=list,
        description=(
            "Agent short names whose cached results are no longer valid for the new query "
            "(e.g. disease filter changed). Only list agents already in agents_already_completed. "
            "Valid values: prs, genomic_variants, family_history, pgx, phenotype."
        ),
    )


_router_llm = chat_llm.with_structured_output(ChatRouterDecision)

# Maps agent short name → ChatAgentState output field key
_AGENT_TO_OUTPUT_KEY: dict[str, str] = {
    "prs": "prs",
    "genomic_variants": "genomic_variants",
    "family_history": "family_history",
    "pgx": "pgx",
    "phenotype": "phenotype",
}


# ── Helpers ──────────────────────────────────────────────────────────

def _router_context_summary(state: ChatAgentState) -> str:
    """Compact state summary shown to the chat router LLM."""
    completed = state.get("agents_completed") or []
    return (
        f"agents_already_completed: {', '.join(completed) if completed else 'none'}\n"
        f"prs_data_available: {state.get('prs') is not None}\n"
        f"genomic_variants_data_available: {state.get('genomic_variants') is not None}\n"
        f"family_history_data_available: {state.get('family_history') is not None}\n"
        f"pgx_data_available: {state.get('pgx') is not None}\n"
        f"phenotype_data_available: {state.get('phenotype') is not None}\n"
    )


def _strip_provenance(data: Any) -> Any:
    """Recursively removes any key named 'provenance' from nested dicts/lists."""
    if isinstance(data, dict):
        return {k: _strip_provenance(v) for k, v in data.items() if k != "provenance"}
    if isinstance(data, list):
        return [_strip_provenance(item) for item in data]
    return data


def _build_clinical_context(state: ChatAgentState) -> str:
    """
    Serialises all available subagent outputs (without provenance) into a
    structured text block for the synthesis LLM.
    """
    sections: list[str] = []

    for key, label in [
        ("prs", "Polygenic Risk Scores (PRS)"),
        ("genomic_variants", "Genomic Variants"),
        ("family_history", "Family History"),
        ("pgx", "Pharmacogenomics (PGX)"),
        ("phenotype", "Phenotype / Clinical Diagnoses"),
    ]:
        state_output = state.get(key)
        if state_output is None:
            continue

        output_obj = getattr(state_output, "output", None)
        if output_obj is None:
            sections.append(
                f"## {label}\nStatus: {state_output.status}\n"
                f"Errors: {state_output.errors}"
            )
            continue

        stripped = _strip_provenance(output_obj.model_dump())
        sections.append(
            f"## {label}\n{json.dumps(stripped, indent=2, default=str)}"
        )

    if not sections:
        return "No clinical data has been retrieved for this patient yet."

    return "\n\n".join(sections)


# ── Nodes ────────────────────────────────────────────────────────────

def chat_router_node(state: ChatAgentState) -> dict:
    """
    Extracts the latest user message, decides whether clinical data retrieval
    is needed, and selectively invalidates cached agent results when the
    query focus has shifted substantially (e.g. disease changed).
    """
    messages = state.get("messages") or []

    # Extract original_query from the latest HumanMessage
    original_query = state.get("original_query", "")
    for msg in reversed(messages):
        if isinstance(msg, HumanMessage):
            original_query = (
                msg.content if isinstance(msg.content, str) else str(msg.content)
            )
            break

    # Call router LLM
    decision: ChatRouterDecision = _router_llm.invoke(
        [
            SystemMessage(content=CHAT_ROUTER_SYSTEM),
            *messages,
            HumanMessage(content=f"Current system state:\n{_router_context_summary(state)}"),
        ]
    )

    updates: dict = {
        "original_query": original_query,
        "next_action": "run_main_agent" if decision.needs_clinical_data else "respond_directly",
    }

    # Selectively invalidate agents whose cached results are stale
    if decision.reset_agents:
        agents_completed = list(state.get("agents_completed") or [])
        for agent_name in decision.reset_agents:
            if agent_name in agents_completed:
                agents_completed.remove(agent_name)
            output_key = _AGENT_TO_OUTPUT_KEY.get(agent_name)
            if output_key:
                updates[output_key] = None
        updates["agents_completed"] = agents_completed

    return updates


def run_main_agent_node(state: ChatAgentState) -> dict:
    """
    Invokes the main orchestration agent with the current chat state as input.
    The main agent's router dispatches only agents not yet in agents_completed,
    enabling incremental data retrieval across conversation turns.
    """
    orchestration_input = {
        "patient_id": state["patient_id"],
        "original_query": state["original_query"],
        "clinician_id": state.get("clinician_id"),
        "conversation_id": state.get("conversation_id"),
        "clinician_specialty": state.get("clinician_specialty"),
        "requested_diseases": state.get("requested_diseases"),
        "requested_genes": state.get("requested_genes"),
        "agents_completed": list(state.get("agents_completed") or []),
        "prs": state.get("prs"),
        "genomic_variants": state.get("genomic_variants"),
        "family_history": state.get("family_history"),
        "pgx": state.get("pgx"),
        "phenotype": state.get("phenotype"),
    }

    result = main_graph.invoke(orchestration_input)

    return {
        "prs": result.get("prs"),
        "genomic_variants": result.get("genomic_variants"),
        "family_history": result.get("family_history"),
        "pgx": result.get("pgx"),
        "phenotype": result.get("phenotype"),
        "agents_completed": result.get("agents_completed", []),
    }


def synthesize_response_node(state: ChatAgentState) -> dict:
    """
    Generates a clinician-facing response to the current query.
    The synthesis LLM is given the full conversation history plus all available
    clinical data (provenance stripped). The latest HumanMessage drives focus.
    """
    clinical_context = _build_clinical_context(state)

    system_content = (
        f"{CHAT_SYNTHESIS_SYSTEM}\n\n"
        f"## Available Clinical Data\n\n"
        f"{clinical_context}"
    )

    response = chat_llm.invoke(
        [
            SystemMessage(content=system_content),
            *(state.get("messages") or []),
        ]
    )

    return {"messages": [AIMessage(content=response.content)]}


# ── Conditional edge ─────────────────────────────────────────────────

def _route(state: ChatAgentState) -> str:
    return state.get("next_action") or "respond_directly"


# ── Graph construction ───────────────────────────────────────────────

def build_graph():
    builder = StateGraph(ChatAgentState)

    builder.add_node("chat_router", chat_router_node)
    builder.add_node("run_main_agent", run_main_agent_node)
    builder.add_node("synthesize_response", synthesize_response_node)

    builder.add_edge(START, "chat_router")

    builder.add_conditional_edges(
        "chat_router",
        _route,
        {
            "run_main_agent": "run_main_agent",
            "respond_directly": "synthesize_response",
        },
    )

    builder.add_edge("run_main_agent", "synthesize_response")
    builder.add_edge("synthesize_response", END)

    return builder.compile()


graph = build_graph()
