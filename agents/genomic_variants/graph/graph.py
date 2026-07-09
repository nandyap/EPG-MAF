"""
Genomic variants subagent: a ReAct agent that retrieves and interprets
genomic variants for a patient, including pathogenicity classification,
gene context, and extended annotations.
"""
from __future__ import annotations
import json
from typing import Any
from datetime import datetime

from langchain_core.messages import HumanMessage
from langgraph.prebuilt import create_react_agent

from agents.genomic_variants.models.model import genomic_variants_llm
from agents.genomic_variants.prompts.prompt import GENOMIC_VARIANTS_AGENT_SYSTEM_PROMPT
from agents.genomic_variants.state.schemas import (
    GenomicVariantResult,
    GenomicVariantsResultList,
)
from agents.genomic_variants.state.state import (
    GenomicVariantsAgentState,
    GenomicVariantsStateOutput,
    GenomicVariantsToolExecution,
)
from agents.genomic_variants.tools.tools import (
    explore_patient_genomic_variants,
    search_variant_annotations,
    get_patient_genomic_variants,
)
from agents.shared.state.provenance import DBProvenance
from config.llm import AGENT_LLM_CONFIGS


# ── Agent definition ─────────────────────────────────────────────────
# response_format is NOT set — strict structured-output mode rejects
# Dict[str, Any] fields (present in VariantExtendedAnnotations.raw_annotations
# and DBProvenance). Structured extraction is done post-hoc in
# genomic_variants_node using method="function_calling".

genomic_variants_agent = create_react_agent(
    genomic_variants_llm,
    tools=[
        explore_patient_genomic_variants,  # Tool 1: patient-scoped variant key discovery
        search_variant_annotations,        # Tool 2: reference/annotation lookup
        get_patient_genomic_variants,      # Tool 3: patient data JOIN annotations
    ],
    prompt=GENOMIC_VARIANTS_AGENT_SYSTEM_PROMPT,
)


# ── Node ─────────────────────────────────────────────────────────────

