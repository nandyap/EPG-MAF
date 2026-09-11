"""Run the real workflow with tracing ON.

`test_flow_trace.py` covers the helper in isolation. This covers the
thing that actually broke: **argument expressions at the call sites**.

Those are evaluated before ``trace`` is entered, so the helper's
try/except cannot catch them. A wrong attribute access inside a
``trace(...)`` argument raises inside a workflow handler and fails the
turn. Exactly that happened while writing this instrumentation —
``specialists=[s.specialist for s in ...]`` against a ``list[str]``
turned twelve passing end-to-end tests red.

Every other test in the suite runs with tracing off, which is the
default, so none of them execute a single trace call site. Without this
file the instrumentation would ship untested and the first thing to
exercise it would be a clinical turn in the deployed environment.

Mirrors the paths in ``tests/unit/workflow/test_end_to_end.py`` and
asserts the same outcomes. If tracing is inert, as intended, these
assertions hold identically with the flags on.
"""

from __future__ import annotations

import os
from typing import Any

import pytest

from egp_maf.config.settings import DispatchMode, Settings
from egp_maf.logging import flow_trace
from egp_maf.logging.flow_trace import configure_flow_trace
from egp_maf.state.clinician_context import ClinicianContext
from egp_maf.workflow.decisions import ChatRouterDecision, SpecialistDispatchSet
from egp_maf.workflow.router_llm import StubOrchRouterLlm, StubRouterLlm
from egp_maf.workflow.runtime import WorkflowRuntime
from egp_maf.workflow.state import ChatWorkflowState, SessionMessage

os.environ.setdefault("LLM_API_KEY", "test")

pytestmark = pytest.mark.unit


class _TraceSettings:
    trace_flow = True
    trace_payloads = True


@pytest.fixture
def tracing_on():
    """Both flags on — payload tracing exercises the widest set of call
    sites, including the ``preview``/``summarise_messages`` arguments."""
    before = (flow_trace._flow_enabled, flow_trace._payloads_enabled)  # noqa: SLF001
    configure_flow_trace(_TraceSettings())
    yield
    (
        flow_trace._flow_enabled,  # noqa: SLF001
        flow_trace._payloads_enabled,  # noqa: SLF001
    ) = before


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


async def _final_state(
    runtime: WorkflowRuntime, initial: ChatWorkflowState
) -> ChatWorkflowState:
    result = await runtime.run_turn(initial)
    for out in result.get_outputs():
        if isinstance(out, ChatWorkflowState):
            return out
    raise AssertionError("Workflow yielded no ChatWorkflowState output")


class TestWorkflowSurvivesTracing:
    async def test_direct_path(self, tracing_on) -> None:
        """chat_router → synthesize, no orchestration."""
        runtime = WorkflowRuntime(
            settings=_settings(),
            chat_router_llm=StubRouterLlm(
                ChatRouterDecision(needs_clinical_data=False, reason="cached")
            ),
            orch_router_llm=StubOrchRouterLlm([]),
        )

        final = await _final_state(runtime, _state())

        assert final.messages[-1].role == "assistant"

    async def test_single_specialist_path(self, tracing_on) -> None:
        """The path through the dispatcher fan-out — where the bug was."""
        runtime = WorkflowRuntime(
            settings=_settings(),
            chat_router_llm=StubRouterLlm(
                ChatRouterDecision(needs_clinical_data=True, reason="needs data")
            ),
            orch_router_llm=StubOrchRouterLlm(
                [
                    SpecialistDispatchSet(specialists=["prs"], reason="prs"),
                    SpecialistDispatchSet(specialists=[], reason="done"),
                ]
            ),
        )

        final = await _final_state(runtime, _state())

        assert "prs" in final.agents_completed

    async def test_two_iterations(self, tracing_on) -> None:
        """Two dispatch loops — traces the router twice and the joiner twice."""
        runtime = WorkflowRuntime(
            settings=_settings(),
            chat_router_llm=StubRouterLlm(
                ChatRouterDecision(needs_clinical_data=True, reason="needs data")
            ),
            orch_router_llm=StubOrchRouterLlm(
                [
                    SpecialistDispatchSet(specialists=["prs"], reason="prs"),
                    SpecialistDispatchSet(specialists=["pgx"], reason="pgx"),
                    SpecialistDispatchSet(specialists=[], reason="done"),
                ]
            ),
        )

        final = await _final_state(runtime, _state())

        assert "prs" in final.agents_completed
        assert "pgx" in final.agents_completed

    async def test_parallel_fanout(self, tracing_on) -> None:
        """Fan-out width 2 — two specialists traced concurrently.

        Worth covering separately: concurrent trace emission shares the
        contextvars bound for the turn.

        Note the alias spellings. ``Settings`` is ``extra="ignore"``, so
        passing the snake_case field names here is silently discarded and
        the test runs in sequential mode while appearing to assert on
        parallel — which is how this test first passed for the wrong
        reason.
        """
        runtime = WorkflowRuntime(
            settings=_settings(
                ORCH_DISPATCH_MODE=DispatchMode.PARALLEL,
                ORCH_MAX_FANOUT_WIDTH=2,
            ),
            chat_router_llm=StubRouterLlm(
                ChatRouterDecision(needs_clinical_data=True, reason="needs data")
            ),
            orch_router_llm=StubOrchRouterLlm(
                [
                    SpecialistDispatchSet(
                        specialists=["prs", "pgx"], reason="both"
                    ),
                    SpecialistDispatchSet(specialists=[], reason="done"),
                ]
            ),
        )

        final = await _final_state(runtime, _state())

        assert "prs" in final.agents_completed
        assert "pgx" in final.agents_completed
