"""Fan-out dispatcher + fan-in joiner for the orchestration sub-workflow.

Two executors here:

- :class:`SpecialistDispatcherExecutor` — receives the router's decision,
  re-broadcasts it to every specialist stub via fan-out. In Phase 1 the
  decision always contains ≤1 specialist name; each stub decides
  whether the name is theirs (see
  :class:`~egp_maf.workflow.orchestration.specialist_stub.SpecialistPlaceholderExecutor`).
  The specialist stubs that aren't selected simply pass state through
  so the fan-in barrier completes deterministically.
- :class:`SpecialistJoinerExecutor` — merges the up-to-5 branch outputs
  back into a single :class:`OrchestrationWorkflowState` (deterministic
  reduction across all specialist slots + ``agents_completed``) and
  forwards to ``orch_router`` for the next iteration.

The wire uses a small :class:`SpecialistDispatch` envelope (state +
decision) so downstream executors don't need out-of-band state.
"""

from __future__ import annotations

from typing import Any

from agent_framework import Executor, WorkflowContext, handler
from pydantic import BaseModel, ConfigDict

from egp_maf.logging.setup import get_logger
from egp_maf.workflow.decisions import SpecialistDispatchSet
from egp_maf.workflow.state import (
    OrchestrationWorkflowState,
    SpecialistSlot,
    apply_agents_completed,
)

_logger = get_logger(__name__)

_SPECIALIST_SLOTS = (
    "prs",
    "genomic_variants",
    "family_history",
    "pgx",
    "phenotype",
)


class SpecialistDispatch(BaseModel):
    """Envelope carried on the wire from :class:`OrchRouterExecutor`
    through the fan-out to each specialist stub."""

    state: OrchestrationWorkflowState
    decision: SpecialistDispatchSet

    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)


class SpecialistDispatcherExecutor(Executor):
    """Executor id: ``specialist_dispatcher``.

    Trivial pass-through — the point of this executor is to be the
    single MAF ``source`` for the fan-out edge group. Fan-out semantics
    (broadcast the same message to all targets) mean each specialist
    stub sees the identical :class:`SpecialistDispatch`.
    """

    def __init__(self, *, executor_id: str = "specialist_dispatcher") -> None:
        super().__init__(id=executor_id)

    @handler
    async def handle_dispatch(
        self,
        message: SpecialistDispatch,
        ctx: WorkflowContext[SpecialistDispatch],
    ) -> None:
        await ctx.send_message(message)


class SpecialistJoinerExecutor(Executor):
    """Executor id: ``specialist_joiner``.

    Fan-in barrier. Receives a list of :class:`OrchestrationWorkflowState`s
    (one per specialist stub) and merges them into a single state before
    forwarding to :class:`OrchRouterExecutor` for the next iteration.

    Determinism: specialist slots and ``agents_completed`` are the only
    mutating fields; both are combined via the reducers defined in
    :mod:`egp_maf.workflow.state`, so completion order is irrelevant.
    """

    def __init__(self, *, executor_id: str = "specialist_joiner") -> None:
        super().__init__(id=executor_id)

    @handler
    async def handle_branch_outputs(
        self,
        message: list[OrchestrationWorkflowState],
        ctx: WorkflowContext[OrchestrationWorkflowState],
    ) -> None:
        if not message:
            _logger.warning("specialist_joiner.empty_fanin")
            return

        base = message[0]
        merged_completed: list[str] = list(base.agents_completed)
        merged_slots: dict[str, Any] = {}

        for branch in message[1:]:
            merged_completed = apply_agents_completed(
                merged_completed,
                list(branch.agents_completed),
            )

        # Slot merge: for each slot name take the "last non-None writer"
        # semantics from the branch that actually wrote it (a specialist
        # that wasn't selected in this iteration will have left its slot
        # unchanged from the router-forwarded value).
        for name in _SPECIALIST_SLOTS:
            for branch in message:
                slot = getattr(branch, name)
                if isinstance(slot, SpecialistSlot):
                    merged_slots[name] = slot

        merged = base.model_copy(
            update={
                "agents_completed": merged_completed,
                **merged_slots,
            }
        )
        _logger.info(
            "specialist_joiner.merged",
            branch_count=len(message),
            agents_completed=merged_completed,
        )
        await ctx.send_message(merged)
