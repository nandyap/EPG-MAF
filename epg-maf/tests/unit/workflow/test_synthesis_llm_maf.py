"""Tests for :class:`MafSynthesisLlm` — the real synthesis stage.

Context: the deployed build answered every clinical question with
``STUB: <query>`` because :func:`build_container` defaulted to
:class:`StubSynthesisLlm` and nothing ever supplied a real one. No real
``SynthesisLlm`` implementation existed at all. These tests cover the
adapter that replaced it.

The MAF client is faked, so no network call is made.
"""

from __future__ import annotations

from typing import Any

import pytest

from egp_maf.workflow.state import SessionMessage
from egp_maf.workflow.synthesis_llm_maf import MafSynthesisLlm

pytestmark = pytest.mark.unit


class _FakeResponse:
    def __init__(self, text: str) -> None:
        self.text = text


class _FakeClient:
    """Records the messages it is asked to send."""

    def __init__(self, reply: str = "Assessed: no pathogenic variants.") -> None:
        self._reply = reply
        self.calls: list[dict[str, Any]] = []

    async def get_response(self, messages: Any, options: Any = None) -> Any:
        self.calls.append({"messages": list(messages), "options": options})
        return _FakeResponse(self._reply)


def _texts(messages: list[Any]) -> list[tuple[str, str]]:
    """Flatten MAF messages to ``(role, text)`` pairs."""
    out: list[tuple[str, str]] = []
    for m in messages:
        text = " ".join(
            c.text for c in m.contents if getattr(c, "type", None) == "text"
        )
        out.append((m.role, text))
    return out


def _llm(client: _FakeClient) -> MafSynthesisLlm:
    return MafSynthesisLlm(
        client=client,  # type: ignore[arg-type]
        system_prompt="SYSTEM PROMPT",
        model_label="gpt-5.1",
    )


class TestSynthesise:
    @pytest.mark.asyncio
    async def test_returns_model_reply(self) -> None:
        client = _FakeClient("BRCA1 pathogenic variant present.")

        reply = await _llm(client).synthesise(
            original_query="any BRCA findings?",
            messages=[],
            clinical_context="## Genomic Variants\n{...}",
        )

        assert reply == "BRCA1 pathogenic variant present."

    @pytest.mark.asyncio
    async def test_sends_system_prompt_first(self) -> None:
        client = _FakeClient()

        await _llm(client).synthesise(
            original_query="q", messages=[], clinical_context="ctx"
        )

        sent = _texts(client.calls[0]["messages"])
        assert sent[0] == ("system", "SYSTEM PROMPT")

    @pytest.mark.asyncio
    async def test_includes_query_and_clinical_context(self) -> None:
        client = _FakeClient()

        await _llm(client).synthesise(
            original_query="does the patient have diabetes?",
            messages=[],
            clinical_context="## Phenotype\nType 2 diabetes mellitus",
        )

        final_role, final_text = _texts(client.calls[0]["messages"])[-1]
        assert final_role == "user"
        assert "does the patient have diabetes?" in final_text
        assert "Type 2 diabetes mellitus" in final_text

    @pytest.mark.asyncio
    async def test_forwards_prior_conversation(self) -> None:
        client = _FakeClient()
        history = [
            SessionMessage(role="user", content="earlier question"),
            SessionMessage(role="assistant", content="earlier answer"),
        ]

        await _llm(client).synthesise(
            original_query="follow-up question",
            messages=history,
            clinical_context="ctx",
        )

        sent = _texts(client.calls[0]["messages"])
        assert ("user", "earlier question") in sent
        assert ("assistant", "earlier answer") in sent

    @pytest.mark.asyncio
    async def test_does_not_repeat_current_question(self) -> None:
        """The current turn is re-rendered with the clinical data, so the
        raw copy carried in ``messages`` must be dropped."""
        client = _FakeClient()
        history = [SessionMessage(role="user", content="the question")]

        await _llm(client).synthesise(
            original_query="the question",
            messages=history,
            clinical_context="ctx",
        )

        sent = _texts(client.calls[0]["messages"])
        assert ("user", "the question") not in sent
        assert sum(1 for role, _ in sent if role == "user") == 1

    @pytest.mark.asyncio
    async def test_empty_model_reply_falls_back(self) -> None:
        """Never render an empty assistant bubble to the clinician."""
        client = _FakeClient("")

        reply = await _llm(client).synthesise(
            original_query="q", messages=[], clinical_context="ctx"
        )

        assert reply
        assert "unable to generate a response" in reply
