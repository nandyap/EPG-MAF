"""Router-LLM seams.

The chat router and orchestration router both call a small LLM whose only
job is to emit a structured decision. We keep the decision LLM behind a
narrow protocol so W04 can be tested without any real Compass calls, and
W05 can swap the implementation to a real ``ChatAgent``-backed router
without touching the executor code.

W05 concrete implementations will live under ``egp_maf.workflow.chat`` /
``egp_maf.workflow.orchestration`` alongside the real ChatAgent glue.
"""

from __future__ import annotations

from typing import Protocol

from egp_maf.workflow.decisions import ChatRouterDecision, SpecialistDispatchSet


class RouterLlm(Protocol):
    """Emits a :class:`ChatRouterDecision` for the current conversation
    state."""

    async def decide_chat_route(
        self,
        *,
        original_query: str,
        agents_completed: list[str],
        cached_domains: list[str],
    ) -> ChatRouterDecision: ...


class OrchRouterLlm(Protocol):
    """Emits a :class:`SpecialistDispatchSet` for the current orchestration
    state."""

    async def decide_dispatch(
        self,
        *,
        original_query: str,
        agents_completed: list[str],
        requested_diseases: list[str] | None,
    ) -> SpecialistDispatchSet: ...


# ── Stubs (W04 tests + W04 end-to-end smoke) ─────────────────────────


class StubRouterLlm:
    """Deterministic stub — returns a preset decision on every call.

    Used in W04 tests and by the DI container until W05 wires the real
    Compass-backed router in ``build_container``.
    """

    def __init__(self, decision: ChatRouterDecision) -> None:
        self._decision = decision

    async def decide_chat_route(
        self,
        *,
        original_query: str,
        agents_completed: list[str],
        cached_domains: list[str],
    ) -> ChatRouterDecision:
        return self._decision


class StubOrchRouterLlm:
    """Deterministic stub — returns a preset sequence of decisions.

    On the ``i``-th call it returns the ``i``-th entry; if the sequence is
    exhausted it returns an empty (terminal) :class:`SpecialistDispatchSet`.
    """

    def __init__(self, decisions: list[SpecialistDispatchSet]) -> None:
        self._decisions = list(decisions)
        self._call_count = 0

    async def decide_dispatch(
        self,
        *,
        original_query: str,
        agents_completed: list[str],
        requested_diseases: list[str] | None,
    ) -> SpecialistDispatchSet:
        if self._call_count >= len(self._decisions):
            self._call_count += 1
            return SpecialistDispatchSet(specialists=[], reason="stub-exhausted")
        decision = self._decisions[self._call_count]
        self._call_count += 1
        return decision

    @property
    def call_count(self) -> int:
        return self._call_count
