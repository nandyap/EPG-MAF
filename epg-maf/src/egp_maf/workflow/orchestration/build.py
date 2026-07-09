"""Orchestration-workflow assembly.

Topology:

.. code-block:: text

    orch_router ──> specialist_dispatcher ──fan-out──> [5 stubs]
                                                          │
                                              fan-in ─────┘
                                                          │
                                                          v
                                                  specialist_joiner
                                                          │
                                                          v
                                                    orch_router (loop)

The router's terminal path yields the final
:class:`OrchestrationWorkflowState`, which
:class:`~egp_maf.workflow.chat.run_orchestration.RunOrchestrationExecutor`
consumes.
"""

from __future__ import annotations

from typing import get_args

from agent_framework import Workflow, WorkflowBuilder

from egp_maf.config.settings import Settings
from egp_maf.workflow.decisions import SpecialistName
from egp_maf.workflow.orchestration.dispatcher import (
    SpecialistDispatcherExecutor,
    SpecialistJoinerExecutor,
)
from egp_maf.workflow.orchestration.orch_router import OrchRouterExecutor
from egp_maf.workflow.orchestration.specialist_stub import (
    SpecialistPlaceholderExecutor,
)
from egp_maf.workflow.router_llm import OrchRouterLlm


def build_orchestration_workflow(
    *,
    router_llm: OrchRouterLlm,
    settings: Settings,
) -> Workflow:
    """Assemble the orchestration sub-workflow with 5 specialist stubs.

    Uses W04 placeholder executors. W05 will replace each stub with a
    real :class:`ChatAgent`-backed specialist without changing the
    surrounding topology.
    """
    orch_router = OrchRouterExecutor(router_llm=router_llm, settings=settings)
    dispatcher = SpecialistDispatcherExecutor()
    joiner = SpecialistJoinerExecutor()
    stubs = [
        SpecialistPlaceholderExecutor(name=name) for name in get_args(SpecialistName)
    ]

    # Cap by loop safety: MAF's WorkflowBuilder(max_iterations=...) is a
    # hard superstep cap independent of our own router-iteration budget.
    # We give ourselves generous headroom because a single dispatch cycle
    # can span multiple supersteps (router → dispatcher → 5 stubs → joiner
    # is ~4 supersteps).
    superstep_headroom = max(50, settings.orch_iteration_budget * 6)

    builder = WorkflowBuilder(
        max_iterations=superstep_headroom,
        start_executor=orch_router,
        name="egp_orchestration_workflow",
        description=(
            "Domain orchestration: orch_router → fan-out to specialists → "
            "fan-in → orch_router (loop). Phase 1 dispatches ≤1 specialist "
            "per iteration; fan-out plumbing is present but dormant."
        ),
        # ``orch_router`` is the sole terminal executor (it yields the final
        # OrchestrationWorkflowState on the terminal path).
        output_from=[orch_router],
    )

    builder.add_edge(orch_router, dispatcher)
    builder.add_fan_out_edges(dispatcher, stubs)
    builder.add_fan_in_edges(stubs, joiner)
    builder.add_edge(joiner, orch_router)

    return builder.build()
