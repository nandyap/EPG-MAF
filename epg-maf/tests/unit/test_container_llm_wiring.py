"""Guards the composition root's LLM wiring.

Regression: :func:`build_container` defaulted every LLM stage to a stub,
and :mod:`egp_maf.api.main` calls it with no arguments. The deployed
service therefore:

- never asked the chat router whether clinical data was needed
  (``StubRouterLlm`` always answered "no"),
- never dispatched a specialist (``StubOrchRouterLlm`` ends immediately),
- answered every clinical question with ``STUB: <query>``.

The workflow, the specialists and the router adapters were all correct —
nothing connected them to the entrypoint. These tests fail if the
production default regresses to stubs.

No network call is made: the LLM client constructor is faked, and the
adapters are only constructed, never invoked.
"""

from __future__ import annotations

import pytest

from egp_maf.config.settings import Settings
from egp_maf.di.container import build_container
from egp_maf.workflow.chat.synthesize_response import StubSynthesisLlm
from egp_maf.workflow.router_llm import StubOrchRouterLlm, StubRouterLlm
from egp_maf.workflow.router_llm_maf import MafChatRouterLlm, MafOrchRouterLlm
from egp_maf.workflow.synthesis_llm_maf import MafSynthesisLlm

pytestmark = pytest.mark.unit


def _settings() -> Settings:
    return Settings(
        LLM_API_KEY="test-key",
        COSMOS_KEY="test-cosmos-key",
        EGP_AUTH_STUB_ENABLED=True,
    )


def _stages(container) -> tuple[object, object, object]:
    """Return the (chat_router, orch_router, synthesis) instances actually
    wired into the built workflows."""
    runtime = container.workflow_runtime
    chat_wf = runtime.chat_workflow
    orch_wf = runtime.orchestration_workflow

    def _find(workflow, attr: str) -> object | None:
        for executor in workflow.executors.values():
            candidate = getattr(executor, attr, None)
            if candidate is not None:
                return candidate
        return None

    return (
        _find(chat_wf, "_router_llm"),
        _find(orch_wf, "_router_llm"),
        _find(chat_wf, "_synthesis_llm"),
    )


class TestProductionDefaults:
    def test_defaults_to_real_compass_backed_stages(self) -> None:
        """The core regression — production must not get stubs."""
        container = build_container(_settings())

        chat_router, orch_router, synthesis = _stages(container)

        assert isinstance(chat_router, MafChatRouterLlm)
        assert isinstance(orch_router, MafOrchRouterLlm)
        assert isinstance(synthesis, MafSynthesisLlm)

    def test_all_five_specialists_are_registered(self) -> None:
        container = build_container(_settings())

        assert container.specialist_registry.names() == [
            "family_history",
            "genomic_variants",
            "pgx",
            "phenotype",
            "prs",
        ]


class TestStubMode:
    def test_opt_in_stub_mode_still_available(self) -> None:
        """Offline smoke runs need the stub path — but only on request."""
        container = build_container(_settings(), use_stub_llms=True)

        chat_router, orch_router, synthesis = _stages(container)

        assert isinstance(chat_router, StubRouterLlm)
        assert isinstance(orch_router, StubOrchRouterLlm)
        assert isinstance(synthesis, StubSynthesisLlm)


class TestInjectionSeams:
    def test_individual_stages_can_be_overridden(self) -> None:
        injected = StubRouterLlm.__new__(StubRouterLlm)

        container = build_container(_settings(), chat_router_llm=injected)

        chat_router, orch_router, synthesis = _stages(container)
        assert chat_router is injected
        # The stages not overridden stay real.
        assert isinstance(orch_router, MafOrchRouterLlm)
        assert isinstance(synthesis, MafSynthesisLlm)
