"""End-to-end tests for the Slice 3 ScopeGuard integration in ``POST /chat``.

Verifies the golden dataset G1 + G2 + G6 scenarios against the real
FastAPI stack (in-memory thread state, stub authenticator, real
ScopeGuard, stub workflow).
"""

from __future__ import annotations

import json
import os
from typing import Any

import pytest
from fastapi.testclient import TestClient

from egp_maf.api import create_app
from egp_maf.auth.audit import AuditEvent, AuditEventEmitter, AuditSink
from egp_maf.auth.authenticator import StubAuthenticator
from egp_maf.config.settings import Settings
from egp_maf.di.container import Container
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


class _RecordingAuditSink:
    """Captures every audit event for assertion."""

    def __init__(self) -> None:
        self.events: list[AuditEvent] = []

    def emit(self, event: AuditEvent) -> None:
        self.events.append(event)


def _make_container() -> tuple[Container, _RecordingAuditSink]:
    from egp_maf.agents.registry import SpecialistRegistry
    from tests.support.authz_doubles import OpenAuthzPolicy

    settings = Settings(  # type: ignore[call-arg]
        auth_stub_enabled=True,
        auth_required_role="Clinician",
    )
    sink = _RecordingAuditSink()
    audit = AuditEventEmitter(sink=sink)
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
    container = Container(
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
    return container, sink


def _token(**overrides: Any) -> str:
    claims = {
        "oid": "OID-1",
        "tid": "TID-1",
        "roles": ["Clinician"],
        "exp": 9999999999,
        **overrides,
    }
    return json.dumps(claims)


# ── Golden G1: cross-patient reference ─────────────────────────────


class TestGoldenG1CrossPatient:
    def test_returns_200_with_refusal_reply(self) -> None:
        container, _ = _make_container()
        client = TestClient(create_app(container))
        headers = {"Authorization": f"Bearer {_token()}"}

        resp = client.post(
            "/chat",
            headers=headers,
            json={
                "thread_id": "T-g1",
                "patient_id": "HG04001",
                "message": "What variants does patient HG04005 carry?",
            },
        )

        assert resp.status_code == 200, resp.text
        body = resp.json()
        # Refusal wording is present.
        assert "this chat is for patient" in body["reply"].lower()
        assert "start a new chat" in body["reply"].lower()
        assert "HG04001" in body["reply"]
        # No specialist ran.
        assert body["agents_completed"] == []
        assert body["prs"] is None
        assert body["pgx"] is None

    def test_emits_scope_violation_audit(self) -> None:
        container, sink = _make_container()
        client = TestClient(create_app(container))
        headers = {"Authorization": f"Bearer {_token()}"}

        client.post(
            "/chat",
            headers=headers,
            json={
                "thread_id": "T-g1",
                "patient_id": "HG04001",
                "message": "What variants does patient HG04005 carry?",
            },
        )

        scope_events = [e for e in sink.events if e.event == "scope.violation"]
        assert len(scope_events) == 1
        assert scope_events[0].patient_id == "HG04001"
        assert scope_events[0].outcome == "refused"
        assert scope_events[0].reason is not None
        assert scope_events[0].reason.startswith("cross_patient")


# ── Golden G2: cohort-scan intent ──────────────────────────────────


class TestGoldenG2CohortScan:
    def test_returns_200_with_cohort_refusal(self) -> None:
        container, _ = _make_container()
        client = TestClient(create_app(container))
        headers = {"Authorization": f"Bearer {_token()}"}

        resp = client.post(
            "/chat",
            headers=headers,
            json={
                "thread_id": "T-g2",
                "patient_id": "HG04001",
                "message": "How many patients in the database carry pathogenic variants?",
            },
        )

        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert "i can only report on patient" in body["reply"].lower()
        assert "can't scan across other patients" in body["reply"].lower()
        assert body["agents_completed"] == []


# ── Golden G6: annotation-safe cohort → workflow runs ──────────────


class TestGoldenG6AnnotationSafeAllowed:
    def test_workflow_runs_normally(self) -> None:
        container, sink = _make_container()
        client = TestClient(create_app(container))
        headers = {"Authorization": f"Bearer {_token()}"}

        resp = client.post(
            "/chat",
            headers=headers,
            json={
                "thread_id": "T-g6",
                "patient_id": "HG04005",
                "message": (
                    "How common is my BRCA1 variant in the EGP cohort compared "
                    "to the general population?"
                ),
            },
        )

        assert resp.status_code == 200, resp.text
        body = resp.json()
        # No refusal wording.
        assert "can't scan" not in body["reply"].lower()
        assert "this chat is for patient" not in body["reply"].lower()
        # No scope.violation audit event.
        assert not any(e.event == "scope.violation" for e in sink.events)


# ── Cross-cutting: legitimate query still works after Slices 1+2 ───


class TestScopeGuardDoesNotBreakLegitimateQueries:
    def test_normal_query_runs(self) -> None:
        container, _ = _make_container()
        client = TestClient(create_app(container))
        headers = {"Authorization": f"Bearer {_token()}"}

        resp = client.post(
            "/chat",
            headers=headers,
            json={
                "thread_id": "T-ok",
                "patient_id": "PGP001",
                "message": "What PRS does this patient have?",
            },
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        # No refusal wording.
        assert "start a new chat" not in body["reply"].lower()
