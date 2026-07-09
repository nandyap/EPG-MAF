from __future__ import annotations
from typing import Any, Dict, List
from pydantic import BaseModel, Field
from datetime import datetime


class DBProvenance(BaseModel):
    """
    Provenance record linking any clinical fact back to its exact
    DB source row and the tool call that retrieved it.
    
    Used by all subagents — lives in shared/ because every agent
    needs to trace facts back to their source.
    """
    tool_name: str = Field(
        ...,
        description="Name of the LangGraph tool that retrieved this data."
    )
    tool_parameters: Dict[str, Any] = Field(
        ...,
        description="Exact parameters passed to the tool call.",
        json_schema_extra={"additionalProperties": False},
    )
    source_table: str = Field(
        ...,
        description="DB table this fact was retrieved from e.g. patient_prs."
    )
    source_row: Dict[str, Any] = Field(
        ...,
        description="The exact raw row from the DB that produced this fact.",
        json_schema_extra={"additionalProperties": False},
    )
    fields_derived: List[str] = Field(
        ...,
        description=(
            "Which fields on the parent model were derived from this row. "
            "Allows any field to be traced back to its exact source. "
            "e.g. ['prs_score', 'percentile']"
        )
    )
    retrieved_at: datetime = Field(
        default_factory=datetime.utcnow,
        description="Timestamp of when this data was retrieved."
    )


def find_provenance_for_field(
    provenance: List[DBProvenance],
    field: str
) -> DBProvenance | None:
    """
    Utility — trace any named field back to its provenance record.
    
    Usage:
        prov = find_provenance_for_field(result.provenance, "percentile")
    """
    return next(
        (p for p in provenance if field in p.fields_derived),
        None
    )