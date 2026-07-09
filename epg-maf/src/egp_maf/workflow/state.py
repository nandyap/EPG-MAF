"""Workflow shared-state models + reducers.

Ports the prototype's ``ChatAgentState`` (agents/chat/state/state.py) and
``OrchestrationAgentState`` (agents/main/state/state.py) into Pydantic
models sized to sit on MAF ``WorkflowContext.state``.

Two additions vs the prototype (ADR-008 + ADR-009):

- ``ctx: ClinicianContext`` is required, not optional.
- ``agents_completed`` gets a **list-append set reducer** with a ``Remove``
  sentinel; every mutation goes through :func:`apply_agents_completed`.

Specialist slots (``prs``, ``genomic_variants`` …) hold a small
:class:`SpecialistSlot` envelope in W04. W05 will tighten the ``output``
type to concrete Pydantic models per domain.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from egp_maf.state.clinician_context import ClinicianContext

# ── Specialist identifiers (5, per prototype) ────────────────────────
_SPECIALIST_NAMES: frozenset[str] = frozenset(
    {"prs", "genomic_variants", "family_history", "pgx", "phenotype"}
)


class Remove(BaseModel):
    """Sentinel signalling that a specialist name should be dropped from
    ``agents_completed`` (used by the chat router when it resets cached
    results — Design ADR-009 §"Cache invalidation")."""

    name: str

    model_config = ConfigDict(frozen=True, extra="forbid")


class SpecialistSlot(BaseModel):
    """One specialist's contribution to shared state.

    W04 keeps ``output`` typed as ``dict[str, Any] | None``. W05 tightens
    it into a per-domain discriminated union of ``<Domain>StateOutput``s.
    ``errors`` mirrors the prototype's ``<Domain>StateOutput.errors`` field.
    """

    status: Literal["pending", "running", "completed", "failed"] = "pending"
    output: dict[str, Any] | None = None
    errors: list[str] = Field(default_factory=list)
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )

    model_config = ConfigDict(extra="forbid")

    @classmethod
    def completed_with(cls, output: dict[str, Any]) -> "SpecialistSlot":
        return cls(status="completed", output=output)

    @classmethod
    def failed_with(cls, error: str) -> "SpecialistSlot":
        return cls(status="failed", errors=[error])


class SessionMessage(BaseModel):
    """Conversation message — ports prototype ``BaseMessage`` shape to a
    minimal role/content pair suitable for the workflow's shared state.

    The chat router sees the raw list; the synthesizer strips provenance
    from clinical context before assembling the LLM prompt.
    """

    role: Literal["user", "assistant", "system", "tool"]
    content: str
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )

    model_config = ConfigDict(extra="forbid")


class ChatWorkflowState(BaseModel):
    """Chat workflow's shared state — one instance per turn.

    Persists across turns via :class:`~egp_maf.services.thread_state.ThreadStateProvider`
    (Cosmos), rehydrated from :class:`SessionDocument` at start of turn.
    """

    # ── Session identity ────────────────────────────────────────────
    ctx: ClinicianContext
    patient_id: str
    thread_id: str
    conversation_id: str | None = None
    clinician_specialty: str | None = None

    # ── Current turn ────────────────────────────────────────────────
    original_query: str = ""
    next_action: Literal["run_orchestration", "respond_directly", ""] = ""

    # ── Optional query-scoped filters ───────────────────────────────
    requested_diseases: list[str] | None = None
    requested_genes: list[str] | None = None

    # ── Conversation ────────────────────────────────────────────────
    messages: list[SessionMessage] = Field(default_factory=list)

    # ── Specialist slots ────────────────────────────────────────────
    prs: SpecialistSlot | None = None
    genomic_variants: SpecialistSlot | None = None
    family_history: SpecialistSlot | None = None
    pgx: SpecialistSlot | None = None
    phenotype: SpecialistSlot | None = None

    # ── Completion tracking (managed via apply_agents_completed) ────
    agents_completed: list[str] = Field(default_factory=list)

    model_config = ConfigDict(extra="forbid")


class OrchestrationWorkflowState(BaseModel):
    """Orchestration sub-workflow shared state.

    Constructed by the chat workflow's :class:`RunOrchestrationExecutor`
    from the outer :class:`ChatWorkflowState`. The two states carry the
    same specialist slots so results merge back cleanly on completion.
    """

    # ── Session identity ────────────────────────────────────────────
    ctx: ClinicianContext
    patient_id: str
    original_query: str
    conversation_id: str | None = None
    clinician_specialty: str | None = None

    # ── Query-scoped filters (may be tightened by orch_router) ──────
    requested_diseases: list[str] | None = None
    requested_genes: list[str] | None = None

    # ── Specialist slots (mirror ChatWorkflowState) ─────────────────
    prs: SpecialistSlot | None = None
    genomic_variants: SpecialistSlot | None = None
    family_history: SpecialistSlot | None = None
    pgx: SpecialistSlot | None = None
    phenotype: SpecialistSlot | None = None

    # ── Completion tracking ─────────────────────────────────────────
    agents_completed: list[str] = Field(default_factory=list)

    # ── Router loop counter (checked against iteration budget) ──────
    router_iterations: int = 0

    model_config = ConfigDict(extra="forbid")


# ── Reducers ─────────────────────────────────────────────────────────


def apply_agents_completed(
    current: list[str],
    delta: str | Remove | list[str | Remove],
) -> list[str]:
    """Set-append reducer for ``agents_completed`` — Design ADR-009.

    - Adding an already-present name is a no-op (set semantics).
    - :class:`Remove` drops the named specialist (used by chat router's
      ``reset_agents`` decision).
    - Deterministic sort keeps checkpoints byte-stable across replays.
    """
    ordered: list[str | Remove] = (
        [delta] if isinstance(delta, (str, Remove)) else list(delta)
    )
    current_set: set[str] = set(current)
    for item in ordered:
        if isinstance(item, Remove):
            current_set.discard(item.name)
        else:
            if item not in _SPECIALIST_NAMES:
                raise ValueError(
                    f"Unknown specialist name {item!r}. "
                    f"Expected one of {sorted(_SPECIALIST_NAMES)}."
                )
            current_set.add(item)
    return sorted(current_set)


def apply_specialist_slot(
    current: SpecialistSlot | None,
    delta: SpecialistSlot,
) -> SpecialistSlot:
    """Overwrite reducer for a specialist slot.

    Chosen deliberately: the prototype semantics is "the last write wins";
    the specialist runs to completion inside a single executor, so there's
    no partial-merge case to handle in W04.
    """
    return delta
