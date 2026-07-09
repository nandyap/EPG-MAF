"""Tests for the specialist placeholder + dispatcher/joiner executors."""

from __future__ import annotations

from typing import Any

from egp_maf.state.clinician_context import ClinicianContext
from egp_maf.workflow.decisions import SpecialistDispatchSet
from egp_maf.workflow.orchestration.dispatcher import (
    SpecialistDispatch,
    SpecialistDispatcherExecutor,
    SpecialistJoinerExecutor,
)
from egp_maf.workflow.orchestration.specialist_stub import (
    SpecialistPlaceholderExecutor,
)
from egp_maf.workflow.state import (
    OrchestrationWorkflowState,
    SpecialistSlot,
)


class CapturingContext:
    def __init__(self) -> None:
        self.sent: list[Any] = []

    async def send_message(self, message: Any, target_id: str | None = None) -> None:
        self.sent.append(message)


def _state(**overrides: Any) -> OrchestrationWorkflowState:
    base = OrchestrationWorkflowState(
        ctx=ClinicianContext.system(),
        patient_id="P1",
        original_query="q",
    )
    return base.model_copy(update=overrides)


class TestSpecialistPlaceholderExecutor:
    async def test_activates_when_named_in_decision(self) -> None:
        stub = SpecialistPlaceholderExecutor(name="prs")
        ctx = CapturingContext()
        await stub.handle_dispatch(
            SpecialistDispatch(
                state=_state(),
                decision=SpecialistDispatchSet(specialists=["prs"], reason="go"),
            ),
            ctx,  # type: ignore[arg-type]
        )
        assert len(ctx.sent) == 1
        out = ctx.sent[0]
        assert isinstance(out, OrchestrationWorkflowState)
        assert out.prs is not None
        assert out.prs.status == "completed"
        assert out.prs.output is not None
        assert out.prs.output["specialist"] == "prs"
        assert out.agents_completed == ["prs"]

    async def test_passes_through_when_not_named(self) -> None:
        stub = SpecialistPlaceholderExecutor(name="pgx")
        ctx = CapturingContext()
        state = _state()
        await stub.handle_dispatch(
            SpecialistDispatch(
                state=state,
                decision=SpecialistDispatchSet(specialists=["prs"], reason="go"),
            ),
            ctx,  # type: ignore[arg-type]
        )
        assert len(ctx.sent) == 1
        # State forwarded unchanged.
        assert ctx.sent[0] is state

    async def test_forwards_requested_diseases_into_payload(self) -> None:
        stub = SpecialistPlaceholderExecutor(name="phenotype")
        ctx = CapturingContext()
        await stub.handle_dispatch(
            SpecialistDispatch(
                state=_state(),
                decision=SpecialistDispatchSet(
                    specialists=["phenotype"],
                    reason="filter",
                    requested_diseases=["Alzheimer's disease"],
                ),
            ),
            ctx,  # type: ignore[arg-type]
        )
        assert ctx.sent[0].phenotype.output["requested_diseases"] == [
            "Alzheimer's disease"
        ]


class TestSpecialistDispatcherExecutor:
    async def test_pass_through(self) -> None:
        d = SpecialistDispatcherExecutor()
        ctx = CapturingContext()
        message = SpecialistDispatch(
            state=_state(),
            decision=SpecialistDispatchSet(specialists=["prs"], reason="go"),
        )
        await d.handle_dispatch(message, ctx)  # type: ignore[arg-type]
        assert ctx.sent == [message]


class TestSpecialistJoinerExecutor:
    async def test_merges_slots_from_active_branch(self) -> None:
        j = SpecialistJoinerExecutor()
        # 5 branches: PRS produced a slot, others passed through.
        prs_branch = _state(
            prs=SpecialistSlot.completed_with({"specialist": "prs"}),
            agents_completed=["prs"],
        )
        others = [_state() for _ in range(4)]
        ctx = CapturingContext()
        await j.handle_branch_outputs([prs_branch, *others], ctx)  # type: ignore[arg-type]
        assert len(ctx.sent) == 1
        merged = ctx.sent[0]
        assert merged.prs is not None
        assert merged.pgx is None
        assert merged.agents_completed == ["prs"]

    async def test_merges_agents_completed_across_branches(self) -> None:
        j = SpecialistJoinerExecutor()
        b1 = _state(
            prs=SpecialistSlot.completed_with({"specialist": "prs"}),
            agents_completed=["prs"],
        )
        b2 = _state(
            pgx=SpecialistSlot.completed_with({"specialist": "pgx"}),
            agents_completed=["pgx"],
        )
        ctx = CapturingContext()
        await j.handle_branch_outputs([b1, b2], ctx)  # type: ignore[arg-type]
        merged = ctx.sent[0]
        assert merged.agents_completed == ["pgx", "prs"]
        assert merged.prs is not None
        assert merged.pgx is not None
