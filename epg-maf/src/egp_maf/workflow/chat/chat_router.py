"""``chat_router`` executor — Design §5.4.

Reads the latest user message from :class:`ChatWorkflowState`, asks the
router LLM whether the turn needs new clinical data, applies any
``reset_agents`` decision, and forwards the state to either the
orchestration sub-workflow or straight to synthesis.

Mirrors prototype ``agents/chat/graph/graph.py::chat_router_node``.
"""

from __future__ import annotations

from agent_framework import Executor, WorkflowContext, handler

from egp_maf.logging.setup import get_logger
from egp_maf.workflow.decisions import ALL_SPECIALIST_NAMES
from egp_maf.workflow.router_llm import RouterLlm
from egp_maf.workflow.state import (
    ChatWorkflowState,
    Remove,
    apply_agents_completed,
)

_logger = get_logger(__name__)


class ChatRouterExecutor(Executor):
    """Executor id: ``chat_router``.

    Sends ``ChatWorkflowState`` downstream. The switch-case edge in
    :func:`.build.build_chat_workflow` routes on ``state.next_action``:
    ``"run_orchestration"`` → orchestration sub-workflow, otherwise
    → :class:`SynthesizeResponseExecutor`.
    """

    def __init__(self, *, router_llm: RouterLlm, executor_id: str = "chat_router") -> None:
        super().__init__(id=executor_id)
        self._router_llm = router_llm

    @handler
    async def handle_state(
        self,
        message: ChatWorkflowState,
        ctx: WorkflowContext[ChatWorkflowState],
    ) -> None:
        # Extract the latest user message → original_query.
        original_query = message.original_query
        for msg in reversed(message.messages):
            if msg.role == "user":
                original_query = msg.content
                break

        cached_domains = [
            name
            for name in ("prs", "genomic_variants", "family_history", "pgx", "phenotype")
            if getattr(message, name) is not None
        ]

        decision = await self._router_llm.decide_chat_route(
            original_query=original_query,
            agents_completed=list(message.agents_completed),
            cached_domains=cached_domains,
        )

        _logger.info(
            "chat_router.decided",
            needs_clinical_data=decision.needs_clinical_data,
            reset_agents=list(decision.reset_agents),
            thread_id=message.thread_id,
        )

        # Apply reset — drop cached slots + names from agents_completed.
        updates: dict[str, object] = {
            "original_query": original_query,
            "next_action": (
                "run_orchestration"
                if decision.needs_clinical_data
                else "respond_directly"
            ),
        }

        if decision.reset_agents:
            resets = [
                name for name in decision.reset_agents if name in ALL_SPECIALIST_NAMES
            ]
            if resets:
                updates["agents_completed"] = apply_agents_completed(
                    list(message.agents_completed),
                    [Remove(name=name) for name in resets],
                )
                for name in resets:
                    updates[name] = None

        next_state = message.model_copy(update=updates)
        await ctx.send_message(next_state)
