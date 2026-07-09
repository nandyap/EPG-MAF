"""Business-behaviour mode-parity harness (F08.2).

Runs the same workflow twice — once with ``ORCH_DISPATCH_MODE=sequential``,
once with ``ORCH_DISPATCH_MODE=parallel`` — with a deterministic
:class:`SpecialistRegistry` that produces the same typed outputs
regardless of dispatch order. Asserts structural equality on the final
:class:`ChatWorkflowState`.

Any diff produced by :func:`tests.support.parity_diff.deep_diff` is a
real regression: the workflow topology, joiner semantics, or reducer
logic disagrees across modes.

Ignore list (per :data:`~tests.support.parity_diff.DEFAULT_IGNORE_KEYS`):

- ``updated_at`` / ``produced_at`` / ``timestamp`` — wall-clock timing.
- ``router_iterations`` — parallel takes fewer.
- ``retrieved_at`` — provenance stamp.

Every other field must match byte-for-byte.
"""

from __future__ import annotations

import os
from typing import Any

import pytest

from egp_maf.config.settings import DispatchMode, Settings
from egp_maf.state.clinician_context import ClinicianContext
from egp_maf.workflow.decisions import (
    ChatRouterDecision,
    SpecialistDispatchSet,
    SpecialistName,
)
from egp_maf.workflow.router_llm import StubOrchRouterLlm, StubRouterLlm
from egp_maf.workflow.runtime import WorkflowRuntime
from egp_maf.workflow.state import ChatWorkflowState, SessionMessage

from tests.support.deterministic_specialists import build_deterministic_registry
from tests.support.parity_diff import deep_diff

os.environ.setdefault("LLM_API_KEY", "test")


# ── Helpers ──────────────────────────────────────────────────────────


def _settings(mode: DispatchMode, *, width: int = 5) -> Settings:
    return Settings(  # type: ignore[call-arg]
        ORCH_DISPATCH_MODE=mode,
        ORCH_MAX_FANOUT_WIDTH=width,
    )


def _chat_state(patient_id: str = "P1") -> ChatWorkflowState:
    return ChatWorkflowState(
        ctx=ClinicianContext.system(),
        patient_id=patient_id,
        thread_id="T1",
        messages=[
            SessionMessage(role="user", content="Give me the picture on this patient."),
        ],
    )


def _sequential_orch_llm(
    dispatch_order: list[SpecialistName],
) -> StubOrchRouterLlm:
    """One specialist per iteration, ending with an empty set."""
    decisions = [
        SpecialistDispatchSet(specialists=[name], reason=f"seq step {i + 1}")
        for i, name in enumerate(dispatch_order)
    ]
    decisions.append(SpecialistDispatchSet(specialists=[], reason="done"))
    return StubOrchRouterLlm(decisions)


def _parallel_orch_llm(
    dispatch_set: list[SpecialistName],
) -> StubOrchRouterLlm:
    """One iteration with the whole set, then end."""
    return StubOrchRouterLlm(
        [
            SpecialistDispatchSet(specialists=dispatch_set, reason="parallel fan-out"),
            SpecialistDispatchSet(specialists=[], reason="done"),
        ]
    )


async def _run(runtime: WorkflowRuntime, state: ChatWorkflowState) -> ChatWorkflowState:
    result = await runtime.run_turn(state)
    for out in result.get_outputs():
        if isinstance(out, ChatWorkflowState):
            return out
    raise AssertionError("Workflow yielded no ChatWorkflowState output")


def _dump_state(state: ChatWorkflowState) -> dict[str, Any]:
    """Serialise to a plain dict for :func:`deep_diff`. Drops ``ctx``
    because :class:`ClinicianContext` is `frozen=True` and identical
    across both runs anyway."""
    dump = state.model_dump(mode="json")
    dump.pop("ctx", None)
    return dump


# ── The harness ─────────────────────────────────────────────────────


_ALL: list[SpecialistName] = [
    "prs",
    "genomic_variants",
    "family_history",
    "pgx",
    "phenotype",
]


class TestModeParityFullFanout:
    """All 5 specialists dispatched — the parallel-mode canonical case."""

    async def test_sequential_and_parallel_produce_structurally_equal_output(
        self,
    ) -> None:
        # Fresh registry per run — the deterministic fixtures hold a
        # single ``ResultList`` per specialist and the pipeline mutates
        # it (provenance append). Reusing the registry across runs would
        # cause double provenance.
        seq_runtime = WorkflowRuntime(
            settings=_settings(DispatchMode.SEQUENTIAL, width=1),
            chat_router_llm=StubRouterLlm(
                ChatRouterDecision(needs_clinical_data=True, reason="need it")
            ),
            orch_router_llm=_sequential_orch_llm(_ALL),
            specialist_registry=build_deterministic_registry(),
        )
        par_runtime = WorkflowRuntime(
            settings=_settings(DispatchMode.PARALLEL, width=5),
            chat_router_llm=StubRouterLlm(
                ChatRouterDecision(needs_clinical_data=True, reason="need it")
            ),
            orch_router_llm=_parallel_orch_llm(_ALL),
            specialist_registry=build_deterministic_registry(),
        )

        seq_final = await _run(seq_runtime, _chat_state())
        par_final = await _run(par_runtime, _chat_state())

        # Every specialist ran in both modes.
        assert sorted(seq_final.agents_completed) == sorted(_ALL)
        assert sorted(par_final.agents_completed) == sorted(_ALL)

        diffs = deep_diff(_dump_state(seq_final), _dump_state(par_final))
        assert diffs == [], (
            "sequential vs parallel state diverged:\n  "
            + "\n  ".join(diffs)
        )


