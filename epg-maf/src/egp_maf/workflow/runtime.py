"""``WorkflowRuntime`` — the DI-container-facing facade for the workflow.

Owns two built :class:`Workflow` objects (chat + orchestration) and exposes
a single :meth:`run` method taking a fresh :class:`ChatWorkflowState`.

W04 shipped stub router / synthesis LLMs and stub specialist executors;
W05 accepts a :class:`SpecialistRegistry` and real router LLMs so the
orchestration positions are wired to real :class:`SpecialistExecutor`s.
The optional-registry contract keeps W04-era smoke tests working.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from agent_framework import Workflow

from egp_maf.config.settings import Settings
from egp_maf.logging.setup import get_logger
from egp_maf.workflow.chat.build import build_chat_workflow
from egp_maf.workflow.chat.synthesize_response import (
    StubSynthesisLlm,
    SynthesisLlm,
)
from egp_maf.workflow.orchestration.build import build_orchestration_workflow
from egp_maf.workflow.router_llm import OrchRouterLlm, RouterLlm
from egp_maf.workflow.state import ChatWorkflowState

if TYPE_CHECKING:  # pragma: no cover
    from egp_maf.agents.registry import SpecialistRegistry

_logger = get_logger(__name__)


class WorkflowRuntime:
    """Owns the built workflows for the lifetime of the process."""

    def __init__(
        self,
        *,
        settings: Settings,
        chat_router_llm: RouterLlm,
        orch_router_llm: OrchRouterLlm,
        synthesis_llm: SynthesisLlm | None = None,
        specialist_registry: "SpecialistRegistry | None" = None,
    ) -> None:
        self._settings = settings
        self._orchestration_workflow: Workflow = build_orchestration_workflow(
            router_llm=orch_router_llm,
            settings=settings,
            specialist_registry=specialist_registry,
        )
        self._chat_workflow: Workflow = build_chat_workflow(
            router_llm=chat_router_llm,
            orchestration_workflow=self._orchestration_workflow,
            synthesis_llm=synthesis_llm or StubSynthesisLlm(),
        )
        _logger.info(
            "workflow_runtime.built",
            dispatch_mode=settings.orch_dispatch_mode.value,
            max_fanout_width=settings.orch_max_fanout_width,
            iteration_budget=settings.orch_iteration_budget,
            specialists_wired=(
                specialist_registry.names()
                if specialist_registry is not None
                else []
            ),
        )

    @property
    def chat_workflow(self) -> Workflow:
        return self._chat_workflow

    @property
    def orchestration_workflow(self) -> Workflow:
        return self._orchestration_workflow

    async def run_turn(self, initial_state: ChatWorkflowState) -> Any:
        """Convenience — awaits the chat workflow's non-streaming run."""
        return await self._chat_workflow.run(initial_state)
