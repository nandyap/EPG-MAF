"""Executor that plugs a real :class:`SpecialistBase` into the workflow.

Replaces W04's :class:`SpecialistPlaceholderExecutor` for production
runs. When the current :class:`SpecialistDispatchSet` names this
executor's specialist, it runs the full 10-step pipeline via
:meth:`SpecialistBase.run` and writes the produced
:class:`SpecialistSlotOutput` into the workflow's
:class:`SpecialistSlot`. Otherwise it passes state through so the fan-in
barrier can complete.
"""

from __future__ import annotations

from datetime import datetime, timezone

from agent_framework import Executor, WorkflowContext, handler

from egp_maf.agents.base import SpecialistBase, SpecialistInputs, SpecialistLlm
from egp_maf.logging.setup import get_logger
from egp_maf.telemetry import specialist_span
from egp_maf.telemetry.metrics import MetricEmitter, NullMetricEmitter
from egp_maf.workflow.decisions import SpecialistName
from egp_maf.workflow.orchestration.dispatcher import SpecialistDispatch
from egp_maf.workflow.state import (
    OrchestrationWorkflowState,
    SpecialistSlot,
    apply_agents_completed,
)

_logger = get_logger(__name__)


class SpecialistExecutor(Executor):
    """Production replacement for :class:`SpecialistPlaceholderExecutor`.

    One instance per specialist name. Bound to a :class:`SpecialistBase`
    and a :class:`SpecialistLlm` at construction time.

    W09 — Specialist-failure isolation (F11.5, Design §7.5): an exception
    raised anywhere inside :meth:`SpecialistBase.run` is caught here and
    materialised as a ``status='failed'`` slot with the error class in
    ``errors``. The workflow continues (other specialists still run) and
    synthesis reflects the gap.
    """

    def __init__(
        self,
        *,
        specialist: SpecialistBase,
        llm: SpecialistLlm,
        executor_id: str | None = None,
        metric_emitter: MetricEmitter | None = None,
    ) -> None:
        super().__init__(id=executor_id or f"specialist_{specialist.name}")
        self._specialist = specialist
        self._llm = llm
        self._metrics: MetricEmitter = metric_emitter or NullMetricEmitter()
        # Cache the typed name for the ``in`` check below.
        self._name: SpecialistName = specialist.name  # type: ignore[assignment]

    @property
    def specialist_name(self) -> str:
        return self._specialist.name

    @handler
    async def handle_dispatch(
        self,
        message: SpecialistDispatch,
        ctx: WorkflowContext[OrchestrationWorkflowState],
    ) -> None:
        if self._name not in message.decision.specialists:
            # Not selected — forward state unchanged so the fan-in
            # barrier completes.
            await ctx.send_message(message.state)
            return

        started_at = datetime.now(timezone.utc)
        inputs = SpecialistInputs(
            patient_id=message.state.patient_id,
            original_query=message.state.original_query,
            requested_diseases=(
                list(message.decision.requested_diseases)
                if message.decision.requested_diseases is not None
                else message.state.requested_diseases
            ),
        )
        # W08: one span per specialist run; provenance built inside the
        # specialist inherits the trace/span ids via
        # ``get_current_trace_and_span_ids`` (Design §20.6).
        # W09 (F11.5): catch every exception here so one failing
        # specialist can't take down the whole orchestration.
        slot: SpecialistSlot
        try:
            with specialist_span(
                self._name, patient_id=inputs.patient_id
            ) as _:
                slot_output = await self._specialist.run(
                    inputs=inputs, ctx=message.state.ctx, llm=self._llm
                )
        except Exception as exc:  # noqa: BLE001 — isolation is the point
            error_class = type(exc).__name__
            _logger.exception(
                "specialist.executor.failed",
                specialist=self._name,
                error_class=error_class,
            )
            self._metrics.emit_specialist_failed(
                domain=self._name, error_class=error_class
            )
            slot = SpecialistSlot(
                status="failed",
                output=None,
                errors=[f"{error_class}: {exc}"],
            )
        else:
            # Map the domain SpecialistSlotOutput's status onto the
            # workflow's SpecialistSlot envelope. Payload is serialised for
            # the opaque slot store.
            payload = slot_output.model_dump(mode="json")
            slot_status = _slot_status_for(payload.get("status"))
            slot = SpecialistSlot(
                status=slot_status,
                output=payload,
                errors=list(payload.get("errors") or []),
            )

        duration_ms = int(
            (datetime.now(timezone.utc) - started_at).total_seconds() * 1000
        )
        self._metrics.emit_specialist(
            domain=self._name, status=slot.status, duration_ms=duration_ms
        )
        updated = message.state.model_copy(
            update={
                self._name: slot,
                "agents_completed": apply_agents_completed(
                    list(message.state.agents_completed), self._name
                ),
            }
        )
        _logger.info(
            "specialist.executor.completed",
            specialist=self._name,
            status=slot.status,
            duration_ms=duration_ms,
        )
        await ctx.send_message(updated)


def _slot_status_for(specialist_status: str | None) -> str:
    """Map the specialist's status vocabulary onto the workflow slot's."""
    mapping = {
        "completed": "completed",
        "failed": "failed",
        "partial": "completed",  # partial still populates the slot
    }
    return mapping.get(specialist_status or "", "failed")
