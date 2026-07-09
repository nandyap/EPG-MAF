"""
PGX subagent: a ReAct agent that retrieves a patient's diplotype/phenotype
status and interprets drug-gene interaction recommendations.
"""
from __future__ import annotations
import json
from typing import Any
from datetime import datetime

from langchain_core.messages import HumanMessage
from langgraph.prebuilt import create_react_agent

from agents.pgx.models.model import pgx_llm
from agents.pgx.prompts.prompt import PGX_AGENT_SYSTEM_PROMPT
from agents.pgx.state.schemas import PGXDrugResult, PGXResultList
from agents.pgx.state.state import PGXAgentState, PGXStateOutput, PGXToolExecution
from agents.pgx.tools.tools import explore_patient_pgx, search_pgx_annotations, get_patient_pgx
from agents.shared.state.provenance import DBProvenance
from config.llm import AGENT_LLM_CONFIGS


# ── Agent definition ─────────────────────────────────────────────────
# response_format is NOT set — strict structured-output mode rejects
# Dict[str, Any] fields in DBProvenance. Structured extraction is done
# post-hoc using method="function_calling".

pgx_agent = create_react_agent(
    pgx_llm,
    tools=[
        explore_patient_pgx,        # Tool 1: patient-scoped gene/phenotype discovery
        search_pgx_annotations,     # Tool 2: reference/annotation lookup
        get_patient_pgx,            # Tool 3: patient data JOIN annotations
    ],
    prompt=PGX_AGENT_SYSTEM_PROMPT,
)


# ── Node ─────────────────────────────────────────────────────────────

def pgx_node(state: dict) -> dict:
    """
    LangGraph node for the PGX subagent.

    Reads from OrchestratorState:
        - patient_id          (required)
        - original_query      (for LLM interpretation context)
        - requested_genes     (optional — filter by gene)

    Writes to OrchestratorState:
        - pgx                 PGXStateOutput
        - agents_completed    appends "pgx"
    """

    # ── Read inputs ───────────────────────────────────────────────
    patient_id: str = state["patient_id"]
    original_query: str = state.get("original_query", "")
    requested_genes: list[str] | None = state.get("requested_genes")

    # ── Initialise internal state ─────────────────────────────────
    agent_state = PGXAgentState(
        patient_id=patient_id,
        query_context=original_query,
        requested_genes=requested_genes,
        status="running",
        started_at=datetime.utcnow(),
    )

    # ── Build user message ────────────────────────────────────────
    gene_line = (
        f"Focus on the following genes only: {', '.join(requested_genes)}."
        if requested_genes
        else "Retrieve all available PGX records for this patient."
    )
    user_content = (
        f"Patient ID: {patient_id}\n\n"
        f"{gene_line}\n\n"
        f"User query context: {original_query}"
    )

    # ── Invoke agent ──────────────────────────────────────────────
    try:
        result = pgx_agent.invoke(
            {"messages": [HumanMessage(content=user_content)]}
        )

        # ── Structured extraction ─────────────────────────────────
        extraction_instruction = HumanMessage(content=(
            f"Based on the tool results above, populate a PGXResultList "
            f"for patient '{patient_id}'. "
            "For each gene-drug pair: "
            "populate gene, diplotype, phenotype from the patient status columns; "
            "populate drug, recommendation, summary, source from the annotation columns; "
            "write a 1-2 sentence clinical interpretation in the 'interpretation' field — "
            "explain what the patient's metabolizer phenotype means for this drug "
            "and what action (if any) the recommendation implies. "
            "Write a 'summary' field covering the overall pharmacogenomics picture "
            "for this patient across all assessed genes."
        ))
        structured_llm = pgx_llm.with_structured_output(
            PGXResultList, method="function_calling"
        )
        structured: PGXResultList = structured_llm.invoke(
            [*result["messages"], extraction_instruction]
        )

        # ── Post-extraction: programmatic fields ──────────────────
        structured.patient_id = patient_id

        # genes_assessed — derived from results, not LLM-filled
        structured.genes_assessed = list({
            r.gene for r in structured.results if r.gene
        })

        # drugs_with_recommendations — drugs that have a non-null recommendation
        structured.drugs_with_recommendations = list({
            r.drug for r in structured.results
            if r.drug and r.recommendation is not None
        })

        # model attribution
        _model = AGENT_LLM_CONFIGS["pgx"].model
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
    pgx_output = PGXStateOutput.from_agent_state(
        agent_state, expected_patient_id=patient_id
    )

    return {
        "pgx": pgx_output,
        "agents_completed": state.get("agents_completed", []) + ["pgx"],
    }


# ── Helpers ──────────────────────────────────────────────────────────

def _extract_tool_executions(
    messages: list[Any],
) -> list[PGXToolExecution]:
    """Parses LangGraph message history to extract tool calls and outputs."""
    from langchain_core.messages import AIMessage, ToolMessage

    executions: list[PGXToolExecution] = []
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
                PGXToolExecution(
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


# list_pgx_catalog is a discovery tool — reference data only,
# excluded from provenance so _attach_provenance skips it.
_TOOL_SOURCE_TABLE: dict[str, str] = {
    "get_patient_pgx": "patient_pgx_status LEFT JOIN pgx_annotations",
}
_TOOL_FIELDS_DERIVED: dict[str, list[str]] = {
    "get_patient_pgx": [
        "gene", "diplotype", "phenotype",
        "drug", "recommendation", "summary", "source",
    ],
}


def _attach_provenance(
    results: list[PGXDrugResult],
    tool_executions: list[PGXToolExecution],
) -> None:
    """
    Attaches a DBProvenance record to each result, matched on the
    composite key (gene, drug).
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
                    row.get("gene") != result.gene
                    or row.get("drug") != result.drug
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
