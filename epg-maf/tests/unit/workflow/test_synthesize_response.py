"""Tests for :class:`SynthesizeResponseExecutor` and the provenance
stripper."""

from __future__ import annotations

import json
from typing import Any

from egp_maf.state.clinician_context import ClinicianContext
from egp_maf.workflow.chat.synthesize_response import (
    StubSynthesisLlm,
    SynthesisLlm,
    SynthesizeResponseExecutor,
    strip_provenance,
)
from egp_maf.workflow.state import (
    ChatWorkflowState,
    SessionMessage,
    SpecialistSlot,
)


class CapturingContext:
    def __init__(self) -> None:
        self.yielded: list[Any] = []

    async def yield_output(self, output: Any) -> None:
        self.yielded.append(output)


class RecordingSynthesis(SynthesisLlm):
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def synthesise(
        self,
        *,
        original_query: str,
        messages: list[SessionMessage],
        clinical_context: str,
    ) -> str:
        self.calls.append(
            {
                "original_query": original_query,
                "message_count": len(messages),
                "clinical_context": clinical_context,
            }
        )
        return "OK"


class TestStripProvenance:
    def test_drops_top_level_provenance(self) -> None:
        assert strip_provenance({"a": 1, "provenance": [{}]}) == {"a": 1}

    def test_drops_nested_provenance(self) -> None:
        data = {"result": {"gene": "BRCA1", "provenance": [{"tool_name": "x"}]}}
        assert strip_provenance(data) == {"result": {"gene": "BRCA1"}}

    def test_drops_provenance_in_lists(self) -> None:
        data = {"results": [{"a": 1, "provenance": []}, {"b": 2}]}
        assert strip_provenance(data) == {"results": [{"a": 1}, {"b": 2}]}

    def test_scalars_pass_through(self) -> None:
        assert strip_provenance("hello") == "hello"
        assert strip_provenance(42) == 42
        assert strip_provenance(None) is None


def _state(**overrides: Any) -> ChatWorkflowState:
    base = ChatWorkflowState(
        ctx=ClinicianContext.system(),
        patient_id="P1",
        thread_id="T1",
        original_query="Q?",
        messages=[SessionMessage(role="user", content="Q?")],
    )
    return base.model_copy(update=overrides)


class TestSynthesizeResponseExecutor:
    async def test_appends_assistant_message_to_state(self) -> None:
        exec_ = SynthesizeResponseExecutor(synthesis_llm=StubSynthesisLlm(template="hi"))
        ctx = CapturingContext()
        await exec_.handle_state(_state(), ctx)  # type: ignore[arg-type]
        assert len(ctx.yielded) == 1
        final = ctx.yielded[0]
        assert isinstance(final, ChatWorkflowState)
        assert final.messages[-1].role == "assistant"
        assert final.messages[-1].content == "hi"

    async def test_clinical_context_contains_stripped_slot(self) -> None:
        recorder = RecordingSynthesis()
        exec_ = SynthesizeResponseExecutor(synthesis_llm=recorder)
        state = _state(
            prs=SpecialistSlot.completed_with(
                {"results": [{"prs_name": "PRS_1", "provenance": [{"x": 1}]}]}
            )
        )
        await exec_.handle_state(state, CapturingContext())  # type: ignore[arg-type]
        assert len(recorder.calls) == 1
        ctx_text = recorder.calls[0]["clinical_context"]
        assert "PRS_1" in ctx_text
        assert "provenance" not in ctx_text

    async def test_no_slots_gives_empty_notice(self) -> None:
        recorder = RecordingSynthesis()
        exec_ = SynthesizeResponseExecutor(synthesis_llm=recorder)
        await exec_.handle_state(_state(), CapturingContext())  # type: ignore[arg-type]
        assert "No clinical data" in recorder.calls[0]["clinical_context"]
