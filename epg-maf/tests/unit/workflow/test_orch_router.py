"""Tests for :class:`OrchRouterExecutor` — dispatch, termination,
budget, mode/width sanitisation."""

from __future__ import annotations

from typing import Any

import pytest

from egp_maf.config.settings import DispatchMode, Settings
from egp_maf.errors import RoutingBudgetExceeded
from egp_maf.state.clinician_context import ClinicianContext
from egp_maf.workflow.decisions import SpecialistDispatchSet
from egp_maf.workflow.orchestration.dispatcher import SpecialistDispatch
from egp_maf.workflow.orchestration.orch_router import OrchRouterExecutor
from egp_maf.workflow.router_llm import StubOrchRouterLlm
from egp_maf.workflow.state import OrchestrationWorkflowState


class CapturingContext:
    def __init__(self) -> None:
        self.sent: list[Any] = []
        self.yielded: list[Any] = []

    async def send_message(self, message: Any, target_id: str | None = None) -> None:
        self.sent.append(message)

    async def yield_output(self, output: Any) -> None:
        self.yielded.append(output)


def _settings(**overrides: Any) -> Settings:
    import os

    os.environ.setdefault("LLM_API_KEY", "test")
    return Settings(**overrides)  # type: ignore[call-arg]


def _state(**overrides: Any) -> OrchestrationWorkflowState:
    base = OrchestrationWorkflowState(
        ctx=ClinicianContext.system(),
        patient_id="P1",
        original_query="q",
    )
    return base.model_copy(update=overrides)


class TestOrchRouterDispatch:
    async def test_non_terminal_sends_dispatch_and_increments_counter(self) -> None:
        router = OrchRouterExecutor(
            router_llm=StubOrchRouterLlm(
                [SpecialistDispatchSet(specialists=["prs"], reason="start")]
            ),
            settings=_settings(),
        )
        ctx = CapturingContext()
        await router.handle_state(_state(), ctx)  # type: ignore[arg-type]
        assert len(ctx.sent) == 1
        assert isinstance(ctx.sent[0], SpecialistDispatch)
        assert ctx.sent[0].decision.specialists == ["prs"]
        assert ctx.sent[0].state.router_iterations == 1

    async def test_terminal_yields_output(self) -> None:
        router = OrchRouterExecutor(
            router_llm=StubOrchRouterLlm(
                [SpecialistDispatchSet(specialists=[], reason="done")]
            ),
            settings=_settings(),
        )
        ctx = CapturingContext()
        await router.handle_state(_state(agents_completed=["prs"]), ctx)  # type: ignore[arg-type]
        assert len(ctx.yielded) == 1
        assert isinstance(ctx.yielded[0], OrchestrationWorkflowState)
        assert ctx.yielded[0].agents_completed == ["prs"]
        assert ctx.sent == []


class TestOrchRouterBudget:
    async def test_budget_exceeded_raises(self) -> None:
        settings = _settings(ORCH_ITERATION_BUDGET=3)
        router = OrchRouterExecutor(
            router_llm=StubOrchRouterLlm(
                [SpecialistDispatchSet(specialists=["prs"], reason="loop")]
            ),
            settings=settings,
        )
        ctx = CapturingContext()
        state = _state(router_iterations=3)  # already at budget
        with pytest.raises(RoutingBudgetExceeded):
            await router.handle_state(state, ctx)  # type: ignore[arg-type]


class TestOrchRouterModeSanitisation:
    async def test_parallel_decision_downgraded_when_sequential_mode(self) -> None:
        router = OrchRouterExecutor(
            router_llm=StubOrchRouterLlm(
                [
                    SpecialistDispatchSet(
                        specialists=["prs", "pgx"], reason="parallel"
                    )
                ]
            ),
            settings=_settings(),
        )
        ctx = CapturingContext()
        await router.handle_state(_state(), ctx)  # type: ignore[arg-type]
        # Should have been downgraded to the first specialist only.
        assert ctx.sent[0].decision.specialists == ["prs"]

    async def test_parallel_decision_preserved_when_parallel_mode(self) -> None:
        settings = _settings(
            ORCH_DISPATCH_MODE=DispatchMode.PARALLEL,
            ORCH_MAX_FANOUT_WIDTH=5,
        )
        router = OrchRouterExecutor(
            router_llm=StubOrchRouterLlm(
                [
                    SpecialistDispatchSet(
                        specialists=["prs", "pgx"], reason="parallel"
                    )
                ]
            ),
            settings=settings,
        )
        ctx = CapturingContext()
        await router.handle_state(_state(), ctx)  # type: ignore[arg-type]
        assert ctx.sent[0].decision.specialists == ["prs", "pgx"]

    async def test_width_cap_applied_in_parallel_mode(self) -> None:
        settings = _settings(
            ORCH_DISPATCH_MODE=DispatchMode.PARALLEL,
            ORCH_MAX_FANOUT_WIDTH=2,
        )
        router = OrchRouterExecutor(
            router_llm=StubOrchRouterLlm(
                [
                    SpecialistDispatchSet(
                        specialists=["prs", "pgx", "family_history"],
                        reason="huge",
                    )
                ]
            ),
            settings=settings,
        )
        ctx = CapturingContext()
        await router.handle_state(_state(), ctx)  # type: ignore[arg-type]
        assert ctx.sent[0].decision.specialists == ["prs", "pgx"]
