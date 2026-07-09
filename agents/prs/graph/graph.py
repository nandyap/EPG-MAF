"""
PRS subagent: a ReAct agent that retrieves and interprets Polygenic Risk
Scores for a patient, given their patient_id and any diseases of interest
derived from the orchestrator state.
"""
from __future__ import annotations
import json
from typing import Any
from datetime import datetime

from langchain_core.messages import HumanMessage
from langgraph.prebuilt import create_react_agent

from agents.prs.models.model import prs_llm
from agents.prs.prompts.prompt import PRS_AGENT_SYSTEM_PROMPT
from agents.prs.state.schemas import PRSResult, PRSResultList
from agents.prs.state.state import PRSAgentState, PRSStateOutput, PRSToolExecution
from agents.prs.tools.tools import explore_patient_prs, search_prs_annotations, get_patient_prs
from agents.shared.state.provenance import DBProvenance
from config.llm import AGENT_LLM_CONFIGS


# ── Agent definition ────────────────────────────────────────────────
# response_format is NOT set here — create_react_agent uses OpenAI strict
# structured-output mode by default, which rejects Dict[str, Any] fields.
# Structured extraction is done in prs_node using method="function_calling".

prs_agent = create_react_agent(
    prs_llm,
    tools=[
        explore_patient_prs,        # Tool 1: patient-scoped key discovery
        search_prs_annotations,     # Tool 2: reference/annotation lookup
        get_patient_prs,            # Tool 3: patient data JOIN annotations
    ],
    prompt=PRS_AGENT_SYSTEM_PROMPT,
)


# ── Node ─────────────────────────────────────────────────────────────

def prs_node(state: dict) -> dict:
    """
    LangGraph node for the PRS subagent.

    Reads from OrchestratorState:
        - patient_id        (required)
        - original_query    (for LLM interpretation context)
        - requested_diseases (optional — filters PRS to specific diseases)

    Writes to OrchestratorState:
        - prs               PRSStateOutput (slim orchestrator-facing result)
        - agents_completed  appends "prs"
    """

    # ── Read inputs from orchestrator state ──────────────────────
    patient_id: str = state["patient_id"]
    original_query: str = state.get("original_query", "")
    requested_diseases: list[str] | None = state.get("requested_diseases")

    # ── Initialise internal agent state ──────────────────────────
    agent_state = PRSAgentState(
        patient_id=patient_id,
        query_context=original_query,
        requested_diseases=requested_diseases,
        status="running",
        started_at=datetime.utcnow(),
    )

    # ── Build user message ────────────────────────────────────────
    disease_line = (
        f"Focus on the following diseases only: {', '.join(requested_diseases)}."
        if requested_diseases
        else "Retrieve all available PRS scores for this patient."
    )

    user_content = (
        f"Patient ID: {patient_id}\n\n"
        f"{disease_line}\n\n"
        f"User query context: {original_query}"
    )

    # ── Invoke agent ──────────────────────────────────────────────
    try:
        result = prs_agent.invoke(
            {"messages": [HumanMessage(content=user_content)]}
        )

        # ── Structured extraction (function_calling avoids strict-mode schema issues)
        # Append an instruction so the LLM fills interpretation + summary,
        # not just extracts the raw tool data.
        extraction_instruction = HumanMessage(content=(
            "Based on the tool results above, populate the PRSResultList for this patient. "
            "For each result write a 1-2 sentence clinical interpretation in the "
            "'interpretation' field explaining what the risk band and percentile mean. "
            "Write a 'summary' covering the overall polygenic risk picture across all traits."
        ))
        structured_llm = prs_llm.with_structured_output(
            PRSResultList, method="function_calling"
        )
        structured: PRSResultList = structured_llm.invoke(
            [*result["messages"], extraction_instruction]
        )

        # ── Post-extraction: set model fields + attach DB provenance
        tool_executions = _extract_tool_executions(result["messages"])
        _model = AGENT_LLM_CONFIGS["prs"].model

        for r in structured.results:
            if r.interpretation and not r.interpretation_model:
                r.interpretation_model = _model
        if structured.summary and not structured.summary_model:
            structured.summary_model = _model

        _attach_provenance(structured.results, tool_executions)

        agent_state.output = structured
        agent_state.status = "complete"
        agent_state.tool_executions = tool_executions

    except Exception as e:
        agent_state.status = "failed"
        agent_state.errors.append(str(e))

    finally:
        agent_state.completed_at = datetime.utcnow()

    # ── Build slim output for orchestrator ────────────────────────
    prs_output = PRSStateOutput.from_agent_state(agent_state)

    return {
        "prs": prs_output,
        "agents_completed": state.get("agents_completed", []) + ["prs"],
    }


