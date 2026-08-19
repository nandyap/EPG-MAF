"""MAF-backed implementation of the :class:`SynthesisLlm` protocol.

Sibling of :mod:`egp_maf.workflow.router_llm_maf` — a narrow adapter over
:meth:`OpenAIChatClient.get_response` that turns the conversation plus the
(provenance-stripped) clinical context into the clinician-facing reply.

Unlike the router LLMs this call is **not** structured: the synthesis step
emits free prose, so no ``response_format`` is set.

Structural typing only — this class satisfies
:class:`egp_maf.workflow.chat.synthesize_response.SynthesisLlm` without
importing it, which keeps the module free of any import cycle back into
the workflow package.
"""

from __future__ import annotations

import logging
from typing import Any

from agent_framework import ChatOptions, Content, Message
from agent_framework.openai import OpenAIChatClient

from egp_maf.telemetry import llm_span

_logger = logging.getLogger(__name__)

# Roles we forward to the model. ``system`` is supplied by the prompt and
# ``tool`` messages belong to the specialist ReAct loops, not to synthesis.
_FORWARDED_ROLES = ("user", "assistant")


def _msg(role: str, text: str) -> Message:
    return Message(role=role, contents=[Content(type="text", text=text)])


def _response_text(response: Any) -> str:
    """Pull the assistant text out of a MAF response."""
    text = getattr(response, "text", None)
    if text:
        return str(text)
    for msg in reversed(getattr(response, "messages", None) or []):
        for content in getattr(msg, "contents", None) or []:
            if getattr(content, "type", None) == "text" and getattr(
                content, "text", None
            ):
                return str(content.text)
    return ""


class MafSynthesisLlm:
    """Real Compass-backed synthesis step for the chat workflow."""

    def __init__(
        self,
        *,
        client: OpenAIChatClient,
        system_prompt: str,
        model_label: str = "chat",
        temperature: float = 0.0,
    ) -> None:
        self._client = client
        self._system_prompt = system_prompt
        self._model_label = model_label
        self._temperature = temperature

    async def synthesise(
        self,
        *,
        original_query: str,
        messages: list[Any],
        clinical_context: str,
    ) -> str:
        """Return the clinician-facing reply.

        ``clinical_context`` has already had provenance stripped by
        :func:`~egp_maf.workflow.chat.synthesize_response._build_clinical_context`
        (Design §5.4) — this method must never receive raw provenance.
        """
        chat_messages: list[Message] = [_msg("system", self._system_prompt)]

        # Prior turns give the model conversational continuity. The
        # current question is re-rendered below alongside the clinical
        # data, so drop it here to avoid asking it twice.
        history = [m for m in messages if getattr(m, "role", None) in _FORWARDED_ROLES]
        if (
            history
            and history[-1].role == "user"
            and history[-1].content == original_query
        ):
            history = history[:-1]
        chat_messages.extend(_msg(m.role, m.content) for m in history)

        chat_messages.append(
            _msg(
                "user",
                f"Clinician question:\n{original_query}\n\n"
                f"Clinical data retrieved for this patient:\n{clinical_context}\n\n"
                "Answer the question using only the clinical data above.",
            )
        )

        with llm_span(model=self._model_label, phase="synthesis"):
            response = await self._client.get_response(
                chat_messages,
                options=ChatOptions(temperature=self._temperature),
            )

        reply = _response_text(response)
        if not reply:
            # Never return an empty bubble to the clinician.
            _logger.warning(
                "synthesis_llm.empty_response",
                extra={"model": self._model_label},
            )
            return (
                "I was unable to generate a response for that question. "
                "Please try rephrasing it."
            )
        return reply