class TestModeParityPartialFanout:
    """Only 2 specialists — proves the harness catches order-independence
    at less-than-full fan-out too."""

    async def test_two_specialists_parity(self) -> None:
        selected: list[SpecialistName] = ["prs", "family_history"]

        seq_runtime = WorkflowRuntime(
            settings=_settings(DispatchMode.SEQUENTIAL, width=1),
            chat_router_llm=StubRouterLlm(
                ChatRouterDecision(needs_clinical_data=True, reason="need it")
            ),
            orch_router_llm=_sequential_orch_llm(selected),
            specialist_registry=build_deterministic_registry(),
        )
        par_runtime = WorkflowRuntime(
            settings=_settings(DispatchMode.PARALLEL, width=5),
            chat_router_llm=StubRouterLlm(
                ChatRouterDecision(needs_clinical_data=True, reason="need it")
            ),
            orch_router_llm=_parallel_orch_llm(selected),
            specialist_registry=build_deterministic_registry(),
        )

        seq_final = await _run(seq_runtime, _chat_state())
        par_final = await _run(par_runtime, _chat_state())

        assert sorted(seq_final.agents_completed) == sorted(selected)
        assert sorted(par_final.agents_completed) == sorted(selected)

        diffs = deep_diff(_dump_state(seq_final), _dump_state(par_final))
        assert diffs == [], (
            "sequential vs parallel state diverged (partial fanout):\n  "
            + "\n  ".join(diffs)
        )


class TestModeParityWidthSanitisation:
    """Sequential mode enforces |dispatch_set|=1 even if the LLM asks
    for more — validates F08.1 acceptance criterion 2 end-to-end."""

    async def test_sequential_downgrades_parallel_decision_to_singleton(
        self,
    ) -> None:
        seq_runtime = WorkflowRuntime(
            settings=_settings(DispatchMode.SEQUENTIAL, width=1),
            chat_router_llm=StubRouterLlm(
                ChatRouterDecision(needs_clinical_data=True, reason="need it")
            ),
            # LLM asks for [prs, pgx] on the first iteration; sequential
            # mode must downgrade to [prs] silently. Second iteration
            # gets [pgx]; third ends.
            orch_router_llm=StubOrchRouterLlm(
                [
                    SpecialistDispatchSet(
                        specialists=["prs", "pgx"], reason="LLM asked parallel"
                    ),
                    SpecialistDispatchSet(specialists=["pgx"], reason="then pgx"),
                    SpecialistDispatchSet(specialists=[], reason="done"),
                ]
            ),
            specialist_registry=build_deterministic_registry(),
        )
        final = await _run(seq_runtime, _chat_state())
        # Both prs and pgx completed, but never in the same iteration.
        assert sorted(final.agents_completed) == sorted(["prs", "pgx"])
        assert final.prs is not None
        assert final.pgx is not None


class TestModeParityWidthCap:
    """Parallel mode caps |dispatch_set| at ``ORCH_MAX_FANOUT_WIDTH``
    even if the LLM asks for more — validates F08.1 acceptance criterion
    3 end-to-end."""

    async def test_parallel_caps_at_configured_width(self) -> None:
        par_runtime = WorkflowRuntime(
            # width=2 while the LLM asks for 4 specialists.
            settings=_settings(DispatchMode.PARALLEL, width=2),
            chat_router_llm=StubRouterLlm(
                ChatRouterDecision(needs_clinical_data=True, reason="need it")
            ),
            orch_router_llm=StubOrchRouterLlm(
                [
                    SpecialistDispatchSet(
                        specialists=["prs", "pgx", "family_history", "phenotype"],
                        reason="LLM asked huge",
                    ),
                    SpecialistDispatchSet(
                        specialists=["family_history", "phenotype"],
                        reason="second half",
                    ),
                    SpecialistDispatchSet(specialists=[], reason="done"),
                ]
            ),
            specialist_registry=build_deterministic_registry(),
        )
        final = await _run(par_runtime, _chat_state())
        assert sorted(final.agents_completed) == sorted(
            ["prs", "pgx", "family_history", "phenotype"]
        )