# ── Helpers ──────────────────────────────────────────────────────────

def _extract_tool_executions(messages: list[Any]) -> list[PRSToolExecution]:
    """
    Parses LangGraph message history to extract tool calls and their outputs.
    Pairs AIMessage tool_calls with their ToolMessage responses.

    This gives the full audit trail of what the agent actually called,
    what parameters it used, and what came back — regardless of whether
    those calls made it into a DBProvenance record on a result.
    """
    from langchain_core.messages import AIMessage, ToolMessage

    executions: list[PRSToolExecution] = []
    tool_call_map: dict[str, dict] = {}

    for message in messages:

        # AIMessage carries the tool call intent + parameters
        if isinstance(message, AIMessage) and message.tool_calls:
            for tc in message.tool_calls:
                tool_call_map[tc["id"]] = {
                    "tool_name": tc["name"],
                    "tool_parameters": tc["args"],
                }

        # ToolMessage carries the response — match back to the call
        elif isinstance(message, ToolMessage):
            call_info = tool_call_map.get(message.tool_call_id, {})
            executions.append(
                PRSToolExecution(
                    tool_name=call_info.get("tool_name", "unknown"),
                    tool_parameters=call_info.get("tool_parameters", {}),
                    tool_output=_parse_tool_output(message.content),
                    error=None,
                )
            )

    return executions


def _parse_tool_output(content: Any) -> list[dict]:
    """Parse a ToolMessage's content into a list of row dicts."""
    if isinstance(content, list):
        return content
    if isinstance(content, str):
        try:
            parsed = json.loads(content)
            if isinstance(parsed, list):
                return parsed
            return [parsed]
        except json.JSONDecodeError:
            pass
    return [{"raw": str(content)}]


# list_prs_catalog is a discovery tool — its output is reference data, not
# patient-specific. It is excluded here so _attach_provenance skips it.
_TOOL_SOURCE_TABLE: dict[str, str] = {
    "get_patient_prs": "patient_prs JOIN prs_annotations",
}
_TOOL_FIELDS_DERIVED: dict[str, list[str]] = {
    "get_patient_prs": [
        "prs_name", "disease_name", "prs_score",
        "percentile", "risk_band", "source", "metadata_notes",
    ],
}


def _attach_provenance(
    results: list[PRSResult],
    tool_executions: list[PRSToolExecution],
) -> None:
    """
    For each PRSResult, find matching rows in the tool execution audit trail
    and attach a DBProvenance record per source table touched.

    Matches on prs_name so each result gets provenance from whichever tool
    calls returned data for it.
    """
    for result in results:
        seen_tools: set[str] = set()
        for exec in tool_executions:
            if exec.tool_name not in _TOOL_SOURCE_TABLE:
                continue
            if not exec.tool_output:
                continue
            if exec.tool_name in seen_tools:  # one provenance entry per tool per result
                continue
            for row in exec.tool_output:
                if not isinstance(row, dict):
                    continue
                if row.get("prs_name") != result.prs_name:
                    continue
                result.provenance.append(DBProvenance(
                    tool_name=exec.tool_name,
                    tool_parameters=exec.tool_parameters,
                    source_table=_TOOL_SOURCE_TABLE[exec.tool_name],
                    source_row=row,
                    fields_derived=_TOOL_FIELDS_DERIVED[exec.tool_name],
                ))
                seen_tools.add(exec.tool_name)
                break