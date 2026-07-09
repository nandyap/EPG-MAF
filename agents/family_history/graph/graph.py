"""
Family history subagent: a ReAct agent that retrieves and interprets
family history criteria records for a patient, including threshold
evaluation and privacy-aware qualification of incomplete searches.
"""
from __future__ import annotations
import json
from typing import Any
from datetime import datetime

from langchain_core.messages import HumanMessage
from langgraph.prebuilt import create_react_agent

from agents.family_history.models.model import family_history_llm
from agents.family_history.prompts.prompt import FAMILY_HISTORY_AGENT_SYSTEM_PROMPT
from agents.family_history.state.schemas import (
    FamilyHistoryCriteriaResult,
    FamilyHistoryResultList,
)
from agents.family_history.state.state import (
    FamilyHistoryAgentState,
    FamilyHistoryStateOutput,
    FamilyHistoryToolExecution,
)
from agents.family_history.tools.tools import (
    explore_patient_family_history,
    search_family_history_annotations,
    get_patient_family_history,
)
from agents.shared.state.provenance import DBProvenance
from config.llm import AGENT_LLM_CONFIGS


# ── Agent definition ─────────────────────────────────────────────────
# response_format is NOT set — strict structured-output mode rejects
# Dict[str, Any] fields in DBProvenance. Structured extraction is done
# post-hoc using method="function_calling".

family_history_agent = create_react_agent(
    family_history_llm,
    tools=[
        explore_patient_family_history,      # Tool 1: patient-scoped key discovery
        search_family_history_annotations,   # Tool 2: reference/annotation lookup
        get_patient_family_history,          # Tool 3: patient data JOIN annotations
    ],
    prompt=FAMILY_HISTORY_AGENT_SYSTEM_PROMPT,
)


# ── Node ─────────────────────────────────────────────────────────────

def family_history_node(state: dict) -> dict:
    """
    LangGraph node for the family history subagent.

    Reads from OrchestratorState:
        - patient_id          (required)
        - original_query      (for LLM interpretation context)
        - requested_diseases  (optional — filter by disease)

    Writes to OrchestratorState:
        - family_history      FamilyHistoryStateOutput
        - agents_completed    appends "family_history"
    """

    # ── Read inputs ───────────────────────────────────────────────
    patient_id: str = state["patient_id"]
    original_query: str = state.get("original_query", "")
    requested_diseases: list[str] | None = state.get("requested_diseases")

    # ── Initialise internal state ─────────────────────────────────
    agent_state = FamilyHistoryAgentState(
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
        else "Retrieve all available family history records for this patient."
    )
    user_content = (
        f"Patient ID: {patient_id}\n\n"
        f"{disease_line}\n\n"
        f"User query context: {original_query}"
    )

    # ── Invoke agent ──────────────────────────────────────────────
    try:
        result = family_history_agent.invoke(
            {"messages": [HumanMessage(content=user_content)]}
        )

        # ── Structured extraction ─────────────────────────────────
        extraction_instruction = HumanMessage(content=(
            f"Based on the tool results above, populate a FamilyHistoryResultList "
            f"for patient '{patient_id}'. "
            "For each family history record: "
            "populate all threshold fields (disease_name, criteria_name, "
            "affected_relative_count, total_relatives_searched, "
            "meets_threshold, "
            "search_context_notes, last_observed_diagnosis_in_database) from the patient data columns; "
            "populate criteria_description and criteria_source from the annotation JOIN columns; "
            "write a 1-2 sentence clinical interpretation in the 'interpretation' field — "
            "if search_context_notes indicates an incomplete search, explicitly qualify the result "
            "(e.g. 'Threshold not met; however, 0 eligible females over 30 were included — "
            "result may underestimate risk'). "
            "Write a 'summary' field covering the overall family history picture."
        ))
        structured_llm = family_history_llm.with_structured_output(
            FamilyHistoryResultList, method="function_calling"
        )
        structured: FamilyHistoryResultList = structured_llm.invoke(
            [*result["messages"], extraction_instruction]
        )

        # ── Post-extraction: programmatic fields ──────────────────
        structured.patient_id = patient_id

        # diseases_meeting_threshold — derived from results, not LLM-filled
        structured.diseases_meeting_threshold = list({
            r.disease_name for r in structured.results
            if r.meets_threshold and r.disease_name
        })

        # model attribution
        _model = AGENT_LLM_CONFIGS["family_history"].model
        for r in structured.results:
            if r.interpretation and not r.interpretation_model:
                r.interpretation_model = _model
        if structured.summary and not structured.summary_model:
            structured.summary_model = _model

        # provenance
        tool_executions = _extract_tool_executions(result["messages"])
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
    fh_output = FamilyHistoryStateOutput.from_agent_state(
        agent_state, expected_patient_id=patient_id
    )

    return {
        "family_history": fh_output,
        "agents_completed": state.get("agents_completed", []) + ["family_history"],
    }


# ── Helpers ──────────────────────────────────────────────────────────

def _extract_tool_executions(
    messages: list[Any],
) -> list[FamilyHistoryToolExecution]:
    """Parses LangGraph message history to extract tool calls and outputs."""
    from langchain_core.messages import AIMessage, ToolMessage

    executions: list[FamilyHistoryToolExecution] = []
    tool_call_map: dict[str, dict] = {}

    for message in messages:
        if isinstance(message, AIMessage) and message.tool_calls:
            for tc in message.tool_calls:
                tool_call_map[tc["id"]] = {
                    "tool_name": tc["name"],
                    "tool_parameters": tc["args"],
                }
        elif isinstance(message, ToolMessage):
            call_info = tool_call_map.get(message.tool_call_id, {})
            executions.append(
                FamilyHistoryToolExecution(
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


# list_family_history_catalog is a discovery tool — reference data only,
# excluded from provenance so _attach_provenance skips it.
_TOOL_SOURCE_TABLE: dict[str, str] = {
    "get_patient_family_history": "patient_kinship_history JOIN kinship_history_annotations",
}
_TOOL_FIELDS_DERIVED: dict[str, list[str]] = {
    "get_patient_family_history": [
        "disease_name", "criteria_name",
        "affected_relative_count", "total_relatives_searched",
        "meets_threshold", "search_context_notes",
        "last_observed_diagnosis_in_database",
        "criteria_description", "criteria_source",
    ],
}


def _attach_provenance(
    results: list[FamilyHistoryCriteriaResult],
    tool_executions: list[FamilyHistoryToolExecution],
) -> None:
    """
    Attaches a DBProvenance record to each result, matched on the
    composite key (disease_name, criteria_name).
    """
    for result in results:
        seen_tools: set[str] = set()
        for exec in tool_executions:
            if exec.tool_name not in _TOOL_SOURCE_TABLE:
                continue
            if not exec.tool_output:
                continue
            if exec.tool_name in seen_tools:
                continue
            for row in exec.tool_output:
                if not isinstance(row, dict):
                    continue
                if (
                    row.get("disease_name") != result.disease_name
                    or row.get("criteria_name") != result.criteria_name
                ):
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
