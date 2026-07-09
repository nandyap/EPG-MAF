"""MAF-backed implementations of the W04 :class:`RouterLlm` /
:class:`OrchRouterLlm` protocols.

Same shape as :class:`~egp_maf.agents.llm_bridge.MafSpecialistLlm` — a
narrow adapter that uses :class:`OpenAIChatClient.get_response` with
:class:`ChatOptions(response_format=...)` to obtain structured decisions.
The two router LLMs live here (not in :mod:`egp_maf.agents`) because
they're consumed by the workflow layer, not by any specialist.
"""

from __future__ import annotations

import logging
from typing import Any

from agent_framework import ChatOptions, Content, Message
from agent_framework.openai import OpenAIChatClient

from egp_maf.workflow.decisions import (
    ChatRouterDecision,
    SpecialistDispatchSet,
)

_logger = logging.getLogger(__name__)


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
        response = await self._client.get_response(
            [_msg("system", self._system_prompt), _msg("user", user_msg)],
            options=ChatOptions(
                temperature=self._temperature,
                response_format=ChatRouterDecision,
            ),
        )
        return _parse_decision(response, ChatRouterDecision)


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
        response = await self._client.get_response(
            [_msg("system", self._system_prompt), _msg("user", user_msg)],
            options=ChatOptions(
                temperature=self._temperature,
                response_format=SpecialistDispatchSet,
            ),
        )
        return _parse_decision(response, SpecialistDispatchSet)