def genomic_variants_node(state: dict) -> dict:
    """
    LangGraph node for the genomic variants subagent.

    Reads from OrchestratorState:
        - patient_id                (required)
        - original_query            (for LLM interpretation context)
        - requested_diseases        (optional — filter by disease)
        - requested_genes           (optional — filter by gene)
        - requested_variant_types   (optional — filter by variant type)
        - requested_pathogenicity   (optional — filter by pathogenicity class)

    Writes to OrchestratorState:
        - genomic_variants          GenomicVariantsStateOutput
        - agents_completed          appends "genomic_variants"
    """

    # ── Read inputs from orchestrator state ──────────────────────
    patient_id: str = state["patient_id"]
    original_query: str = state.get("original_query", "")
    requested_diseases: list[str] | None = state.get("requested_diseases")
    requested_genes: list[str] | None = state.get("requested_genes")
    requested_variant_types: list[str] | None = state.get("requested_variant_types")
    requested_pathogenicity: list[str] | None = state.get("requested_pathogenicity")

    # ── Initialise internal agent state ──────────────────────────
    agent_state = GenomicVariantsAgentState(
        patient_id=patient_id,
        query_context=original_query,
        requested_diseases=requested_diseases,
        requested_genes=requested_genes,
        requested_variant_types=requested_variant_types,
        requested_pathogenicity=requested_pathogenicity,
        status="running",
        started_at=datetime.utcnow(),
    )

    # ── Build user message ────────────────────────────────────────
    filter_lines: list[str] = []
    if requested_diseases:
        filter_lines.append(f"Diseases of interest: {', '.join(requested_diseases)}.")
    if requested_genes:
        filter_lines.append(f"Genes of interest: {', '.join(requested_genes)}.")
    if requested_variant_types:
        filter_lines.append(f"Variant types of interest: {', '.join(requested_variant_types)}.")
    if requested_pathogenicity:
        filter_lines.append(f"Pathogenicity classes of interest: {', '.join(requested_pathogenicity)}.")

    filter_text = (
        "\n".join(filter_lines)
        if filter_lines
        else "Retrieve all available variants for this patient."
    )

    user_content = (
        f"Patient ID: {patient_id}\n\n"
        f"{filter_text}\n\n"
        f"User query context: {original_query}"
    )

    # ── Invoke agent ──────────────────────────────────────────────
    try:
        result = genomic_variants_agent.invoke(
            {"messages": [HumanMessage(content=user_content)]}
        )

        # ── Structured extraction ─────────────────────────────────
        # Append an instruction so the LLM writes interpretations and
        # populates the nested annotation sub-models (not just raw data).
        extraction_instruction = HumanMessage(content=(
            f"Based on the tool results above, populate a GenomicVariantsResultList "
            f"for patient '{patient_id}'. "
            "For each variant: "
            "populate sample_data from the patient_variants columns (genotype, sequencing_platform, variant_caller, call_quality); "
            "populate core_annotations from the top-level annotation columns (gene, variant_type, pathogenicity, disease_name, notes); "
            "populate extended_annotations typed fields (hgvs_c, hgvs_p, gnomad_af, rsid, etc.) "
            "by parsing them out of annotations_json, "
            "and put any remaining annotations_json content into raw_annotations as a dict; "
            "write a 1-2 sentence clinical interpretation in the 'interpretation' field "
            "explaining the variant's pathogenicity and clinical significance. "
            "Write a 'summary' field covering the overall variant picture for this patient."
        ))
        structured_llm = genomic_variants_llm.with_structured_output(
            GenomicVariantsResultList, method="function_calling"
        )
        structured: GenomicVariantsResultList = structured_llm.invoke(
            [*result["messages"], extraction_instruction]
        )

        # ── Post-extraction: set programmatic fields ──────────────
        # patient_id — set explicitly rather than relying on LLM
        structured.patient_id = patient_id

        # pathogenic_count — derived from results, not LLM-filled
        _pathogenic = {"Pathogenic", "Likely Pathogenic"}
        structured.pathogenic_count = sum(
            1 for r in structured.results
            if r.core_annotations
            and r.core_annotations.pathogenicity in _pathogenic
        )

        # model attribution
        _model = AGENT_LLM_CONFIGS["genomic_variants"].model
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
    gv_output = GenomicVariantsStateOutput.from_agent_state(
        agent_state, expected_patient_id=patient_id
    )

    return {
        "genomic_variants": gv_output,
        "agents_completed": state.get("agents_completed", []) + ["genomic_variants"],
    }


# ── Helpers ──────────────────────────────────────────────────────────

def _extract_tool_executions(
    messages: list[Any],
) -> list[GenomicVariantsToolExecution]:
    """
    Parses LangGraph message history to extract tool calls and outputs.
    Pairs AIMessage tool_calls with their ToolMessage responses.
    """
    from langchain_core.messages import AIMessage, ToolMessage

    executions: list[GenomicVariantsToolExecution] = []
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
                GenomicVariantsToolExecution(
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


# list_variant_catalog is a discovery tool — its output is reference data, not
# patient-specific. It is excluded here so _attach_provenance skips it.
_TOOL_SOURCE_TABLE: dict[str, str] = {
    "get_patient_genomic_variants": "patient_variants JOIN variant_annotations",
}

_TOOL_FIELDS_DERIVED: dict[str, list[str]] = {
    "get_patient_genomic_variants": [
        "variant_id", "genotype", "sequencing_platform", "variant_caller",
        "call_quality", "gene", "variant_type", "pathogenicity",
        "pathogenicity_source", "disease_name", "inheritance",
        "annotations_json", "notes",
    ],
}


def _attach_provenance(
    results: list[GenomicVariantResult],
    tool_executions: list[GenomicVariantsToolExecution],
) -> None:
    """
    For each GenomicVariantResult, find matching rows in the tool execution
    audit trail and attach a DBProvenance record per source table touched.

    Matches on variant_id so each result gets provenance from the tool calls
    that returned data for it.
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
                if row.get("variant_id") != result.variant_id:
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
