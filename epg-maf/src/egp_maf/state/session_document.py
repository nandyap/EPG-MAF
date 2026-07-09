"""Session document schema — persisted in Cosmos DB per Design §13.2.

The document holds one clinician-patient conversation across turns. It
contains everything the chat workflow needs to resume mid-conversation:
messages, cached specialist outputs, completion tracking.

Specialist output types (``prs``, ``genomic_variants``, …) are held in the
``results`` mapping as opaque payloads for the foundation workstream. They
are typed strictly in the specialist workstream.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

CURRENT_SCHEMA_VERSION = 1


class SessionMessage(BaseModel):
    """One message in a session's conversation history."""

    role: Literal["user", "assistant", "system", "tool"]
    content: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    message_id: str | None = None

    model_config = ConfigDict(extra="forbid")


class SessionDocument(BaseModel):
    """Cosmos DB session document.

    Partition key is ``clinician_id``; item id is ``thread_id``.

    ``etag`` is populated by :class:`~egp_maf.services.thread_state.ThreadStateProvider`
    from the Cosmos response header and used for optimistic-concurrency writes.

    ``results`` holds the specialist state outputs. In the foundation
    workstream the values are typed as ``dict[str, Any]`` — the specialist
    workstream tightens this to concrete Pydantic models via a discriminated
    union.
    """

    # ── Identity ────────────────────────────────────────────────────
    schema_version: int = Field(default=CURRENT_SCHEMA_VERSION)
    thread_id: str
    clinician_id: str
    tenant_id: str
    patient_id: str
    clinician_specialty: str | None = None

    # ── Lifecycle ────────────────────────────────────────────────────
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    last_activity: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    ttl: int = 86400  # Cosmos native TTL — refreshed on save.

    # ── Conversation ─────────────────────────────────────────────────
    messages: list[SessionMessage] = Field(default_factory=list)

    # ── Specialist completion tracking ──────────────────────────────
    # Set semantics enforced by ThreadStateProvider on save (dedupe + sort).
    agents_completed: list[str] = Field(default_factory=list)

    # ── Specialist outputs (typed in the specialist workstream) ─────
    results: dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "One entry per specialist domain: 'prs', 'genomic_variants', "
            "'family_history', 'pgx', 'phenotype'. Values are typed in "
            "the specialist workstream."
        ),
    )

    # ── Cosmos metadata (set by ThreadStateProvider; NOT persisted directly) ──
    etag: str | None = Field(default=None, exclude=True)

    model_config = ConfigDict(
        extra="forbid",
        # We serialise datetimes as ISO 8601 strings for Cosmos.
        json_schema_extra={"cosmos_partition_key": "/clinician_id"},
    )

    # ── Convenience mutators (immutability by convention, not enforcement) ──
    def with_message(self, message: SessionMessage) -> "SessionDocument":
        """Return a copy with an appended message."""
        return self.model_copy(
            update={
                "messages": [*self.messages, message],
                "last_activity": datetime.now(timezone.utc),
            }
        )

    def with_agent_completed(self, agent_name: str) -> "SessionDocument":
        """Return a copy with ``agent_name`` added to ``agents_completed`` (set semantics)."""
        current = set(self.agents_completed)
        current.add(agent_name)
        return self.model_copy(
            update={
                "agents_completed": sorted(current),
                "last_activity": datetime.now(timezone.utc),
            }
        )

    def without_agent(self, agent_name: str) -> "SessionDocument":
        """Return a copy with the agent's cached output removed and its name
        stripped from ``agents_completed``. Used by the chat router when it
        emits a ``reset_agents`` decision.
        """
        new_results = {k: v for k, v in self.results.items() if k != agent_name}
        new_completed = [a for a in self.agents_completed if a != agent_name]
        return self.model_copy(
            update={
                "results": new_results,
                "agents_completed": new_completed,
                "last_activity": datetime.now(timezone.utc),
            }
        )
