"""HTTP request/response schemas for ``POST /chat``.

Contract lives here (not in :mod:`egp_maf.workflow.state`) so the API
surface is decoupled from the internal workflow state — clients can't
send fields like ``ctx`` or ``agents_completed`` even by accident.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ChatRequestBody(BaseModel):
    """Body of ``POST /chat``.

    Auth: the clinician identity comes from the bearer token (W07).
    The body carries only the per-turn payload.
    """

    thread_id: str = Field(..., min_length=1, max_length=128)
    patient_id: str = Field(..., min_length=1, max_length=128)
    message: str = Field(..., min_length=1, max_length=8_000)
    # Optional filters — the router MAY tighten these further.
    requested_diseases: list[str] | None = None
    requested_genes: list[str] | None = None

    model_config = ConfigDict(extra="forbid")


class ChatSpecialistSlotView(BaseModel):
    """Per-domain slot summary in the response body.

    Only clinician-visible fields — no provenance ``source_row``,
    no LLM prompt/completion text.
    """

    status: str
    output: dict[str, Any] | None = None
    errors: list[str] = Field(default_factory=list)

    model_config = ConfigDict(extra="forbid")


class ChatResponseBody(BaseModel):
    """Body of a successful ``POST /chat`` (HTTP 200)."""

    thread_id: str
    patient_id: str
    trace_id: str | None = None
    reply: str = ""
    agents_completed: list[str] = Field(default_factory=list)
    prs: ChatSpecialistSlotView | None = None
    genomic_variants: ChatSpecialistSlotView | None = None
    family_history: ChatSpecialistSlotView | None = None
    pgx: ChatSpecialistSlotView | None = None
    phenotype: ChatSpecialistSlotView | None = None

    model_config = ConfigDict(extra="forbid")


class ErrorResponseBody(BaseModel):
    """W09 :func:`format_error_response` envelope, HTTP-shaped."""

    error_code: str
    message: str
    trace_id: str | None = None

    model_config = ConfigDict(extra="forbid")


class HealthResponseBody(BaseModel):
    """``GET /healthz`` response."""

    status: str
    service: str = "egp-window"
    env: str

    model_config = ConfigDict(extra="forbid")


# ── Slice 1: thread pinning (B-002 + B-005) ───────────────────────────


class ThreadCreateRequest(BaseModel):
    """Body of ``POST /threads`` — open a new chat pinned to one patient."""

    patient_id: str = Field(..., min_length=1, max_length=128)
    # Slice 2: optional client-supplied title. If omitted, the API
    # auto-populates from the first user message on POST /chat.
    title: str | None = Field(default=None, max_length=200)

    model_config = ConfigDict(extra="forbid")


class ThreadCreateResponse(BaseModel):
    """Response of a successful ``POST /threads`` (HTTP 200)."""

    thread_id: str
    patient_id: str
    title: str | None = None
    created_at: datetime

    model_config = ConfigDict(extra="forbid")


class ThreadListItem(BaseModel):
    """One thread in the sidebar listing (``GET /threads``).

    Deliberately excludes ``messages`` — the sidebar shows the pinned
    ``patient_id``, ``title``, and last-activity timestamp only.
    Retrieving the full transcript is a separate endpoint (out of scope
    for Slice 2).
    """

    thread_id: str
    patient_id: str
    title: str | None = None
    last_activity: datetime

    model_config = ConfigDict(extra="forbid")


class ThreadListResponse(BaseModel):
    """Response of ``GET /threads``."""

    threads: list[ThreadListItem] = Field(default_factory=list)
    count: int = 0

    model_config = ConfigDict(extra="forbid")
