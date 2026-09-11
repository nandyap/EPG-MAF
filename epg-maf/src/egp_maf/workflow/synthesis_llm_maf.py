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

from typing import Any

from agent_framework import ChatOptions, Content, Message
from agent_framework.openai import OpenAIChatClient

from egp_maf.logging import get_logger
from egp_maf.logging.flow_trace import (
    preview,
    summarise_messages,
    trace,
    trace_payload,
)
from egp_maf.telemetry import llm_span

# structlog, not ``logging.getLogger``: ``extra={}`` on the stdlib logger
# is dropped by the ``format="%(message)s"`` root handler (§4e). The
# existing ``synthesis_llm.empty_response`` below had been losing its
# ``model`` field since it was written.
_logger = get_logger(__name__)

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

        # ``clinical_context_chars`` is the field to read when a reply
        # states something the database does not support. Synthesis can
        # only blend what it is given; a near-empty context with a
        # confident clinical reply means the content arrived from a
        # specialist slot, not from here.
        trace(
            "llm.synthesis.request",
            model=self._model_label,
            history_messages=len(history),
            total_messages=len(chat_messages),
            message_shape=summarise_messages(chat_messages),
            clinical_context_chars=len(clinical_context),
            query_chars=len(original_query),
        )
        trace_payload(
            "llm.synthesis.request.body",
            model=self._model_label,
            system_prompt=preview(self._system_prompt),
            clinical_context=preview(clinical_context),
            original_query=preview(original_query, 500),
        )

        with llm_span(model=self._model_label, phase="synthesis"):
            response = await self._client.get_response(
                chat_messages,
                options=ChatOptions(temperature=self._temperature),
            )

        reply = _response_text(response)
        trace(
            "llm.synthesis.response",
            model=self._model_label,
            reply_chars=len(reply),
            empty=not reply,
        )
        trace_payload(
            "llm.synthesis.response.body",
            model=self._model_label,
            reply=preview(reply),
        )
        if not reply:
            # Never return an empty bubble to the clinician.
            _logger.warning(
                "synthesis_llm.empty_response",
                model=self._model_label,
            )
            return (
                "I was unable to generate a response for that question. "
                "Please try rephrasing it."
            )
        return reply
