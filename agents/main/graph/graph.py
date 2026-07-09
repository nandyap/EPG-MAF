"""
Main orchestration agent: loop-style router that dispatches to specialist
subagents based on the clinician's query and tracks completion.

Flow:
    START → router → prs_agent ──────┐
                   → genomic_variants_agent ──┤
                   → END             ← router returns "end" when done
    Each subagent returns to router after completing.
"""
from __future__ import annotations

from typing import Literal

from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel, Field

from agents.genomic_variants.graph.graph import genomic_variants_node
from agents.family_history.graph.graph import family_history_node
from agents.pgx.graph.graph import pgx_node
from agents.phenotype.graph.graph import phenotype_node
from agents.main.models.model import main_llm
from agents.main.prompts.prompt import MAIN_AGENT_SYSTEM
from agents.main.state.state import OrchestrationAgentState
from agents.prs.graph.graph import prs_node


# ── Router decision model ────────────────────────────────────────────

class RouterDecision(BaseModel):
    """Structured routing decision emitted by the orchestrator LLM."""

    next: Literal["prs_agent", "genomic_variants_agent", "family_history_agent", "pgx_agent", "phenotype_agent", "end"] = Field(
        description="Which subagent to run next, or 'end' when all relevant agents are done."
    )
    reason: str = Field(description="One-sentence justification for this routing decision.")
    requested_diseases: list[str] | None = Field(
        None,
        description=(
            "Disease names to filter the subagent to. Set when the query targets specific "
            "conditions (e.g. [\"Alzheimer's disease\"]). Leave null for broad queries."
        ),
    )


_router_llm = main_llm.with_structured_output(RouterDecision)


# ── State summary (shown to router LLM each step) ───────────────────

def _state_summary(state: OrchestrationAgentState) -> str:
    """
    Compact representation of current orchestration state shown to the
    router LLM so it can decide what to do next without seeing full outputs.
    """
    completed = state.get("agents_completed", [])
    return (
        f"patient_id: {state.get('patient_id')}\n"
        f"original_query: {state.get('original_query')}\n"
        f"agents_already_completed: {', '.join(completed) if completed else 'none'}\n"
        f"prs_output_available: {state.get('prs') is not None}\n"
        f"genomic_variants_output_available: {state.get('genomic_variants') is not None}\n"
        f"family_history_output_available: {state.get('family_history') is not None}\n"
        f"pgx_output_available: {state.get('pgx') is not None}\n"
        f"phenotype_output_available: {state.get('phenotype') is not None}\n"
    )


# ── Router node ──────────────────────────────────────────────────────

def router_node(state: OrchestrationAgentState) -> dict:
    """
    Invokes the router LLM to decide which subagent to dispatch next.
    Returns only the `next` routing key — no mutation of other state fields.
    """
    decision: RouterDecision = _router_llm.invoke(
        [
            SystemMessage(content=MAIN_AGENT_SYSTEM),
            HumanMessage(content=_state_summary(state)),
        ]
    )
    return {
        "next": decision.next,
        "requested_diseases": decision.requested_diseases,
    }


# ── Conditional edge function ────────────────────────────────────────

def _route(state: OrchestrationAgentState) -> str:
    return state.get("next") or "end"


# ── Graph construction ───────────────────────────────────────────────

def build_graph():
    builder = StateGraph(OrchestrationAgentState)

    # Nodes
    builder.add_node("router", router_node)
    builder.add_node("prs_agent", prs_node)
    builder.add_node("genomic_variants_agent", genomic_variants_node)
    builder.add_node("family_history_agent", family_history_node)
    builder.add_node("pgx_agent", pgx_node)
    builder.add_node("phenotype_agent", phenotype_node)

    # Entry
    builder.add_edge(START, "router")

    # Router decides where to go
    builder.add_conditional_edges(
        "router",
        _route,
        {
            "prs_agent": "prs_agent",
            "genomic_variants_agent": "genomic_variants_agent",
            "family_history_agent": "family_history_agent",
            "pgx_agent": "pgx_agent",
            "phenotype_agent": "phenotype_agent",
            "end": END,
        },
    )

    # Each subagent returns to router for re-evaluation
    builder.add_edge("prs_agent", "router")
    builder.add_edge("genomic_variants_agent", "router")
    builder.add_edge("family_history_agent", "router")
    builder.add_edge("pgx_agent", "router")
    builder.add_edge("phenotype_agent", "router")

    return builder.compile()


graph = build_graph()
