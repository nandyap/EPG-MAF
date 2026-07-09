"""Chat-router executor test — verifies the state mutations produced by
each router decision path.

Uses a tiny :class:`CapturingContext` stand-in for ``WorkflowContext`` so
we can drive the executor's handler directly, without spinning a full
:class:`Workflow`. End-to-end wiring is exercised in
:mod:`tests.unit.workflow.test_end_to_end_stub`.
"""

from __future__ import annotations

from typing import Any

import pytest

from egp_maf.state.clinician_context import ClinicianContext
from egp_maf.workflow.chat.chat_router import ChatRouterExecutor
from egp_maf.workflow.decisions import ChatRouterDecision
from egp_maf.workflow.router_llm import StubRouterLlm
from egp_maf.workflow.state import (
    ChatWorkflowState,
    SessionMessage,
    SpecialistSlot,
)


class CapturingContext:
    """Minimal stand-in for ``WorkflowContext`` — captures sent messages."""

    def __init__(self) -> None:
        self.sent: list[Any] = []

    async def send_message(self, message: Any, target_id: str | None = None) -> None:
        self.sent.append(message)


def _initial_state(**overrides: Any) -> ChatWorkflowState:
    base = ChatWorkflowState(
        ctx=ClinicianContext.system(),
        patient_id="P1",
        thread_id="T1",
        messages=[SessionMessage(role="user", content="What is my PRS?")],
    )
    return base.model_copy(update=overrides)


class TestChatRouterExecutor:
    async def test_extracts_latest_user_message_into_original_query(self) -> None:
        exec_ = ChatRouterExecutor(
            router_llm=StubRouterLlm(
                ChatRouterDecision(needs_clinical_data=True, reason="need it")
            )
        )
        ctx = CapturingContext()
        await exec_.handle_state(_initial_state(), ctx)  # type: ignore[arg-type]
        assert len(ctx.sent) == 1
        assert isinstance(ctx.sent[0], ChatWorkflowState)
        assert ctx.sent[0].original_query == "What is my PRS?"

    async def test_routes_to_orchestration_when_data_needed(self) -> None:
        exec_ = ChatRouterExecutor(
            router_llm=StubRouterLlm(
                ChatRouterDecision(needs_clinical_data=True, reason="need it")
            )
        )
        ctx = CapturingContext()
        await exec_.handle_state(_initial_state(), ctx)  # type: ignore[arg-type]
        assert ctx.sent[0].next_action == "run_orchestration"

    async def test_routes_directly_when_no_new_data_needed(self) -> None:
        exec_ = ChatRouterExecutor(
            router_llm=StubRouterLlm(
                ChatRouterDecision(needs_clinical_data=False, reason="cached")
            )
        )
        ctx = CapturingContext()
        await exec_.handle_state(_initial_state(), ctx)  # type: ignore[arg-type]
        assert ctx.sent[0].next_action == "respond_directly"

    async def test_reset_agents_drops_cache_and_agents_completed(self) -> None:
        exec_ = ChatRouterExecutor(
            router_llm=StubRouterLlm(
                ChatRouterDecision(
                    needs_clinical_data=True,
                    reason="disease changed",
                    reset_agents=["prs"],
                )
            )
        )
        initial = _initial_state(
            prs=SpecialistSlot.completed_with({"specialist": "prs"}),
            pgx=SpecialistSlot.completed_with({"specialist": "pgx"}),
            agents_completed=["pgx", "prs"],
        )
        ctx = CapturingContext()
        await exec_.handle_state(initial, ctx)  # type: ignore[arg-type]
        out = ctx.sent[0]
        assert out.prs is None
        assert out.pgx is not None  # untouched
        assert out.agents_completed == ["pgx"]
