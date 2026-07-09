"""MAF workflow skeleton — chat + orchestration sub-workflow.

Delivered in W04. Contains:

- Shared-state models (:mod:`.state`) — mirror the prototype's
  ``ChatAgentState`` and ``OrchestrationAgentState`` field-for-field,
  add ``ClinicianContext`` (ADR-008) and list-append reducer for
  ``agents_completed`` (ADR-009).
- Router decision types (:mod:`.decisions`) — ``ChatRouterDecision`` and
  the Phase-1 singleton-set-only ``SpecialistDispatchSet`` (ADR-013).
- Router LLM protocol (:mod:`.router_llm`) — the seam that W05 replaces
  with real Compass ``ChatAgent`` calls; W04 tests use a deterministic
  stub.
- Chat executors (:mod:`.chat`) — ``ChatRouterExecutor``,
  ``SynthesizeResponseExecutor`` and the orchestration sub-workflow
  invocation.
- Orchestration executors (:mod:`.orchestration`) — ``OrchRouterExecutor``,
  5 specialist placeholder executors (real specialists land in W05),
  fan-out/fan-in edges wired but dormant at width 1, iteration-budget
  tracker.
- :class:`.runtime.WorkflowRuntime` — startup facade returned by the DI
  container.

Framework touch points: :mod:`agent_framework` (``WorkflowBuilder``,
``Executor``, ``WorkflowContext``, ``WorkflowExecutor``, ``handler``,
``FanOutEdgeGroup``, ``FanInEdgeGroup``, ``SwitchCaseEdgeGroup``).
No Compass or LLM calls in W04.
"""

from egp_maf.workflow.decisions import (
    ChatRouterDecision,
    SpecialistDispatchSet,
    SpecialistName,
)
from egp_maf.workflow.router_llm import (
    OrchRouterLlm,
    RouterLlm,
    StubOrchRouterLlm,
    StubRouterLlm,
)
from egp_maf.workflow.runtime import WorkflowRuntime
from egp_maf.workflow.state import (
    ChatWorkflowState,
    OrchestrationWorkflowState,
    Remove,
    SpecialistSlot,
    apply_agents_completed,
    apply_specialist_slot,
)

__all__ = [
    "ChatRouterDecision",
    "ChatWorkflowState",
    "OrchRouterLlm",
    "OrchestrationWorkflowState",
    "Remove",
    "RouterLlm",
    "SpecialistDispatchSet",
    "SpecialistName",
    "SpecialistSlot",
    "StubOrchRouterLlm",
    "StubRouterLlm",
    "WorkflowRuntime",
    "apply_agents_completed",
    "apply_specialist_slot",
]
