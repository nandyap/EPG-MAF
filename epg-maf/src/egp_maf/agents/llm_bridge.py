"""MAF-backed implementation of :class:`SpecialistLlm`.

MAF 1.10.0's message types are ``agent_framework.Message`` (with
``role: str`` and ``contents: Sequence[Content]``) and
``agent_framework.Content`` (a flat class discriminated by ``type: str``,
e.g. ``"text"``, ``"function_call"``, ``"function_result"``).

The narrow contract from :mod:`egp_maf.agents.base` (``run_react`` +
``run_extraction``) maps naturally to MAF:

- ``run_react`` → ``OpenAIChatClient.as_agent(instructions=..., tools=...)``
  then ``agent.run(...)``. We parse the returned :class:`AgentResponse`
  into our neutral :class:`ToolCall` audit trail.
- ``run_extraction`` → ``OpenAIChatClient.get_response`` with
  ``ChatOptions(response_format=<schema>)`` (Structured Outputs).

Also ships :class:`StubSpecialistLlm` — the deterministic double the W05
unit tests use.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any

from agent_framework import ChatOptions, Content, Message
from agent_framework.openai import OpenAIChatClient

from egp_maf.agents.base import (
    SpecialistExtractionRequest,
    SpecialistLlm,
    SpecialistReactRequest,
    SpecialistReactResult,
    ToolCall,
)
from egp_maf.agents.extraction_schema import strict_extraction_schema
from egp_maf.telemetry import llm_span

_logger = logging.getLogger(__name__)


def _text_msg(role: str, text: str) -> Message:
    """Small factory: single-text-content :class:`Message` for the given role."""
    return Message(role=role, contents=[Content(type="text", text=text)])


# ── Real MAF-backed implementation ──────────────────────────────────


class MafSpecialistLlm(SpecialistLlm):
    """Production implementation of :class:`SpecialistLlm`.

    Uses one :class:`OpenAIChatClient` per pass. Both ReAct and extraction
    share the same client; MAF picks up ``response_format`` from the
    :class:`ChatOptions` for the extraction call.
    """

    def __init__(
        self,
        *,
        client: OpenAIChatClient,
        agent_id: str,
        temperature: float = 0.0,
    ) -> None:
        self._client = client
        self._agent_id = agent_id
        self._temperature = temperature

    async def run_react(self, request: SpecialistReactRequest) -> SpecialistReactResult:
        agent = self._client.as_agent(
            id=self._agent_id,
            instructions=request.system_prompt,
            tools=request.tools,
        )
        # W08: one span per LLM call. ``model`` name comes from the
        # ``agent_id`` (which encodes the specialist name in this bridge).
        with llm_span(model=self._agent_id, phase="react"):
            response = await agent.run(
                [_text_msg("user", request.user_message)],
                options=ChatOptions(temperature=self._temperature),
            )
        tool_calls = _extract_tool_calls_from_response(response)
        transcript = _flatten_transcript(response)
        return SpecialistReactResult(transcript=transcript, tool_calls=tool_calls)

    async def run_extraction(
        self, request: SpecialistExtractionRequest[Any]
    ) -> Any:
        messages: list[Message] = [
            _text_msg(m.get("role", "assistant"), m.get("content", ""))
            for m in request.transcript
        ]
        messages.append(_text_msg("user", request.extraction_instruction))

        # Structured Outputs is strict: it rejects the free-form objects
        # inside ``DBProvenance`` (``dict[str, Any]``). The model must not
        # author provenance anyway — it is built at query time by the
        # Repository and attached afterwards — so we ask for a
        # provenance-free variant and validate the reply back into the
        # real schema. See :mod:`egp_maf.agents.extraction_schema`.
        wire_schema = strict_extraction_schema(request.response_schema)

        with llm_span(
            model=self._agent_id, phase="extract", structured_output=True
        ):
            response = await self._client.get_response(
                messages,
                options=ChatOptions(
                    temperature=self._temperature,
                    response_format=wire_schema,
                ),
            )

        # Structured Outputs — MAF populates response.value with the
        # parsed model instance when ``response_format`` is a BaseModel.
        parsed = getattr(response, "value", None)
        if parsed is not None:
            return request.response_schema.model_validate(  # type: ignore[attr-defined]
                parsed.model_dump()
            )

        # Fallback: parse the string content as JSON (belt-and-braces).
        text = _extract_text_from_response(response)
        try:
            return request.response_schema.model_validate_json(text)  # type: ignore[attr-defined]
        except Exception as exc:
            _logger.warning(
                "specialist_llm.extraction_parse_fallback_failed",
                extra={"agent_id": self._agent_id, "error": str(exc)},
            )
            raise


def _extract_tool_calls_from_response(response: Any) -> list[ToolCall]:
    """Parse tool-call records from a MAF :class:`AgentResponse`.

    MAF flattens function calls into ``Content(type='function_call')`` and
    ``Content(type='function_result')``. We iterate all messages, pair
    each call with its result by ``call_id``, and produce one
    :class:`ToolCall` per pair.
    """
    call_map: dict[str, dict[str, Any]] = {}
    calls: list[ToolCall] = []

    for msg in getattr(response, "messages", None) or []:
        for content in getattr(msg, "contents", None) or []:
            ctype = getattr(content, "type", None)
            if ctype == "function_call":
                call_id = getattr(content, "call_id", None) or ""
                args = getattr(content, "arguments", None) or {}
                if isinstance(args, str):
                    try:
                        args = json.loads(args)
                    except json.JSONDecodeError:
                        args = {"raw": args}
                call_map[call_id] = {
                    "tool_name": getattr(content, "name", "unknown"),
                    "tool_parameters": dict(args) if isinstance(args, dict) else {},
                }
            elif ctype == "function_result":
                call_id = getattr(content, "call_id", None) or ""
                info = call_map.get(
                    call_id, {"tool_name": "unknown", "tool_parameters": {}}
                )
                exception = getattr(content, "exception", None)
                calls.append(
                    ToolCall(
                        tool_name=info["tool_name"],
                        tool_parameters=info["tool_parameters"],
                        tool_output=_parse_tool_output(getattr(content, "result", None)),
                        error=str(exception) if exception else None,
                    )
                )
    return calls


def _parse_tool_output(data: Any) -> list[dict[str, Any]]:
    """Coerce whatever the tool returned to a list of dict rows."""
    if data is None:
        return []
    if isinstance(data, list):
        return [x for x in data if isinstance(x, dict)]
    if isinstance(data, dict):
        return [data]
    if isinstance(data, str):
        try:
            parsed = json.loads(data)
        except json.JSONDecodeError:
            return [{"raw": data}]
        return _parse_tool_output(parsed)
    return [{"raw": str(data)}]


def _flatten_transcript(response: Any) -> list[dict[str, Any]]:
    """Serialise ``response.messages`` into ``{role, content}`` pairs
    for the extraction pass. Only ``type='text'`` content is captured;
    function-call turns are elided (the tool trace already covers them)."""
    out: list[dict[str, Any]] = []
    for msg in getattr(response, "messages", None) or []:
        text_parts = [
            c.text or ""
            for c in getattr(msg, "contents", None) or []
            if getattr(c, "type", None) == "text" and getattr(c, "text", None)
        ]
        if not text_parts:
            continue
        role = getattr(msg, "role", "assistant") or "assistant"
        out.append({"role": str(role), "content": "\n".join(text_parts).strip()})
    return out


def _extract_text_from_response(response: Any) -> str:
    """Extract the last assistant text from a MAF response."""
    text = getattr(response, "text", None)
    if text:
        return text
    for msg in reversed(getattr(response, "messages", None) or []):
        for content in getattr(msg, "contents", None) or []:
            if getattr(content, "type", None) == "text" and getattr(content, "text", None):
                return content.text
    return ""


# ── Stub for unit tests ─────────────────────────────────────────────


@dataclass
class StubSpecialistLlm:
    """Deterministic double used by every W05 unit test.

    Configure the two returns and it will pretend to have run both LLM
    passes without any I/O. Records what was asked so tests can assert
    on it.
    """

    react_result: SpecialistReactResult
    extraction_result: Any
    react_calls: list[SpecialistReactRequest] = field(default_factory=list)
    extraction_calls: list[SpecialistExtractionRequest[Any]] = field(
        default_factory=list
    )

    async def run_react(self, request: SpecialistReactRequest) -> SpecialistReactResult:
        self.react_calls.append(request)
        return self.react_result

    async def run_extraction(
        self, request: SpecialistExtractionRequest[Any]
    ) -> Any:
        self.extraction_calls.append(request)
        return self.extraction_result
