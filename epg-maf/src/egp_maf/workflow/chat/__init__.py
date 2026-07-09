"""Chat-workflow executors — Design §5.4.

Three executors in this package:

- :class:`.chat_router.ChatRouterExecutor` — decides whether the current
  turn needs fresh clinical data.
- :class:`.run_orchestration.RunOrchestrationExecutor` — invokes the
  orchestration sub-workflow.
- :class:`.synthesize_response.SynthesizeResponseExecutor` — synthesises
  the clinician-facing response with provenance stripped.

Assembly (:mod:`.build`) wires them with :class:`WorkflowBuilder`.
"""

from egp_maf.workflow.chat.build import build_chat_workflow
from egp_maf.workflow.chat.chat_router import ChatRouterExecutor
from egp_maf.workflow.chat.run_orchestration import RunOrchestrationExecutor
from egp_maf.workflow.chat.synthesize_response import (
    SynthesizeResponseExecutor,
    strip_provenance,
)

__all__ = [
    "ChatRouterExecutor",
    "RunOrchestrationExecutor",
    "SynthesizeResponseExecutor",
    "build_chat_workflow",
    "strip_provenance",
]
