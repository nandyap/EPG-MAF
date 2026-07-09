"""``run_orchestration`` executor — Design ADR-007.

Wraps the orchestration sub-workflow so events surface to the outer stream.
Reads the outer :class:`ChatWorkflowState`, constructs an
:class:`OrchestrationWorkflowState`, invokes the inner workflow, and
merges the resulting specialist slots back onto the outer state.

W04 executes the sub-workflow synchronously via ``Workflow.run(...)``;
event forwarding to the outer stream is intentionally deferred to W08
(observability) — the executor still logs one structured event per
sub-workflow run so operators have coverage in the meantime.
"""

from __future__ import annotations

from typing import Any

from agent_framework import Executor, Workflow, WorkflowContext, handler

from egp_maf.errors import RoutingBudgetExceeded, SpecialistFailed
from egp_maf.logging.setup import get_logger
from egp_maf.workflow.state import (
    ChatWorkflowState,
    OrchestrationWorkflowState,
    SpecialistSlot,
)

_logger = get_logger(__name__)

_SPECIALIST_SLOTS = (
    "prs",
    "genomic_variants",
    "family_history",
    "pgx",
    "phenotype",
)


class RunOrchestrationExecutor(Executor):
    """Executor id: ``run_orchestration``.

    Inputs: :class:`ChatWorkflowState` (only invoked when
    ``chat_router`` set ``next_action == "run_orchestration"``).

    Sends the mutated :class:`ChatWorkflowState` (with merged specialist
    slots + agents_completed) downstream to :class:`SynthesizeResponseExecutor`.
    """

    def __init__(
        self,
        *,
        orchestration_workflow: Workflow,
        executor_id: str = "run_orchestration",
    ) -> None:
        super().__init__(id=executor_id)
        self._orchestration_workflow = orchestration_workflow

    @handler
    async def handle_state(
        self,
        message: ChatWorkflowState,
        ctx: WorkflowContext[ChatWorkflowState],
    ) -> None:
        inner_state = OrchestrationWorkflowState(
            ctx=message.ctx,
            patient_id=message.patient_id,
            original_query=message.original_query,
            conversation_id=message.conversation_id,
            clinician_specialty=message.clinician_specialty,
            requested_diseases=message.requested_diseases,
            requested_genes=message.requested_genes,
            prs=message.prs,
            genomic_variants=message.genomic_variants,
            family_history=message.family_history,
            pgx=message.pgx,
            phenotype=message.phenotype,
            agents_completed=list(message.agents_completed),
        )

        try:
            run_result = await self._orchestration_workflow.run(inner_state)
        except (RoutingBudgetExceeded, SpecialistFailed) as exc:
            # Graceful degradation: keep whatever the sub-workflow managed
            # to produce; log the failure; forward outer state unchanged
            # (aside from marking the failing specialist, which the
            # sub-workflow already did).
            _logger.warning(
                "run_orchestration.sub_workflow_failed",
                error_code=exc.error_code,
                thread_id=message.thread_id,
            )
            await ctx.send_message(message)
            return

        # Sub-workflow yields its final state as workflow output.
        outputs = run_result.get_outputs()
        final_state: OrchestrationWorkflowState | None = None
        for out in outputs:
            if isinstance(out, OrchestrationWorkflowState):
                final_state = out
                break

        if final_state is None:
            _logger.warning(
                "run_orchestration.no_output",
                thread_id=message.thread_id,
                output_count=len(outputs),
            )
            await ctx.send_message(message)
            return

        merged: dict[str, Any] = {"agents_completed": list(final_state.agents_completed)}
        for slot_name in _SPECIALIST_SLOTS:
            slot = getattr(final_state, slot_name)
            if slot is not None and isinstance(slot, SpecialistSlot):
                merged[slot_name] = slot

        _logger.info(
            "run_orchestration.completed",
            thread_id=message.thread_id,
            agents_completed=list(final_state.agents_completed),
            iterations=final_state.router_iterations,
        )

        await ctx.send_message(message.model_copy(update=merged))
