"""``synthesize_response`` executor — Design §5.4.

Composes clinical context (provenance stripped), calls the synthesis
seam, appends an assistant :class:`SessionMessage` to the state, and
yields the final state as the workflow output.

The synthesis LLM is behind a small protocol so W04 tests don't need a
real Compass call. W05 replaces the stub with a real ``ChatAgent`` call.
"""

from __future__ import annotations

import json
from typing import Any, Protocol

from agent_framework import Executor, WorkflowContext, handler

from egp_maf.logging.setup import get_logger
from egp_maf.workflow.state import ChatWorkflowState, SessionMessage

_logger = get_logger(__name__)

_PROVENANCE_KEY = "provenance"


def strip_provenance(data: Any) -> Any:
    """Recursively drop any key named ``provenance`` from nested dicts/lists.

    Preserves the prototype's ``_strip_provenance`` behaviour (see
    ``agents/chat/graph/graph.py``). The synthesis LLM never sees
    provenance — it belongs on the state and in audit logs only.
    """
    if isinstance(data, dict):
        return {k: strip_provenance(v) for k, v in data.items() if k != _PROVENANCE_KEY}
    if isinstance(data, list):
        return [strip_provenance(item) for item in data]
    return data


class SynthesisLlm(Protocol):
    """Emits the assistant's reply given the conversation + clinical context."""

    async def synthesise(
        self,
        *,
        original_query: str,
        messages: list[SessionMessage],
        clinical_context: str,
    ) -> str: ...


class StubSynthesisLlm:
    """Deterministic stub. Returns a canned string derived from the query."""

    def __init__(self, template: str = "STUB: {query}") -> None:
        self._template = template

    async def synthesise(
        self,
        *,
        original_query: str,
        messages: list[SessionMessage],
        clinical_context: str,
    ) -> str:
        return self._template.format(query=original_query or "<empty>")


_DOMAIN_LABELS: tuple[tuple[str, str], ...] = (
    ("prs", "Polygenic Risk Scores (PRS)"),
    ("genomic_variants", "Genomic Variants"),
    ("family_history", "Family History"),
    ("pgx", "Pharmacogenomics (PGX)"),
    ("phenotype", "Phenotype / Clinical Diagnoses"),
)


def _build_clinical_context(state: ChatWorkflowState) -> str:
    """Serialise each present specialist slot into a text block.

    Provenance is stripped before serialisation (Design §5.4). Absent
    slots are silently skipped.

    Failed slots are described in neutral clinical language rather than by
    dumping ``slot.errors``. Those strings are our internal taxonomy —
    ``LlmError: LLM upstream error: ValidationError`` and similar — and the
    synthesis LLM faithfully relayed them to the clinician, which is both
    meaningless to a clinical reader and alarming in a demo. The operator
    detail stays in logs, spans and the specialist slot; only the fact of
    the gap reaches the reply.
    """
    sections: list[str] = []
    for name, label in _DOMAIN_LABELS:
        slot = getattr(state, name)
        if slot is None:
            continue
        if slot.output is None:
            sections.append(
                f"## {label}\n"
                "Data could not be retrieved for this domain on this turn. "
                "State plainly that this information is unavailable right "
                "now and must not be inferred. Do not speculate about the "
                "cause and do not describe it as a system or technical "
                "error."
            )
            continue
        stripped = strip_provenance(slot.output)
        sections.append(
            f"## {label}\n{json.dumps(stripped, indent=2, default=str)}"
        )
    if not sections:
        return "No clinical data has been retrieved for this patient yet."
    return "\n\n".join(sections)


class SynthesizeResponseExecutor(Executor):
    """Executor id: ``synthesize_response``. Terminal — yields the final
    :class:`ChatWorkflowState`."""

    def __init__(
        self,
        *,
        synthesis_llm: SynthesisLlm,
        executor_id: str = "synthesize_response",
    ) -> None:
        super().__init__(id=executor_id)
        self._synthesis_llm = synthesis_llm

    @handler
    async def handle_state(
        self,
        message: ChatWorkflowState,
        ctx: WorkflowContext[None, ChatWorkflowState],
    ) -> None:
        clinical_context = _build_clinical_context(message)
        reply_text = await self._synthesis_llm.synthesise(
            original_query=message.original_query,
            messages=list(message.messages),
            clinical_context=clinical_context,
        )
        appended = message.model_copy(
            update={
                "messages": [
                    *message.messages,
                    SessionMessage(role="assistant", content=reply_text),
                ],
            }
        )
        _logger.info(
            "synthesize_response.completed",
            thread_id=message.thread_id,
            message_count=len(appended.messages),
        )
        await ctx.yield_output(appended)
