"""Chat-workflow assembly.

Wires the three chat executors with :class:`WorkflowBuilder`:

.. code-block:: text

    chat_router ──cond──> run_orchestration ──> synthesize_response
                └cond───────────────────────────> synthesize_response

Routing is via two conditional edges on ``ChatWorkflowState.next_action``.
(MAF's ``add_switch_case_edge_group`` has an internal attribute-name bug
at 1.10.0 — two ``add_edge`` calls with mutually-exclusive conditions is
semantically identical and works today.)
"""

from __future__ import annotations

from agent_framework import Workflow, WorkflowBuilder

from egp_maf.workflow.chat.chat_router import ChatRouterExecutor
from egp_maf.workflow.chat.run_orchestration import RunOrchestrationExecutor
from egp_maf.workflow.chat.synthesize_response import (
    StubSynthesisLlm,
    SynthesisLlm,
    SynthesizeResponseExecutor,
)
from egp_maf.workflow.router_llm import RouterLlm
from egp_maf.workflow.state import ChatWorkflowState


def _needs_orchestration(state: object) -> bool:
    return (
        isinstance(state, ChatWorkflowState)
        and state.next_action == "run_orchestration"
    )


def _does_not_need_orchestration(state: object) -> bool:
    return not _needs_orchestration(state)


def build_chat_workflow(
    *,
    router_llm: RouterLlm,
    orchestration_workflow: Workflow,
    synthesis_llm: SynthesisLlm | None = None,
) -> Workflow:
    """Assemble the chat workflow.

    Callers pass the pre-built orchestration :class:`Workflow` (see
    :mod:`egp_maf.workflow.orchestration.build`). The synthesis LLM
    defaults to a stub in W04; W05 wires the real Compass client.
    """
    chat_router = ChatRouterExecutor(router_llm=router_llm)
    run_orchestration = RunOrchestrationExecutor(
        orchestration_workflow=orchestration_workflow,
    )
    synth = SynthesizeResponseExecutor(
        synthesis_llm=synthesis_llm or StubSynthesisLlm(),
    )

    builder = WorkflowBuilder(
        start_executor=chat_router,
        name="egp_chat_workflow",
        description=(
            "Per-turn chat workflow: chat_router → (orchestration sub-workflow "
            "| direct) → synthesize_response."
        ),
        # ``synthesize_response`` is the sole terminal executor — be
        # explicit so MAF's future strict-output validation is a no-op.
        output_from=[synth],
    )

    builder.add_edge(chat_router, run_orchestration, condition=_needs_orchestration)
    builder.add_edge(chat_router, synth, condition=_does_not_need_orchestration)
    builder.add_edge(run_orchestration, synth)

    return builder.build()
