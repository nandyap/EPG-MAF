"""F11.5 — Specialist-failure isolation.

An exception raised inside a specialist's :meth:`run` must:

1. Not stop other specialists in the same orchestration turn.
2. Materialise as a :class:`SpecialistSlot` with ``status='failed'`` and
   ``errors`` populated (the failed slot is what synthesis reads).
3. Emit :meth:`MetricEmitter.emit_specialist_failed` with the domain +
   error class.
4. Still emit :meth:`MetricEmitter.emit_specialist` for the terminal
   status so latency dashboards remain accurate.

We test at two levels:

- Direct: call :meth:`SpecialistExecutor.handle_dispatch` with a mock
  workflow context and a specialist that raises.
- End-to-end: run the full :class:`WorkflowRuntime` with one failing
  specialist and one succeeding specialist to prove the workflow does
  not abort.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any
from unittest.mock import MagicMock

import pytest

from egp_maf.agents.base import (
    SpecialistBase,
    SpecialistInputs,
    SpecialistLlm,
    SpecialistReactResult,
)
from egp_maf.agents.family_history import FamilyHistorySpecialist
from egp_maf.agents.genomic_variants import GenomicVariantsSpecialist
from egp_maf.agents.llm_bridge import StubSpecialistLlm
from egp_maf.agents.pgx import PGXSpecialist
from egp_maf.agents.phenotype import PhenotypeSpecialist
from egp_maf.agents.prs import PRSSpecialist
from egp_maf.agents.registry import SpecialistRegistry
from egp_maf.config.settings import Settings
from egp_maf.services.provenance import ProvenanceService
from egp_maf.state.clinician_context import ClinicianContext
from egp_maf.state.results.family_history import FamilyHistoryResultList
from egp_maf.state.results.genomic_variants import GenomicVariantsResultList
from egp_maf.state.results.pgx import PGXResultList
from egp_maf.state.results.phenotype import PhenotypeResultList
from egp_maf.state.results.prs import PRSResult, PRSResultList
from egp_maf.telemetry.metrics import NullMetricEmitter
from egp_maf.workflow.decisions import ChatRouterDecision, SpecialistDispatchSet
from egp_maf.workflow.orchestration.dispatcher import SpecialistDispatch
from egp_maf.workflow.orchestration.specialist_executor import SpecialistExecutor
from egp_maf.workflow.router_llm import StubOrchRouterLlm, StubRouterLlm
from egp_maf.workflow.runtime import WorkflowRuntime
from egp_maf.workflow.state import (
    ChatWorkflowState,
    OrchestrationWorkflowState,
    SessionMessage,
)

pytestmark = pytest.mark.unit

os.environ.setdefault("LLM_API_KEY", "test")


# ── Test doubles ────────────────────────────────────────────────────


@dataclass
class _RecordingMetrics(NullMetricEmitter):
    specialists: list[tuple[str, str, int]] = field(default_factory=list)
    failures: list[tuple[str, str]] = field(default_factory=list)

    def emit_specialist(  # type: ignore[override]
        self, *, domain: str, status: str, duration_ms: int
    ) -> None:
        self.specialists.append((domain, status, duration_ms))

    def emit_specialist_failed(  # type: ignore[override]
        self, *, domain: str, error_class: str
    ) -> None:
        self.failures.append((domain, error_class))


class _ExplodingSpecialist(PRSSpecialist):
    """Subclass a real specialist and override :meth:`run` to raise.

    Subclassing keeps the abstract-method contract satisfied while still
    letting us prove the executor catches whatever :meth:`run` raises.
    """

    def __init__(self) -> None:
        super().__init__(
            system_prompt="",
            interpretation_model_name="m",
            repository=MagicMock(),
            provenance_service=ProvenanceService(),
        )
        self.calls = 0

    async def run(  # type: ignore[override]
        self,
        *,
        inputs: SpecialistInputs,
        ctx: Any,
        llm: SpecialistLlm,
    ) -> Any:
        self.calls += 1
        raise RuntimeError("simulated specialist crash")


@dataclass
class _CtxStub:
    sent: list[Any] = field(default_factory=list)

    async def send_message(self, message: Any) -> None:
        self.sent.append(message)


def _make_state() -> OrchestrationWorkflowState:
    return OrchestrationWorkflowState(
        ctx=ClinicianContext.system(),
        patient_id="P1",
        original_query="test",
    )


# ── Direct handler tests ───────────────────────────────────────────


class TestSpecialistExecutorIsolation:
    async def test_handler_catches_run_exception_and_marks_failed(self) -> None:
        specialist = _ExplodingSpecialist()
        metrics = _RecordingMetrics()
        executor = SpecialistExecutor(
            specialist=specialist,
            llm=StubSpecialistLlm(
                react_result=SpecialistReactResult(transcript=[], tool_calls=[]),
                extraction_result=PRSResultList(results=[]),
            ),
            metric_emitter=metrics,
        )
        state = _make_state()
        message = SpecialistDispatch(
            state=state,
            decision=SpecialistDispatchSet(specialists=["prs"], reason="test"),
        )
        ctx = _CtxStub()

        # Must not raise — isolation is the whole point.
        await executor.handle_dispatch(message, ctx)  # type: ignore[arg-type]

        # One state message forwarded downstream with a failed slot.
        assert len(ctx.sent) == 1
        forwarded = ctx.sent[0]
        assert forwarded.prs is not None
        assert forwarded.prs.status == "failed"
        assert forwarded.prs.output is None
        assert any("RuntimeError" in e for e in forwarded.prs.errors)
        assert "prs" in forwarded.agents_completed

        # Metrics: one specialist-run + one specialist-failed emission.
        assert metrics.failures == [("prs", "RuntimeError")]
        assert len(metrics.specialists) == 1
        domain, status, _duration = metrics.specialists[0]
        assert (domain, status) == ("prs", "failed")

    async def test_unselected_specialist_forwards_state_untouched(self) -> None:
        specialist = _ExplodingSpecialist()
        metrics = _RecordingMetrics()
        executor = SpecialistExecutor(
            specialist=specialist,
            llm=StubSpecialistLlm(
                react_result=SpecialistReactResult(transcript=[], tool_calls=[]),
                extraction_result=PRSResultList(results=[]),
            ),
            metric_emitter=metrics,
        )
        state = _make_state()
        message = SpecialistDispatch(
            state=state,
            decision=SpecialistDispatchSet(specialists=["pgx"], reason="not us"),
        )
        ctx = _CtxStub()
        await executor.handle_dispatch(message, ctx)  # type: ignore[arg-type]

        assert specialist.calls == 0  # never invoked
        assert metrics.failures == []
        assert metrics.specialists == []
        assert ctx.sent == [state]  # forwarded verbatim


# ── End-to-end isolation ───────────────────────────────────────────


def _build_registry_with_one_exploding_specialist() -> SpecialistRegistry:
    """PRS explodes; the other four return empty result lists."""
    provenance = ProvenanceService()
    registry = SpecialistRegistry()

    registry.specialists["prs"] = _ExplodingSpecialist()
    registry.specialists["genomic_variants"] = GenomicVariantsSpecialist(
        system_prompt="",
        interpretation_model_name="m",
        repository=MagicMock(),
        provenance_service=provenance,
    )
    registry.specialists["family_history"] = FamilyHistorySpecialist(
        system_prompt="",
        interpretation_model_name="m",
        repository=MagicMock(),
        provenance_service=provenance,
    )
    registry.specialists["pgx"] = PGXSpecialist(
        system_prompt="",
        interpretation_model_name="m",
        repository=MagicMock(),
        provenance_service=provenance,
    )
    registry.specialists["phenotype"] = PhenotypeSpecialist(
        system_prompt="",
        interpretation_model_name="m",
        repository=MagicMock(),
        provenance_service=provenance,
    )

    for name, empty in [
        ("prs", PRSResultList(results=[])),
        ("genomic_variants", GenomicVariantsResultList(patient_id="", results=[])),
        ("family_history", FamilyHistoryResultList(patient_id="", results=[])),
        ("pgx", PGXResultList(patient_id="", results=[])),
        ("phenotype", PhenotypeResultList(patient_id="", results=[])),
    ]:
        registry.llms[name] = StubSpecialistLlm(
            react_result=SpecialistReactResult(transcript=[], tool_calls=[]),
            extraction_result=empty,
        )
    return registry


class TestEndToEndIsolation:
    async def test_failing_specialist_does_not_stop_the_workflow(self) -> None:
        registry = _build_registry_with_one_exploding_specialist()
        metrics = _RecordingMetrics()
        runtime = WorkflowRuntime(
            settings=Settings(),  # type: ignore[call-arg]
            chat_router_llm=StubRouterLlm(
                ChatRouterDecision(needs_clinical_data=True, reason="need data")
            ),
            orch_router_llm=StubOrchRouterLlm(
                [
                    SpecialistDispatchSet(specialists=["prs"], reason="prs explodes"),
                    SpecialistDispatchSet(specialists=["pgx"], reason="then pgx"),
                    SpecialistDispatchSet(specialists=[], reason="done"),
                ]
            ),
            specialist_registry=registry,
            metric_emitter=metrics,
        )
        result = await runtime.run_turn(
            ChatWorkflowState(
                ctx=ClinicianContext.system(),
                patient_id="P1",
                thread_id="T-iso",
                messages=[SessionMessage(role="user", content="q")],
            )
        )
        outputs = result.get_outputs()
        final = next(o for o in outputs if isinstance(o, ChatWorkflowState))

        # PRS failed but PGX still completed.
        assert final.prs is not None
        assert final.prs.status == "failed"
        assert final.pgx is not None
        assert final.pgx.status == "completed"

        # The failure was reported to the metric emitter.
        assert ("prs", "RuntimeError") in metrics.failures
