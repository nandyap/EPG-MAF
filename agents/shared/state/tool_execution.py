"""
Shared tool execution audit record.
Used by all subagents to track tool calls made during a run.
Separate from DBProvenance — provenance lives on results and links
facts to rows. ToolExecution lives on agent state and tracks the full
execution history including failed calls.
"""
from __future__ import annotations
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field
from datetime import datetime


class ToolExecution(BaseModel):
    """
    Audit record for a single tool call made by any subagent.

    Captures the full input/output pair regardless of success or failure.
    Useful for debugging partial runs and auditing what the agent called
    and in what order.
    """
    tool_name: str = Field(
        ...,
        description="Name of the tool called."
    )
    tool_parameters: Dict[str, Any] = Field(
        ...,
        description="Exact parameters passed to the tool."
    )
    tool_output: Optional[List[Dict[str, Any]]] = Field(
        None,
        description="Raw row dicts returned by the tool. None if the call failed."
    )
    error: Optional[str] = Field(
        None,
        description="Error message if this tool call failed. None on success."
    )
    executed_at: datetime = Field(default_factory=datetime.utcnow)
    duration_ms: Optional[int] = Field(
        None,
        description="How long the tool call took in milliseconds."
    )