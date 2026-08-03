"""Slice 2 tests: DELETE, unfiltered GET, title auto-population."""

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
from egp_maf.infrastructure.compass_client import LlmClientFactory
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


def _make_container(*, auth_stub_enabled: bool = True) -> Container:
    from egp_maf.agents.registry import SpecialistRegistry
    from tests.support.authz_doubles import OpenAuthzPolicy

    settings = Settings(  # type: ignore[call-arg]
        auth_stub_enabled=auth_stub_enabled,
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


# ── DELETE /threads/{thread_id} ────────────────────────────────────


class TestDeleteThread:
    def test_owner_delete_returns_204(self) -> None:
        client = TestClient(create_app(_make_container()))
        headers = {"Authorization": f"Bearer {_token()}"}

        create = client.post(
            "/threads", headers=headers, json={"patient_id": "PGP001"}
        )
        thread_id = create.json()["thread_id"]

        resp = client.delete(f"/threads/{thread_id}", headers=headers)

        assert resp.status_code == 204
        # Content-Length must be 0.
        assert resp.text == ""

    def test_unknown_thread_returns_404(self) -> None:
        client = TestClient(create_app(_make_container()))
        headers = {"Authorization": f"Bearer {_token()}"}

        resp = client.delete("/threads/does-not-exist", headers=headers)

        assert resp.status_code == 404
        assert resp.json()["error_code"] == "patient_unavailable"

    def test_delete_removes_from_list(self) -> None:
        client = TestClient(create_app(_make_container()))
        headers = {"Authorization": f"Bearer {_token()}"}

        create = client.post(
            "/threads", headers=headers, json={"patient_id": "PGP001"}
        )
        thread_id = create.json()["thread_id"]

        client.delete(f"/threads/{thread_id}", headers=headers)
        resp = client.get(
            "/threads", headers=headers, params={"patient_id": "PGP001"}
        )

        assert resp.status_code == 200
        assert resp.json()["count"] == 0

    def test_other_clinicians_thread_returns_404(self) -> None:
        """Alice's thread cannot be deleted by Bob — 404, not 403,
        so Bob cannot enumerate Alice's thread ids."""
        client = TestClient(create_app(_make_container()))

        alice = {"Authorization": f"Bearer {_token(oid='ALICE')}"}
        bob = {"Authorization": f"Bearer {_token(oid='BOB')}"}

        create = client.post("/threads", headers=alice, json={"patient_id": "PGP001"})
        thread_id = create.json()["thread_id"]

        resp = client.delete(f"/threads/{thread_id}", headers=bob)
        assert resp.status_code == 404


# ── GET /threads without patient_id ────────────────────────────────


class TestListThreadsUnfiltered:
    def test_returns_all_recent_threads(self) -> None:
        client = TestClient(create_app(_make_container()))
        headers = {"Authorization": f"Bearer {_token()}"}

        client.post("/threads", headers=headers, json={"patient_id": "PGP001"})
        client.post("/threads", headers=headers, json={"patient_id": "PGP001"})
        client.post("/threads", headers=headers, json={"patient_id": "PGP002"})

        resp = client.get("/threads", headers=headers)

        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["count"] == 3
        assert {t["patient_id"] for t in body["threads"]} == {"PGP001", "PGP002"}

    def test_returns_only_current_clinicians_threads(self) -> None:
        client = TestClient(create_app(_make_container()))
        alice = {"Authorization": f"Bearer {_token(oid='ALICE')}"}
        bob = {"Authorization": f"Bearer {_token(oid='BOB')}"}

        client.post("/threads", headers=alice, json={"patient_id": "PGP001"})
        client.post("/threads", headers=bob, json={"patient_id": "PGP001"})

        resp_alice = client.get("/threads", headers=alice)
        assert resp_alice.json()["count"] == 1
        resp_bob = client.get("/threads", headers=bob)
        assert resp_bob.json()["count"] == 1


# ── Title field ────────────────────────────────────────────────────


class TestThreadTitle:
    def test_explicit_title_on_post_threads(self) -> None:
        client = TestClient(create_app(_make_container()))
        headers = {"Authorization": f"Bearer {_token()}"}

        resp = client.post(
            "/threads",
            headers=headers,
            json={"patient_id": "PGP001", "title": "Follow-up: BRCA1 counselling"},
        )

        assert resp.status_code == 200, resp.text
        assert resp.json()["title"] == "Follow-up: BRCA1 counselling"

    def test_no_title_when_not_provided(self) -> None:
        client = TestClient(create_app(_make_container()))
        headers = {"Authorization": f"Bearer {_token()}"}

        resp = client.post(
            "/threads", headers=headers, json={"patient_id": "PGP001"}
        )

        assert resp.json()["title"] is None

    def test_auto_title_from_first_message_on_auto_create(self) -> None:
        """Dev-mode ``POST /chat`` with an unknown thread_id auto-creates
        the thread; the title is derived from the message.
        """
        client = TestClient(create_app(_make_container()))
        headers = {"Authorization": f"Bearer {_token()}"}

        client.post(
            "/chat",
            headers=headers,
            json={
                "thread_id": "T-auto",
                "patient_id": "PGP001",
                "message": "What PRS does this patient have?",
            },
        )

        # Listing shows the title.
        resp = client.get(
            "/threads", headers=headers, params={"patient_id": "PGP001"}
        )
        assert resp.status_code == 200
        item = resp.json()["threads"][0]
        assert item["title"] == "What PRS does this patient have?"

    def test_title_truncated_at_60_chars(self) -> None:
        client = TestClient(create_app(_make_container()))
        headers = {"Authorization": f"Bearer {_token()}"}

        long_msg = "x" * 200
        client.post(
            "/chat",
            headers=headers,
            json={
                "thread_id": "T-long",
                "patient_id": "PGP001",
                "message": long_msg,
            },
        )

        resp = client.get(
            "/threads", headers=headers, params={"patient_id": "PGP001"}
        )
        title = resp.json()["threads"][0]["title"]
        assert title is not None
        # 60 chars max, last char is the ellipsis.
        assert len(title) == 60
        assert title.endswith("\u2026")
