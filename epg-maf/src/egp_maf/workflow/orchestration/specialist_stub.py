"""Specialist placeholder executor — W04 stub.

Real :class:`ChatAgent`-backed specialists ship in W05 (E07). W04 needs
something that:

- Recognises when its specialist is in the current
  :class:`SpecialistDispatchSet` and runs; otherwise passes through
  without producing an update.
- Merges a :class:`SpecialistSlot` marked ``completed`` with a marker
  payload back onto :class:`OrchestrationWorkflowState`.
- Appends its own name to ``agents_completed`` via the set-append reducer.

The stub payload records the ``requested_diseases`` filter (if any) so
downstream tests can assert propagation.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from agent_framework import Executor, WorkflowContext, handler

from egp_maf.logging.setup import get_logger
from egp_maf.workflow.decisions import SpecialistName
from egp_maf.workflow.orchestration.dispatcher import SpecialistDispatch
from egp_maf.workflow.state import (
    OrchestrationWorkflowState,
    SpecialistSlot,
    apply_agents_completed,
)

_logger = get_logger(__name__)


class SpecialistPlaceholderExecutor(Executor):
    """Executor id defaults to ``specialist_<name>``.

    Inputs: :class:`SpecialistDispatch`.
    Sends: :class:`OrchestrationWorkflowState`.
    """

    def __init__(
        self,
        *,
        name: SpecialistName,
        executor_id: str | None = None,
    ) -> None:
        super().__init__(id=executor_id or f"specialist_{name}")
        self._name: SpecialistName = name

    @property
    def specialist_name(self) -> SpecialistName:
        return self._name

    @handler
    async def handle_dispatch(
        self,
        message: SpecialistDispatch,
        ctx: WorkflowContext[OrchestrationWorkflowState],
    ) -> None:
        if self._name not in message.decision.specialists:
            # Not selected this iteration — pass state through unchanged so
            # the fan-in barrier can complete.
            await ctx.send_message(message.state)
            return

        # W04 stub payload — W05 replaces this with the specialist's real
        # <Domain>StateOutput.model_dump().
        payload: dict[str, Any] = {
            "specialist": self._name,
            "placeholder": True,
            "requested_diseases": (
                list(message.decision.requested_diseases)
                if message.decision.requested_diseases is not None
                else None
            ),
            "produced_at": datetime.now(timezone.utc).isoformat(),
        }
        slot = SpecialistSlot.completed_with(payload)
        updated = message.state.model_copy(
            update={
                self._name: slot,
                "agents_completed": apply_agents_completed(
                    list(message.state.agents_completed),
                    self._name,
                ),
            }
        )
        _logger.info(
            "specialist.stub_completed",
            specialist=self._name,
            agents_completed=list(updated.agents_completed),
        )
        await ctx.send_message(updated)
