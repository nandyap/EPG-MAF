"""
Phenotype subagent: a ReAct agent that retrieves a patient's diagnosis history,
semantically matches conditions to the clinical query, and returns a grouped
phenotypic profile with relevance judgments and interpretations.
"""
from __future__ import annotations
import json
from typing import Any
from datetime import datetime

from langchain_core.messages import HumanMessage
from langgraph.prebuilt import create_react_agent

from agents.phenotype.models.model import phenotype_llm
from agents.phenotype.prompts.prompt import PHENOTYPE_AGENT_SYSTEM_PROMPT
from agents.phenotype.state.schemas import PhenotypeDiseaseResult, PhenotypeResultList
from agents.phenotype.state.state import (
    PhenotypeAgentState,
    PhenotypeStateOutput,
    PhenotypeToolExecution,
)
from agents.phenotype.tools.tools import explore_patient_phenotype, get_patient_diagnoses
from agents.shared.state.provenance import DBProvenance
from config.llm import AGENT_LLM_CONFIGS


# ── Agent definition ─────────────────────────────────────────────────

phenotype_agent = create_react_agent(
    phenotype_llm,
    tools=[
        explore_patient_phenotype,  # Tool 1: patient-scoped distinct terms
        get_patient_diagnoses,      # Tool 2+3: grouped encounter data
    ],
    prompt=PHENOTYPE_AGENT_SYSTEM_PROMPT,
)


# ── Node ─────────────────────────────────────────────────────────────

def phenotype_node(state: dict) -> dict:
    """
    LangGraph node for the phenotype subagent.

    Reads from OrchestratorState:
        - patient_id          (required)
        - original_query      (for LLM semantic matching)
        - requested_diseases  (optional — focus on specific diseases)

    Writes to OrchestratorState:
        - phenotype           PhenotypeStateOutput
        - agents_completed    appends "phenotype"
    """

    # ── Read inputs ───────────────────────────────────────────────
    patient_id: str = state["patient_id"]
    original_query: str = state.get("original_query", "")
    requested_diseases: list[str] | None = state.get("requested_diseases")

    # ── Initialise internal state ─────────────────────────────────
    agent_state = PhenotypeAgentState(
        patient_id=patient_id,
        query_context=original_query,
        requested_diseases=requested_diseases,
        status="running",
        started_at=datetime.utcnow(),
    )

    # ── Build user message ────────────────────────────────────────
    focus_line = (
        f"Focus on the following diseases only: {', '.join(requested_diseases)}."
        if requested_diseases
        else "Retrieve and assess all available diagnoses for this patient."
    )
    user_content = (
        f"Patient ID: {patient_id}\n\n"
        f"{focus_line}\n\n"
        f"User query context: {original_query}"
    )

    # ── Invoke agent ──────────────────────────────────────────────
    try:
        result = phenotype_agent.invoke(
            {"messages": [HumanMessage(content=user_content)]}
        )

        # ── Structured extraction ─────────────────────────────────
        extraction_instruction = HumanMessage(content=(
            f"Based on the tool results above, populate a PhenotypeResultList "
            f"for patient '{patient_id}'. "
            "For each condition returned by get_patient_diagnoses: "
            "populate disease_name, encounter_count, first_encounter_date, "
            "last_encounter_date, codes, terms, and code_types directly from "
            "the grouped tool output row; "
            "set relevant_to_query to True if this condition is semantically "
            "relevant to the original query (apply clinical reasoning — include "
            "synonyms and related conditions); "
            "for relevant conditions, write a 1-2 sentence interpretation "
            "explaining the clinical significance in the context of the query. "
            "Write a 'summary' field covering the patient's overall phenotypic "
            "profile and which conditions are most pertinent to the query."
        ))
        structured_llm = phenotype_llm.with_structured_output(
            PhenotypeResultList, method="function_calling"
        )
        structured: PhenotypeResultList = structured_llm.invoke(
            [*result["messages"], extraction_instruction]
        )

        # ── Post-extraction: programmatic fields ──────────────────
        structured.patient_id = patient_id

        # relevant_disease_names — derived programmatically, not LLM-filled
        structured.relevant_disease_names = [
            r.disease_name
            for r in structured.results
            if r.relevant_to_query and r.disease_name
        ]

        # model attribution
        _model = AGENT_LLM_CONFIGS["phenotype"].model
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
    phenotype_output = PhenotypeStateOutput.from_agent_state(
        agent_state, expected_patient_id=patient_id
    )

    return {
        "phenotype": phenotype_output,
        "agents_completed": state.get("agents_completed", []) + ["phenotype"],
    }


# ── Helpers ──────────────────────────────────────────────────────────

def _extract_tool_executions(
    messages: list[Any],
) -> list[PhenotypeToolExecution]:
    """Parses LangGraph message history to extract tool calls and outputs."""
    from langchain_core.messages import AIMessage, ToolMessage

    executions: list[PhenotypeToolExecution] = []
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
                PhenotypeToolExecution(
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


# list_patient_diagnosis_terms is a compact discovery tool — provenance
# is attached from get_patient_diagnoses which has the full grouped detail.
_TOOL_SOURCE_TABLE: dict[str, str] = {
    "get_patient_diagnoses": "diagnoses",
}
_TOOL_FIELDS_DERIVED: dict[str, list[str]] = {
    "get_patient_diagnoses": [
        "disease_name", "encounter_count",
        "first_encounter_date", "last_encounter_date",
        "codes", "terms", "code_types",
    ],
}


def _attach_provenance(
    results: list[PhenotypeDiseaseResult],
    tool_executions: list[PhenotypeToolExecution],
) -> None:
    """
    Attaches a DBProvenance record to each result, matched on disease_name.
    Uses the first get_patient_diagnoses row whose disease_name matches.
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
                if row.get("disease_name") != result.disease_name:
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
