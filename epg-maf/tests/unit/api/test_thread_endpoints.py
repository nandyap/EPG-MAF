"""Tests for the Slice 1 thread endpoints — ``POST /threads``, ``GET /threads``,
and the ``POST /chat`` thread-pin enforcement.

Reuses the same DI-container stub shape as ``test_app.py`` but with:

- An :class:`InMemoryThreadStateProvider` (already the default in
  ``test_app.py``).
- An :class:`AllowlistAuthzPolicy` seeded from a temp JSON file so we
  can exercise the 404-for-not-authorised path deterministically.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from egp_maf.api import create_app
from egp_maf.auth.audit import AuditEventEmitter, NullAuditSink
from egp_maf.auth.authenticator import StubAuthenticator
from egp_maf.config.settings import Settings
from egp_maf.di.container import Container
from egp_maf.infrastructure.compass_client import LlmClientFactory
from egp_maf.services.authz import AllowlistAuthzPolicy
from egp_maf.services.provenance import ProvenanceService
from egp_maf.services.thread_state_memory import InMemoryThreadStateProvider
from egp_maf.telemetry import NullMetricEmitter, build_telemetry_provider
from egp_maf.workflow.decisions import ChatRouterDecision, SpecialistDispatchSet
from egp_maf.workflow.router_llm import StubOrchRouterLlm, StubRouterLlm
from egp_maf.workflow.runtime import WorkflowRuntime

pytestmark = pytest.mark.unit

os.environ.setdefault("LLM_API_KEY", "test")


# ── Minimal doubles ────────────────────────────────────────────────


class _NoopFactory:
    async def open(self) -> None: ...
    async def close(self) -> None: ...


class _NoopPrompts:
    async def warm_cache(self) -> None: ...
    def get(self, name: str) -> str:
        return f"prompt:{name}"


def _write_allowlist(tmp_path: Path) -> Path:
    """Return a path to a v1 allowlist that gives clinician OID-1 access
    to PGP001 only.
    """
    payload = {
        "version": 1,
        "clinicians": {"OID-1": ["PGP001"]},
        "admins": [],
    }
    p = tmp_path / "allowlist.json"
    p.write_text(json.dumps(payload))
    return p


def _make_container(
    *,
    allowlist_path: Path | None = None,
    auth_stub_enabled: bool = True,
) -> Container:
    from egp_maf.agents.registry import SpecialistRegistry
    from tests.support.authz_doubles import OpenAuthzPolicy

    settings = Settings(  # type: ignore[call-arg]
        auth_stub_enabled=auth_stub_enabled,
        auth_required_role="Clinician",
        authz_allowlist_path=str(allowlist_path) if allowlist_path else None,
    )
    audit = AuditEventEmitter(sink=NullAuditSink())
    if allowlist_path is not None:
        policy: Any = AllowlistAuthzPolicy(allowlist_path, audit=audit)
    else:
        policy = OpenAuthzPolicy()

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
        authz_policy=policy,
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


# ── POST /threads ──────────────────────────────────────────────────


class TestCreateThread:
    def test_happy_path_returns_thread_id(self) -> None:
        client = TestClient(create_app(_make_container()))

        resp = client.post(
            "/threads",
            headers={"Authorization": f"Bearer {_token()}"},
            json={"patient_id": "PGP001"},
        )

        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["patient_id"] == "PGP001"
        assert body["thread_id"].startswith("T-")
        assert "created_at" in body

    def test_missing_bearer_returns_401(self, tmp_path: Path) -> None:
        client = TestClient(create_app(_make_container()))
        resp = client.post("/threads", json={"patient_id": "PGP001"})
        assert resp.status_code == 401

    def test_unauthorised_patient_returns_404_patient_unavailable(
        self, tmp_path: Path
    ) -> None:
        # OID-1 is only allowed to see PGP001 per the allowlist.
        allowlist = _write_allowlist(tmp_path)
        client = TestClient(create_app(_make_container(allowlist_path=allowlist)))

        resp = client.post(
            "/threads",
            headers={"Authorization": f"Bearer {_token()}"},
            json={"patient_id": "PGP999"},
        )

        assert resp.status_code == 404
        body = resp.json()
        assert body["error_code"] == "patient_unavailable"
        # Enumeration defence: message must not distinguish between
        # "does not exist" and "not authorised".
        assert "not available" in body["message"].lower()

    def test_empty_patient_id_returns_422(self) -> None:
        client = TestClient(create_app(_make_container()))
        resp = client.post(
            "/threads",
            headers={"Authorization": f"Bearer {_token()}"},
            json={"patient_id": ""},
        )
        # Pydantic validation → 400 via our handler.
        assert resp.status_code in (400, 422)


# ── GET /threads ───────────────────────────────────────────────────


class TestListThreads:
    def test_returns_only_current_clinicians_threads(self) -> None:
        client = TestClient(create_app(_make_container()))
        headers = {"Authorization": f"Bearer {_token()}"}

        # Create 2 threads for OID-1 / PGP001 and 1 for OID-1 / PGP002.
        for _ in range(2):
            client.post("/threads", headers=headers, json={"patient_id": "PGP001"})
        client.post("/threads", headers=headers, json={"patient_id": "PGP002"})

        resp = client.get(
            "/threads",
            headers=headers,
            params={"patient_id": "PGP001"},
        )

        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["count"] == 2
        assert all(t["patient_id"] == "PGP001" for t in body["threads"])


# ── POST /chat — thread pin enforcement ────────────────────────────


class TestChatThreadPinning:
    def test_matching_patient_returns_200(self) -> None:
        client = TestClient(create_app(_make_container()))
        headers = {"Authorization": f"Bearer {_token()}"}

        create = client.post(
            "/threads", headers=headers, json={"patient_id": "PGP001"}
        )
        thread_id = create.json()["thread_id"]

        resp = client.post(
            "/chat",
            headers=headers,
            json={
                "thread_id": thread_id,
                "patient_id": "PGP001",
                "message": "hello",
            },
        )
        assert resp.status_code == 200, resp.text

    def test_mismatched_patient_returns_409(self) -> None:
        client = TestClient(create_app(_make_container()))
        headers = {"Authorization": f"Bearer {_token()}"}

        create = client.post(
            "/threads", headers=headers, json={"patient_id": "PGP001"}
        )
        thread_id = create.json()["thread_id"]

        # Wrong patient on an existing thread.
        resp = client.post(
            "/chat",
            headers=headers,
            json={
                "thread_id": thread_id,
                "patient_id": "PGP999",
                "message": "hello",
            },
        )
        assert resp.status_code == 409
        body = resp.json()
        assert body["error_code"] == "thread_patient_mismatch"

    def test_unknown_thread_auto_creates_in_dev_mode(self) -> None:
        """Dev mode (``auth_stub_enabled=True``) auto-creates a missing
        thread on ``POST /chat`` so the smoke server just works.
        """
        client = TestClient(create_app(_make_container()))
        headers = {"Authorization": f"Bearer {_token()}"}

        resp = client.post(
            "/chat",
            headers=headers,
            json={
                "thread_id": "T-brand-new",
                "patient_id": "PGP001",
                "message": "hello",
            },
        )
        assert resp.status_code == 200, resp.text

    def test_second_chat_after_auto_create_enforces_pin(self) -> None:
        """After auto-creating a thread pinned to PGP001, a second
        ``POST /chat`` with a different ``patient_id`` must 409.
        """
        client = TestClient(create_app(_make_container()))
        headers = {"Authorization": f"Bearer {_token()}"}

        client.post(
            "/chat",
            headers=headers,
            json={
                "thread_id": "T-brand-new",
                "patient_id": "PGP001",
                "message": "hello",
            },
        )
        resp = client.post(
            "/chat",
            headers=headers,
            json={
                "thread_id": "T-brand-new",
                "patient_id": "PGP002",
                "message": "hello again",
            },
        )
        assert resp.status_code == 409
