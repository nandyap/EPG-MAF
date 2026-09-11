"""MAF-backed implementations of the W04 :class:`RouterLlm` /
:class:`OrchRouterLlm` protocols.

Same shape as :class:`~egp_maf.agents.llm_bridge.MafSpecialistLlm` — a
narrow adapter that uses :class:`OpenAIChatClient.get_response` with
:class:`ChatOptions(response_format=...)` to obtain structured decisions.
The two router LLMs live here (not in :mod:`egp_maf.agents`) because
they're consumed by the workflow layer, not by any specialist.
"""

from __future__ import annotations

from typing import Any

from agent_framework import ChatOptions, Content, Message
from agent_framework.openai import OpenAIChatClient

from egp_maf.logging import get_logger
from egp_maf.logging.flow_trace import preview, trace, trace_payload
from egp_maf.telemetry import llm_span
from egp_maf.workflow.decisions import (
    ChatRouterDecision,
    SpecialistDispatchSet,
)

# structlog, not ``logging.getLogger`` — see §4e. This module had no call
# sites, so nothing was lost, but the tracing added below would have been.
_logger = get_logger(__name__)


def _msg(role: str, text: str) -> Message:
    return Message(role=role, contents=[Content(type="text", text=text)])


def _parse_decision(response: Any, schema: type[Any]) -> Any:
    parsed = getattr(response, "value", None)
    if parsed is not None:
        return parsed
    text = _last_text(response)
    return schema.model_validate_json(text)


def _last_text(response: Any) -> str:
    if getattr(response, "text", None):
        return response.text  # type: ignore[no-any-return]
    for msg in reversed(getattr(response, "messages", None) or []):
        for c in getattr(msg, "contents", None) or []:
            if getattr(c, "type", None) == "text" and getattr(c, "text", None):
                return c.text  # type: ignore[no-any-return]
    return ""


class MafChatRouterLlm:
    """Real MAF-backed :class:`RouterLlm` for the chat workflow."""

    def __init__(
        self,
        *,
        client: OpenAIChatClient,
        system_prompt: str,
        temperature: float = 0.0,
    ) -> None:
        self._client = client
        self._system_prompt = system_prompt
        self._temperature = temperature

    async def decide_chat_route(
        self,
        *,
        original_query: str,
        agents_completed: list[str],
        cached_domains: list[str],
    ) -> ChatRouterDecision:
        user_msg = (
            f"Current user message: {original_query!r}\n"
            f"agents_already_completed: "
            f"{', '.join(agents_completed) if agents_completed else 'none'}\n"
            f"cached_domains: "
            f"{', '.join(cached_domains) if cached_domains else 'none'}\n\n"
            "Decide whether the current message requires fresh clinical "
            "data. Respond via the ChatRouterDecision schema."
        )
        trace(
            "llm.chat_router.request",
            agents_completed=agents_completed,
            cached_domains=cached_domains,
            query_chars=len(original_query),
        )
        trace_payload(
            "llm.chat_router.request.body",
            system_prompt=preview(self._system_prompt),
            user_message=preview(user_msg),
        )
        with llm_span(
            model="chat_router", phase="route", structured_output=True
        ):
            response = await self._client.get_response(
                [_msg("system", self._system_prompt), _msg("user", user_msg)],
                options=ChatOptions(
                    temperature=self._temperature,
                    response_format=ChatRouterDecision,
                ),
            )
        decision = _parse_decision(response, ChatRouterDecision)
        trace(
            "llm.chat_router.response",
            decision=decision.model_dump(),
        )
        return decision

class MafOrchRouterLlm:
    """Real MAF-backed :class:`OrchRouterLlm` for the orchestration
    sub-workflow."""

    def __init__(
        self,
        *,
        client: OpenAIChatClient,
        system_prompt: str,
        temperature: float = 0.0,
    ) -> None:
        self._client = client
        self._system_prompt = system_prompt
        self._temperature = temperature

    async def decide_dispatch(
        self,
        *,
        original_query: str,
        agents_completed: list[str],
        requested_diseases: list[str] | None,
    ) -> SpecialistDispatchSet:
        user_msg = (
            f"User query: {original_query!r}\n"
            f"agents_already_completed: "
            f"{', '.join(agents_completed) if agents_completed else 'none'}\n"
            f"requested_diseases: {requested_diseases or 'none'}\n\n"
            "Decide which specialist(s) to dispatch next. Emit an empty "
            "specialists list to end the orchestration. Respond via the "
            "SpecialistDispatchSet schema."
        )
        trace(
            "llm.orch_router.request",
            agents_completed=agents_completed,
            requested_diseases=requested_diseases,
            query_chars=len(original_query),
        )
        trace_payload(
            "llm.orch_router.request.body",
            system_prompt=preview(self._system_prompt),
            user_message=preview(user_msg),
        )
        with llm_span(
            model="orch_router", phase="route", structured_output=True
        ):
            response = await self._client.get_response(
                [_msg("system", self._system_prompt), _msg("user", user_msg)],
                options=ChatOptions(
                    temperature=self._temperature,
                    response_format=SpecialistDispatchSet,
                ),
            )
        decision = _parse_decision(response, SpecialistDispatchSet)
        trace(
            "llm.orch_router.response",
            decision=decision.model_dump(),
        )
        return decision
