"""Tests for :mod:`egp_maf.api.app`.

Uses FastAPI's :class:`TestClient` to drive the app end-to-end with
a real Container built from stubs — same shape as `test_di_container.py`.
"""

from __future__ import annotations

import json
import os
from typing import Any

import pytest
from fastapi.testclient import TestClient

from egp_maf.api import create_app
from egp_maf.auth.authenticator import StubAuthenticator
from egp_maf.config.settings import Settings
from egp_maf.di.container import Container
from egp_maf.infrastructure.compass_client import LlmClientFactory
from egp_maf.services.provenance import ProvenanceService
from egp_maf.services.thread_state import ThreadStateProvider
from egp_maf.telemetry import NullMetricEmitter, build_telemetry_provider
from egp_maf.workflow.decisions import ChatRouterDecision, SpecialistDispatchSet
from egp_maf.workflow.router_llm import StubOrchRouterLlm, StubRouterLlm
from egp_maf.workflow.runtime import WorkflowRuntime

pytestmark = pytest.mark.unit

os.environ.setdefault("LLM_API_KEY", "test")


# ── Minimal doubles (same shape as tests/unit/test_di_container.py) ─


class _NoopFactory:
    def __init__(self) -> None:
        self.opened = False
        self.closed = False

    async def open(self) -> None:
        self.opened = True

    async def close(self) -> None:
        self.closed = True


class _NoopPrompts:
    def __init__(self) -> None:
        self.warmed = False

    async def warm_cache(self) -> None:
        self.warmed = True

    def get(self, name: str) -> str:
        return f"prompt:{name}"


def _make_container() -> Container:
    from egp_maf.agents.registry import SpecialistRegistry
    from egp_maf.auth.audit import AuditEventEmitter, NullAuditSink
    from tests.support.authz_doubles import OpenAuthzPolicy

    settings = Settings(  # type: ignore[call-arg]
        auth_stub_enabled=True,
        auth_required_role="Clinician",
    )
    db = _NoopFactory()
    cosmos = _NoopFactory()
    llm_factory = LlmClientFactory(
        settings, client_constructor=lambda **_: object()
    )
    prompt = _NoopPrompts()
    thread_state = ThreadStateProvider(cosmos, settings)  # type: ignore[arg-type]

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

    audit_emitter = AuditEventEmitter(sink=NullAuditSink())

    return Container(
        settings=settings,
        db_pool_factory=db,  # type: ignore[arg-type]
        cosmos_client_factory=cosmos,  # type: ignore[arg-type]
        llm_client_factory=llm_factory,
        prompt_service=prompt,  # type: ignore[arg-type]
        thread_state_provider=thread_state,
        provenance_service=ProvenanceService(),
        authz_policy=OpenAuthzPolicy(),
        audit_emitter=audit_emitter,
        authenticator=StubAuthenticator(settings=settings, audit=audit_emitter),
        telemetry_provider=build_telemetry_provider(settings),
        metric_emitter=NullMetricEmitter(),
        specialist_registry=empty_registry,
        workflow_runtime=runtime,
    )


@pytest.fixture
def client() -> TestClient:
    return TestClient(create_app(_make_container()))


# ── The token the StubAuthenticator accepts ────────────────────────


def _valid_token(**overrides: Any) -> str:
    claims = {
        "oid": "OID-1",
        "tid": "TID-1",
        "roles": ["Clinician"],
        "exp": 9999999999,
        **overrides,
    }
    return json.dumps(claims)


# ── Health ────────────────────────────────────────────────────────


class TestHealthz:
    def test_returns_ok(self, client: TestClient) -> None:
        resp = client.get("/healthz")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "ok"
        assert body["service"] == "egp-window"


# ── Chat auth ─────────────────────────────────────────────────────


class TestChatAuth:
    def test_missing_bearer_returns_401(self, client: TestClient) -> None:
        resp = client.post(
            "/chat",
            json={"thread_id": "T", "patient_id": "P", "message": "hi"},
        )
        assert resp.status_code == 401
        body = resp.json()
        assert body["error_code"] == "auth_failed"

    def test_malformed_bearer_returns_401(self, client: TestClient) -> None:
        resp = client.post(
            "/chat",
            headers={"Authorization": "Basic xxx"},
            json={"thread_id": "T", "patient_id": "P", "message": "hi"},
        )
        assert resp.status_code == 401

    def test_empty_bearer_returns_401(self, client: TestClient) -> None:
        resp = client.post(
            "/chat",
            headers={"Authorization": "Bearer "},
            json={"thread_id": "T", "patient_id": "P", "message": "hi"},
        )
        assert resp.status_code == 401

    def test_missing_role_returns_401(self, client: TestClient) -> None:
        resp = client.post(
            "/chat",
            headers={"Authorization": f"Bearer {_valid_token(roles=[])}"},
            json={"thread_id": "T", "patient_id": "P", "message": "hi"},
        )
        assert resp.status_code == 401


# ── Chat happy path ───────────────────────────────────────────────


class TestChatHappyPath:
    def test_returns_200_with_stubbed_workflow(
        self, client: TestClient
    ) -> None:
        resp = client.post(
            "/chat",
            headers={"Authorization": f"Bearer {_valid_token()}"},
            json={
                "thread_id": "T-1",
                "patient_id": "P-1",
                "message": "What PRS does the patient have?",
            },
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["thread_id"] == "T-1"
        assert body["patient_id"] == "P-1"
        # Stubbed workflow doesn't run any specialists.
        assert body["agents_completed"] == []
        # Response body has exactly the keys the schema declares.
        assert set(body.keys()) == {
            "thread_id",
            "patient_id",
            "trace_id",
            "reply",
            "agents_completed",
            "prs",
            "genomic_variants",
            "family_history",
            "pgx",
            "phenotype",
        }


# ── Chat validation ───────────────────────────────────────────────


class TestChatValidation:
    def test_missing_field_returns_422(self, client: TestClient) -> None:
        # FastAPI's default handler returns 422 for schema-validation
        # failures on the request body. We do NOT re-wrap that (spec
        # convention).
        resp = client.post(
            "/chat",
            headers={"Authorization": f"Bearer {_valid_token()}"},
            json={"thread_id": "T", "patient_id": "P"},  # message missing
        )
        assert resp.status_code == 422

    def test_extra_field_returns_422(self, client: TestClient) -> None:
        resp = client.post(
            "/chat",
            headers={"Authorization": f"Bearer {_valid_token()}"},
            json={
                "thread_id": "T",
                "patient_id": "P",
                "message": "hi",
                "unknown_field": "x",
            },
        )
        assert resp.status_code == 422


# ── Error envelope shape ──────────────────────────────────────────


class TestErrorEnvelope:
    def test_401_carries_error_code_message_trace_id(
        self, client: TestClient
    ) -> None:
        resp = client.post(
            "/chat",
            json={"thread_id": "T", "patient_id": "P", "message": "hi"},
        )
        assert resp.status_code == 401
        body = resp.json()
        assert set(body.keys()) == {"error_code", "message", "trace_id"}
