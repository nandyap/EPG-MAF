"""Orchestration sub-workflow — Design §5.5, ADR-013.

- :class:`.orch_router.OrchRouterExecutor` — decides which specialist(s)
  to dispatch each iteration, enforces the iteration budget, terminates
  the sub-workflow on an empty :class:`SpecialistDispatchSet`.
- :class:`.specialist_stub.SpecialistPlaceholderExecutor` — W04 stub;
  reports "completed" with a marker payload. Real specialists ship in W05.
- :class:`.dispatcher.SpecialistDispatcherExecutor` — reads the router's
  decision and fans out to the specialist stubs; also handles size-1
  (Phase 1 default) with no plumbing difference.

Assembly (:mod:`.build`) wires them with :class:`WorkflowBuilder`.
"""

from egp_maf.workflow.orchestration.build import build_orchestration_workflow
from egp_maf.workflow.orchestration.dispatcher import (
    SpecialistDispatch,
    SpecialistDispatcherExecutor,
)
from egp_maf.workflow.orchestration.orch_router import OrchRouterExecutor
from egp_maf.workflow.orchestration.specialist_stub import (
    SpecialistPlaceholderExecutor,
)

__all__ = [
    "OrchRouterExecutor",
    "SpecialistDispatch",
    "SpecialistDispatcherExecutor",
    "SpecialistPlaceholderExecutor",
    "build_orchestration_workflow",
]
