"""End-to-end W04 workflow smoke tests — chat + orchestration + fan-out.

Exercises real MAF :class:`WorkflowBuilder`-built workflows with stub
LLMs. Covers:

- Direct path (no clinical data) — chat_router → synthesize.
- Sequential 1-specialist path — chat_router → orch → prs stub → synth.
- Two-iteration path (prs then pgx, then end).
- Fan-out width-2 in parallel mode (Phase 3 preview, exercised via
  configuration override).
- Budget exceeded surfaces gracefully — final state still yielded.
"""

from __future__ import annotations

import os
from typing import Any

import pytest

from egp_maf.config.settings import DispatchMode, Settings
from egp_maf.state.clinician_context import ClinicianContext
from egp_maf.workflow.decisions import ChatRouterDecision, SpecialistDispatchSet
from egp_maf.workflow.router_llm import StubOrchRouterLlm, StubRouterLlm
from egp_maf.workflow.runtime import WorkflowRuntime
from egp_maf.workflow.state import ChatWorkflowState, SessionMessage

os.environ.setdefault("LLM_API_KEY", "test")


def _settings(**overrides: Any) -> Settings:
    return Settings(**overrides)  # type: ignore[call-arg]


def _state(**overrides: Any) -> ChatWorkflowState:
    base = ChatWorkflowState(
        ctx=ClinicianContext.system(),
        patient_id="P1",
        thread_id="T1",
        messages=[SessionMessage(role="user", content="what's the picture?")],
    )
    return base.model_copy(update=overrides)


async def _final_state(runtime: WorkflowRuntime, initial: ChatWorkflowState) -> ChatWorkflowState:
    result = await runtime.run_turn(initial)
    for out in result.get_outputs():
        if isinstance(out, ChatWorkflowState):
            return out
    raise AssertionError("Workflow yielded no ChatWorkflowState output")


class TestChatOnlyPath:
    async def test_no_clinical_data_short_circuits_to_synthesis(self) -> None:
        runtime = WorkflowRuntime(
            settings=_settings(),
            chat_router_llm=StubRouterLlm(
                ChatRouterDecision(needs_clinical_data=False, reason="cached")
            ),
            orch_router_llm=StubOrchRouterLlm([]),
        )
        final = await _final_state(runtime, _state())
        # Nothing dispatched.
        assert final.agents_completed == []
        # But the assistant still replies.
        assert final.messages[-1].role == "assistant"


class TestSequentialSinglePath:
    async def test_one_specialist_dispatched_and_completed(self) -> None:
        runtime = WorkflowRuntime(
            settings=_settings(),
            chat_router_llm=StubRouterLlm(
                ChatRouterDecision(needs_clinical_data=True, reason="need it")
            ),
            orch_router_llm=StubOrchRouterLlm(
                [
                    SpecialistDispatchSet(specialists=["prs"], reason="start"),
                    SpecialistDispatchSet(specialists=[], reason="done"),
                ]
            ),
        )
        final = await _final_state(runtime, _state())
        assert final.agents_completed == ["prs"]
        assert final.prs is not None and final.prs.status == "completed"
        assert final.prs.output is not None
        assert final.prs.output["specialist"] == "prs"


class TestSequentialMultipleIterations:
    async def test_two_specialists_across_two_iterations(self) -> None:
        runtime = WorkflowRuntime(
            settings=_settings(),
            chat_router_llm=StubRouterLlm(
                ChatRouterDecision(needs_clinical_data=True, reason="need it")
            ),
            orch_router_llm=StubOrchRouterLlm(
                [
                    SpecialistDispatchSet(specialists=["prs"], reason="prs first"),
                    SpecialistDispatchSet(specialists=["pgx"], reason="then pgx"),
                    SpecialistDispatchSet(specialists=[], reason="done"),
                ]
            ),
        )
        final = await _final_state(runtime, _state())
        assert final.agents_completed == ["pgx", "prs"]
        assert final.prs is not None
        assert final.pgx is not None


class TestFanoutWidthTwo:
    async def test_parallel_mode_completes_two_in_one_iteration(self) -> None:
        runtime = WorkflowRuntime(
            settings=_settings(
                ORCH_DISPATCH_MODE=DispatchMode.PARALLEL,
                ORCH_MAX_FANOUT_WIDTH=2,
            ),
            chat_router_llm=StubRouterLlm(
                ChatRouterDecision(needs_clinical_data=True, reason="need it")
            ),
            orch_router_llm=StubOrchRouterLlm(
                [
                    SpecialistDispatchSet(
                        specialists=["prs", "pgx"], reason="parallel"
                    ),
                    SpecialistDispatchSet(specialists=[], reason="done"),
                ]
            ),
        )
        final = await _final_state(runtime, _state())
        assert set(final.agents_completed) == {"prs", "pgx"}
        assert final.prs is not None
        assert final.pgx is not None


class TestBudgetExceededDegradesGracefully:
    async def test_run_orchestration_swallows_budget_error(self) -> None:
        # Budget=2, but router says "prs" three times → budget breach on the
        # second re-entry.
        runtime = WorkflowRuntime(
            settings=_settings(ORCH_ITERATION_BUDGET=2),
            chat_router_llm=StubRouterLlm(
                ChatRouterDecision(needs_clinical_data=True, reason="need it")
            ),
            orch_router_llm=StubOrchRouterLlm(
                [
                    SpecialistDispatchSet(specialists=["prs"], reason="i1"),
                    SpecialistDispatchSet(specialists=["pgx"], reason="i2"),
                    SpecialistDispatchSet(specialists=["family_history"], reason="i3"),
                ]
            ),
        )
        final = await _final_state(runtime, _state())
        # Workflow completed (didn't crash); some specialists may have
        # produced state before the budget was breached.
        assert final.messages[-1].role == "assistant"
