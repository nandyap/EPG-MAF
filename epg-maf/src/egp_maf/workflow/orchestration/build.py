"""Orchestration-workflow assembly.

Topology:

.. code-block:: text

    orch_router ──> specialist_dispatcher ──fan-out──> [5 specialists]
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

W04 wired :class:`SpecialistPlaceholderExecutor` at each of the 5
positions. W05 introduces :class:`SpecialistExecutor` (backed by a real
:class:`SpecialistBase`) and takes an optional
:class:`SpecialistRegistry`; if supplied, real specialists are wired in
place of the stubs — the topology and the executor IDs are unchanged.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, get_args

from agent_framework import Executor, Workflow, WorkflowBuilder

from egp_maf.config.settings import Settings
from egp_maf.telemetry.metrics import MetricEmitter, NullMetricEmitter
from egp_maf.workflow.decisions import SpecialistName
from egp_maf.workflow.orchestration.dispatcher import (
    SpecialistDispatcherExecutor,
    SpecialistJoinerExecutor,
)
from egp_maf.workflow.orchestration.orch_router import OrchRouterExecutor
from egp_maf.workflow.orchestration.specialist_executor import SpecialistExecutor
from egp_maf.workflow.orchestration.specialist_stub import (
    SpecialistPlaceholderExecutor,
)
from egp_maf.workflow.router_llm import OrchRouterLlm

if TYPE_CHECKING:  # pragma: no cover
    from egp_maf.agents.registry import SpecialistRegistry


def build_orchestration_workflow(
    *,
    router_llm: OrchRouterLlm,
    settings: Settings,
    specialist_registry: "SpecialistRegistry | None" = None,
    metric_emitter: MetricEmitter | None = None,
) -> Workflow:
    """Assemble the orchestration sub-workflow.

    When ``specialist_registry`` is provided (W05+), the 5 specialist
    positions are wired to real :class:`SpecialistExecutor`s backed by
    the registry's :class:`SpecialistBase` + :class:`SpecialistLlm`
    pairs. When omitted (or when the registry is missing a specialist),
    the position falls back to :class:`SpecialistPlaceholderExecutor` —
    which keeps W04-era tests and cheap smoke runs working.

    W09 — ``metric_emitter`` (F11.5) is threaded into every
    :class:`SpecialistExecutor` so a failed specialist emits
    ``egp.specialist.failed``. Defaults to
    :class:`NullMetricEmitter` for tests that don't wire telemetry.
    """
    orch_router = OrchRouterExecutor(router_llm=router_llm, settings=settings)
    dispatcher = SpecialistDispatcherExecutor()
    joiner = SpecialistJoinerExecutor()
    metrics = metric_emitter or NullMetricEmitter()
    specialists: list[Executor] = []
    for name in get_args(SpecialistName):
        if specialist_registry is not None and name in specialist_registry.specialists:
            specialists.append(
                SpecialistExecutor(
                    specialist=specialist_registry.specialists[name],
                    llm=specialist_registry.get_llm(name),
                    metric_emitter=metrics,
                )
            )
        else:
            specialists.append(SpecialistPlaceholderExecutor(name=name))

    # Cap by loop safety: MAF's WorkflowBuilder(max_iterations=...) is a
    # hard superstep cap independent of our own router-iteration budget.
    # We give ourselves generous headroom because a single dispatch cycle
    # can span multiple supersteps (router → dispatcher → 5 branches → joiner
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
    builder.add_fan_out_edges(dispatcher, specialists)
    builder.add_fan_in_edges(specialists, joiner)
    builder.add_edge(joiner, orch_router)

    return builder.build()
