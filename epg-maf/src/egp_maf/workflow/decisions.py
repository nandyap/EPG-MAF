"""Router decision types — Design §5.5, ADR-013.

- :class:`ChatRouterDecision` — output of the chat router LLM. Same shape
  as the prototype (``needs_clinical_data`` + ``reason`` + ``reset_agents``).
- :class:`SpecialistDispatchSet` — output of the orchestration router LLM.
  Phase 1 enforces ``|specialists| == 1`` when ``SEQUENTIAL_ONLY`` (the
  ``egp_maf.config.settings.DispatchMode.SEQUENTIAL`` mode); Phase 3 relaxes
  the size constraint. Type shape is set-of-specialists from day one so
  the fan-out plumbing needs no future re-typing.
"""

from __future__ import annotations

from typing import Literal, get_args

from pydantic import BaseModel, ConfigDict, Field, model_validator

# The 5 specialist identifiers as a typed alias — used by both decisions
# and the workflow state, keeping the vocabulary in one place.
SpecialistName = Literal[
    "prs",
    "genomic_variants",
    "family_history",
    "pgx",
    "phenotype",
]

ALL_SPECIALIST_NAMES: frozenset[str] = frozenset(get_args(SpecialistName))


class ChatRouterDecision(BaseModel):
    """Structured output of the chat router LLM (see prototype
    ``agents/chat/graph/graph.py::ChatRouterDecision``)."""

    needs_clinical_data: bool = Field(
        description=(
            "True when the latest user message requires fresh clinical "
            "data. False when the question can be answered from the "
            "existing conversation context."
        ),
    )
    reason: str = Field(
        description="One-sentence justification for this routing decision.",
    )
    reset_agents: list[SpecialistName] = Field(
        default_factory=list,
        description=(
            "Names of specialists whose cached results are stale and must "
            "be dropped before the orchestration re-runs. Populated when "
            "the query focus has shifted (e.g. different disease filter)."
        ),
    )

    model_config = ConfigDict(extra="forbid")


class SpecialistDispatchSet(BaseModel):
    """Structured output of the orchestration router — ADR-013.

    Phase 1 always emits ``|specialists| == 1`` (or ``0`` = end). Phase 3
    relaxes to ``|specialists| in {1..5}``. Validation of the width vs
    ``DispatchMode`` happens at the executor boundary because the mode is
    a runtime setting, not a schema constraint.
    """

    specialists: list[SpecialistName] = Field(
        default_factory=list,
        description=(
            "Specialists to dispatch this iteration. Empty list means "
            "the orchestrator is done."
        ),
    )
    reason: str = Field(
        description="One-sentence justification for this dispatch decision.",
    )
    requested_diseases: list[str] | None = Field(
        default=None,
        description=(
            "Optional disease filter to pass to each specialist. Populated "
            "when the query targets specific conditions."
        ),
    )

    model_config = ConfigDict(extra="forbid")

    @model_validator(mode="after")
    def _no_duplicates_in_set(self) -> "SpecialistDispatchSet":
        """The type says ``list`` but the semantics is a set — reject dups."""
        if len(self.specialists) != len(set(self.specialists)):
            raise ValueError(
                "SpecialistDispatchSet.specialists must be a set — "
                "duplicate specialist names are not allowed."
            )
        return self

    def is_terminal(self) -> bool:
        """Return True when this decision ends the orchestration loop."""
        return len(self.specialists) == 0
