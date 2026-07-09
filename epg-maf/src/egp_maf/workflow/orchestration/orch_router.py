"""``orch_router`` executor — Design §5.5, ADR-009, ADR-013.

Emits a :class:`SpecialistDispatchSet` decision. Enforces:

- Phase 1 sequential-only cardinality (``|specialists| <= 1``) when the
  process is in :class:`DispatchMode.SEQUENTIAL` mode.
- Iteration budget = ``settings.orch_iteration_budget`` (default 12);
  breach raises :class:`RoutingBudgetExceeded`.

Terminal-decision path (empty :class:`SpecialistDispatchSet`) yields the
current :class:`OrchestrationWorkflowState` as the sub-workflow output
so :class:`RunOrchestrationExecutor` can merge slots back onto the outer
:class:`ChatWorkflowState`.
"""

from __future__ import annotations

from agent_framework import Executor, WorkflowContext, handler

from egp_maf.config.settings import DispatchMode, Settings
from egp_maf.errors import RoutingBudgetExceeded
from egp_maf.logging.setup import get_logger
from egp_maf.workflow.decisions import SpecialistDispatchSet
from egp_maf.workflow.orchestration.dispatcher import SpecialistDispatch
from egp_maf.workflow.router_llm import OrchRouterLlm
from egp_maf.workflow.state import OrchestrationWorkflowState

_logger = get_logger(__name__)


class OrchRouterExecutor(Executor):
    """Executor id: ``orch_router``.

    Inputs: :class:`OrchestrationWorkflowState`.

    Non-terminal path: sends a :class:`SpecialistDispatch` (state + decision)
    downstream to the dispatcher.
    Terminal path: yields the final :class:`OrchestrationWorkflowState`.
    """

    def __init__(
        self,
        *,
        router_llm: OrchRouterLlm,
        settings: Settings,
        executor_id: str = "orch_router",
    ) -> None:
        super().__init__(id=executor_id)
        self._router_llm = router_llm
        self._settings = settings

    @handler
    async def handle_state(
        self,
        message: OrchestrationWorkflowState,
        ctx: WorkflowContext[SpecialistDispatch, OrchestrationWorkflowState],
    ) -> None:
        # Budget check first — before we spend another LLM call.
        if message.router_iterations >= self._settings.orch_iteration_budget:
            _logger.warning(
                "orch_router.budget_exceeded",
                iterations=message.router_iterations,
                budget=self._settings.orch_iteration_budget,
                agents_completed=list(message.agents_completed),
            )
            raise RoutingBudgetExceeded(
                f"Orchestration iteration budget of "
                f"{self._settings.orch_iteration_budget} exceeded "
                f"(agents_completed={list(message.agents_completed)!r})."
            )

        decision = await self._router_llm.decide_dispatch(
            original_query=message.original_query,
            agents_completed=list(message.agents_completed),
            requested_diseases=message.requested_diseases,
        )

        # Sanitise per DispatchMode (Design ADR-013 §Phase 1).
        if (
            self._settings.orch_dispatch_mode == DispatchMode.SEQUENTIAL
            and len(decision.specialists) > 1
        ):
            _logger.warning(
                "orch_router.parallel_decision_downgraded",
                requested=list(decision.specialists),
                reason=decision.reason,
            )
            decision = SpecialistDispatchSet(
                specialists=[decision.specialists[0]],
                reason=(
                    f"{decision.reason} "
                    f"(downgraded to sequential per ORCH_DISPATCH_MODE)"
                ),
                requested_diseases=decision.requested_diseases,
            )

        # Cap fan-out width regardless of mode.
        if len(decision.specialists) > self._settings.orch_max_fanout_width:
            _logger.warning(
                "orch_router.fanout_width_capped",
                requested_width=len(decision.specialists),
                capped_to=self._settings.orch_max_fanout_width,
            )
            decision = SpecialistDispatchSet(
                specialists=decision.specialists[: self._settings.orch_max_fanout_width],
                reason=(
                    f"{decision.reason} "
                    f"(capped to width {self._settings.orch_max_fanout_width})"
                ),
                requested_diseases=decision.requested_diseases,
            )

        # Terminal path.
        if decision.is_terminal():
            _logger.info(
                "orch_router.terminal",
                iterations=message.router_iterations,
                agents_completed=list(message.agents_completed),
                reason=decision.reason,
            )
            await ctx.yield_output(message)
            return

        # Non-terminal path — increment iteration counter, dispatch.
        next_state = message.model_copy(
            update={
                "router_iterations": message.router_iterations + 1,
                "requested_diseases": (
                    decision.requested_diseases
                    if decision.requested_diseases is not None
                    else message.requested_diseases
                ),
            }
        )
        _logger.info(
            "orch_router.dispatched",
            iterations=next_state.router_iterations,
            dispatch=list(decision.specialists),
            reason=decision.reason,
        )
        await ctx.send_message(
            SpecialistDispatch(state=next_state, decision=decision),
        )
