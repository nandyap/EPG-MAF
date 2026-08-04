"""Slice 4 integration test: every scope_guard-domain golden item runs
end-to-end through the FastAPI stack and passes its shape scorer.

Content-quality scorers (fact_substring / forbidden_substring) are
tolerated as expected-fails when the item carries
``expected_fail_reason`` — those require the real Compass LLM to
synthesise a clinical narrative.
"""

from __future__ import annotations

import json
import os
from typing import Any

import pytest
from fastapi.testclient import TestClient

from egp_maf.api import create_app
from egp_maf.auth.audit import AuditEventEmitter, NullAuditSink
from egp_maf.auth.authenticator import StubAuthenticator
from egp_maf.config.settings import Settings
from egp_maf.di.container import Container
from egp_maf.evals.golden import load_golden_set
from egp_maf.evals.harness import run_golden_item
from egp_maf.infrastructure.compass_client import LlmClientFactory
from egp_maf.security import ScopeGuard
from egp_maf.services.provenance import ProvenanceService
from egp_maf.services.thread_state_memory import InMemoryThreadStateProvider
from egp_maf.telemetry import NullMetricEmitter, build_telemetry_provider
from egp_maf.workflow.decisions import ChatRouterDecision, SpecialistDispatchSet
from egp_maf.workflow.router_llm import StubOrchRouterLlm, StubRouterLlm
from egp_maf.workflow.runtime import WorkflowRuntime

pytestmark = pytest.mark.unit

os.environ.setdefault("LLM_API_KEY", "test")


class _NoopFactory:
    async def open(self) -> None: ...
    async def close(self) -> None: ...


class _NoopPrompts:
    async def warm_cache(self) -> None: ...
    def get(self, name: str) -> str:
        return f"prompt:{name}"


def _make_container() -> Container:
    from egp_maf.agents.registry import SpecialistRegistry
    from tests.support.authz_doubles import OpenAuthzPolicy

    settings = Settings(  # type: ignore[call-arg]
        auth_stub_enabled=True,
        auth_required_role="Clinician",
    )
    audit = AuditEventEmitter(sink=NullAuditSink())
    empty_registry = SpecialistRegistry()
    runtime = WorkflowRuntime(
        settings=settings,
        chat_router_llm=StubRouterLlm(
            ChatRouterDecision(needs_clinical_data=False, reason="test")
        ),
        orch_router_llm=StubOrchRouterLlm(
            [SpecialistDispatchSet(specialists=[], reason="test")]
        ),
        specialist_registry=empty_registry,
    )
    return Container(
        settings=settings,
        db_pool_factory=_NoopFactory(),  # type: ignore[arg-type]
        cosmos_client_factory=_NoopFactory(),  # type: ignore[arg-type]
        llm_client_factory=LlmClientFactory(
            settings, client_constructor=lambda **_: object()
        ),
        prompt_service=_NoopPrompts(),  # type: ignore[arg-type]
        thread_state_provider=InMemoryThreadStateProvider(),  # type: ignore[arg-type]
        provenance_service=ProvenanceService(),
        authz_policy=OpenAuthzPolicy(),
        audit_emitter=audit,
        authenticator=StubAuthenticator(settings=settings, audit=audit),
        telemetry_provider=build_telemetry_provider(settings),
        metric_emitter=NullMetricEmitter(),
        specialist_registry=empty_registry,
        workflow_runtime=runtime,
        scope_guard=ScopeGuard(),
    )


def _token(**overrides: Any) -> str:
    claims = {
        "oid": "OID-1",
        "tid": "TID-1",
        "roles": ["Clinician"],
        "exp": 9999999999,
        **overrides,
    }
    return json.dumps(claims)


@pytest.fixture
def client() -> TestClient:
    return TestClient(create_app(_make_container()))


def _fresh_client() -> TestClient:
    """Build a fresh app + container for one golden-item run.

    The underlying MAF workflow keeps event-queue state bound to the
    asyncio loop of its first request; ``TestClient`` uses a new loop
    per ``post()``. Reusing one client across many golden items
    produces "Queue bound to different event loop" errors. A fresh
    container per item side-steps that entirely at the cost of a bit
    of setup time.
    """
    return TestClient(create_app(_make_container()))


class TestScopeGuardFullGolden:
    """All 11 scope_guard-domain items (G1–G9 + R23 + R24) pass shape today."""

    def test_every_refusal_item_produces_expected_wording(self) -> None:
        items = [
            i for i in load_golden_set()
            if i.domain == "scope_guard" and i.expected_refusal_substrings
        ]
        assert items, "no scope_guard refusal items found"

        failures: list[tuple[str, str]] = []
        for item in items:
            result = run_golden_item(_fresh_client(), item, token=_token())
            if not result.passed:
                failures.append((item.id, str(result.scores)))
        assert not failures, f"Refusal items failing shape: {failures}"

    def test_every_cohort_allowed_item_reaches_workflow(self) -> None:
        """G6/G7/G9 must NOT produce refusal wording — they map to
        annotation lookups the specialist should be able to answer.
        """
        items = [
            i for i in load_golden_set()
            if i.domain == "scope_guard" and "cohort_allowed" in i.tags
        ]
        assert items, "no cohort_allowed items found"

        failures: list[str] = []
        for item in items:
            result = run_golden_item(_fresh_client(), item, token=_token())
            # Refusal wording MUST NOT appear.
            refusal_leaked = any(
                s in result.reply.lower()
                for s in ("start a new chat", "can't scan across other patients")
            )
            if refusal_leaked:
                failures.append(item.id)
        assert not failures, (
            f"cohort_allowed items showed refusal wording: {failures}"
        )
