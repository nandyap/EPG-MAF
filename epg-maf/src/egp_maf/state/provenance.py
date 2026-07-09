"""Provenance record — traces a clinical fact to its exact DB source row.

Port of the LangGraph prototype's ``agents/shared/state/provenance.py``.
Every clinical fact returned by a Repository carries at least one
:class:`DBProvenance` record — this is the audit-trail guarantee described
in Discovery Report §1.4 and Design ADR-017 / §11.7.

Two extensions vs. the prototype:

- ``trace_id`` and ``span_id`` — optional. Populated when a provenance
  record is constructed inside an active OpenTelemetry span (wired in W08).
- ``retrieved_at`` uses ``datetime.now(timezone.utc)`` instead of the
  deprecated ``datetime.utcnow()`` (Discovery §22 M9).

Behavioural parity is preserved by
``tests/parity/test_row_counts.py`` and (in W03) by field-level snapshot
tests against the prototype's outputs.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class DBProvenance(BaseModel):
    """Immutable record linking one clinical fact to its DB source row.

    ``source_row`` holds the exact dict returned by the underlying SQL query
    (before any privacy stripping). ``fields_derived`` names which fields on
    the parent result model were computed from ``source_row``.

    The record is deliberately verbose because it is the audit-trail primary
    key — a reviewer must be able to reconstruct the tool call, the SQL, the
    JOIN, and the exact row that fed any interpretation.
    """

    tool_name: str = Field(
        ...,
        description="Name of the tool that retrieved this data.",
    )
    tool_parameters: dict[str, Any] = Field(
        ...,
        description="Exact parameters passed to the tool call.",
    )
    source_table: str = Field(
        ...,
        description="DB table (or JOIN expression) this fact was retrieved from.",
    )
    source_row: dict[str, Any] = Field(
        ...,
        description="The exact raw row from the DB that produced this fact.",
    )
    fields_derived: list[str] = Field(
        ...,
        description=(
            "Which fields on the parent model were derived from this row. "
            "e.g. ['prs_score', 'percentile']"
        ),
    )
    retrieved_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="Timestamp of when this data was retrieved (UTC).",
    )
    trace_id: str | None = Field(
        default=None,
        description=(
            "OpenTelemetry trace id, populated by ProvenanceService when a "
            "span is active (W08). Null in tests / offline construction."
        ),
    )
    span_id: str | None = Field(
        default=None,
        description="OpenTelemetry span id, populated as above.",
    )

    model_config = ConfigDict(frozen=True, extra="forbid")


def find_provenance_for_field(
    provenance: list[DBProvenance],
    field: str,
) -> DBProvenance | None:
    """Return the first provenance record whose ``fields_derived`` contains
    ``field``, or ``None``.

    Byte-parity utility with the prototype's function of the same name.
    """
    return next((p for p in provenance if field in p.fields_derived), None)
