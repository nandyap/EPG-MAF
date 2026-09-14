"""``POST /threads`` rejects a patient id that does not exist.

Before this, the endpoint had no existence check at all. The comment
that stood in its place said the allowlist doubled as one — true for an
ordinary clinician (unlisted and non-existent both 404, the B-005
enumeration defence), false for an **admin**, because
``_Allowlist.can_read`` returns ``True`` before any per-patient check.

``demo`` is an admin in the dev allowlist. On 2026-09-10 a customer
typed ``HG0007`` for ``HG04007``, got a thread, and the assistant
answered with three fabricated variants.

The admin case is the one that matters, so it gets its own test.
"""

from __future__ import annotations

import json
import os
from typing import Any

import pytest
from fastapi.testclient import TestClient

os.environ.setdefault("LLM_API_KEY", "test")

from egp_maf.agents.registry import SpecialistRegistry
from egp_maf.api import create_app
from egp_maf.auth.audit import AuditEventEmitter, NullAuditSink
from egp_maf.auth.authenticator import StubAuthenticator
from egp_maf.config.settings import Settings
from egp_maf.di.container import Container
from egp_maf.errors import DatabaseUnavailable
from egp_maf.infrastructure.compass_client import LlmClientFactory
from egp_maf.security import ScopeGuard
from egp_maf.services.provenance import ProvenanceService
from egp_maf.state.clinician_context import ClinicianContext
from egp_maf.telemetry import NullMetricEmitter, build_telemetry_provider
from egp_maf.workflow.decisions import ChatRouterDecision, SpecialistDispatchSet
from egp_maf.workflow.router_llm import StubOrchRouterLlm, StubRouterLlm
from egp_maf.workflow.runtime import WorkflowRuntime
from tests.support.authz_doubles import OpenAuthzPolicy

pytestmark = pytest.mark.unit


class _NoopFactory:
    async def open(self) -> None: ...
    async def close(self) -> None: ...


class _NoopPrompts:
    async def warm(self) -> None: ...
    def get(self, name: str) -> str:
        return "prompt"


class _InMemoryThreads:
    def __init__(self) -> None:
        self.created: list[str] = []

    async def create_thread(
        self, *, clinician_id: str, tenant_id: str, patient_id: str, title: Any
    ) -> Any:
        from datetime import datetime, timezone
        from types import SimpleNamespace

        self.created.append(patient_id)
        return SimpleNamespace(
            thread_id=f"T-{len(self.created)}",
            patient_id=patient_id,
            title=title,
            created_at=datetime.now(timezone.utc),
        )


class _PatientRepoDouble:
    """Stands in for :class:`PatientRepository`."""

    def __init__(self, *, known: set[str] | None = None, raises: Exception | None = None):
        self._known = known or set()
        self._raises = raises
        self.calls: list[str] = []

    async def exists(self, ctx: ClinicianContext, patient_id: str) -> bool:
        self.calls.append(patient_id)
        if self._raises is not None:
            raise self._raises
        return patient_id in self._known


def _make_client(patient_repo: Any) -> tuple[TestClient, _InMemoryThreads]:
    settings = Settings(  # type: ignore[call-arg]
        auth_stub_enabled=True, auth_required_role="Clinician"
    )
    audit = AuditEventEmitter(sink=NullAuditSink())
    registry = SpecialistRegistry()
    threads = _InMemoryThreads()
    container = Container(
        settings=settings,
        db_pool_factory=_NoopFactory(),  # type: ignore[arg-type]
        cosmos_client_factory=_NoopFactory(),  # type: ignore[arg-type]
        llm_client_factory=LlmClientFactory(
            settings, client_constructor=lambda **_: object()
        ),
        prompt_service=_NoopPrompts(),  # type: ignore[arg-type]
        thread_state_provider=threads,  # type: ignore[arg-type]
        provenance_service=ProvenanceService(),
        # Open policy = the admin case. Every patient passes the
        # allowlist, so the existence check is the only thing standing
        # between a typo and a thread.
        authz_policy=OpenAuthzPolicy(),
        audit_emitter=audit,
        authenticator=StubAuthenticator(settings=settings, audit=audit),
        telemetry_provider=build_telemetry_provider(settings),
        metric_emitter=NullMetricEmitter(),
        specialist_registry=registry,
        workflow_runtime=WorkflowRuntime(
            settings=settings,
            chat_router_llm=StubRouterLlm(
                ChatRouterDecision(needs_clinical_data=False, reason="t")
            ),
            orch_router_llm=StubOrchRouterLlm(
                [SpecialistDispatchSet(specialists=[], reason="t")]
            ),
            specialist_registry=registry,
        ),
        scope_guard=ScopeGuard(),
        patient_repository=patient_repo,
    )
    return TestClient(create_app(container)), threads


_TOKEN = json.dumps(
    {"oid": "demo", "tid": "T", "roles": ["Clinician"], "exp": 9999999999}
)
_AUTH = {"Authorization": f"Bearer {_TOKEN}"}


class TestPatientExistenceCheck:
    def test_real_patient_creates_a_thread(self) -> None:
        client, threads = _make_client(_PatientRepoDouble(known={"HG04007"}))

        resp = client.post(
            "/threads", json={"patient_id": "HG04007"}, headers=_AUTH
        )

        assert resp.status_code == 200
        assert threads.created == ["HG04007"]

    def test_typo_is_rejected_even_for_an_admin(self) -> None:
        """The 2026-09-10 case. ``demo`` is allow-listed for everything,
        so only the existence check can stop this."""
        client, threads = _make_client(_PatientRepoDouble(known={"HG04007"}))

        resp = client.post(
            "/threads", json={"patient_id": "HG0007"}, headers=_AUTH
        )

        assert resp.status_code == 404
        assert threads.created == []

    def test_rejection_is_indistinguishable_from_not_allow_listed(self) -> None:
        """B-005's enumeration defence: "does not exist" and "not
        authorised" must return the identical status and body, or the
        response itself becomes a patient-directory lookup."""
        client, _ = _make_client(_PatientRepoDouble(known=set()))

        resp = client.post(
            "/threads", json={"patient_id": "HG9999"}, headers=_AUTH
        )

        assert resp.status_code == 404
        assert resp.json()["error_code"] == "patient_unavailable"

    def test_database_failure_is_not_reported_as_patient_not_found(self) -> None:
        """The distinction the whole §4j change was about: a database we
        cannot reach tells us nothing about whether the patient exists.
        Answering 404 would turn a retrieval failure into a factual
        claim."""
        client, threads = _make_client(
            _PatientRepoDouble(raises=DatabaseUnavailable("pool timeout"))
        )

        resp = client.post(
            "/threads", json={"patient_id": "HG04007"}, headers=_AUTH
        )

        assert resp.status_code != 404
        assert resp.status_code >= 500
        assert threads.created == []

    def test_check_runs_before_the_thread_is_written(self) -> None:
        """No junk threads in Cosmos for ids that were never real."""
        repo = _PatientRepoDouble(known=set())
        client, threads = _make_client(repo)

        client.post("/threads", json={"patient_id": "HG0007"}, headers=_AUTH)

        assert repo.calls == ["HG0007"]
        assert threads.created == []

    def test_absent_repository_does_not_break_thread_creation(self) -> None:
        """``patient_repository`` is optional so existing test containers
        keep compiling. ``build_container`` always supplies it; when it is
        missing the endpoint logs a warning rather than failing."""
        client, threads = _make_client(None)

        resp = client.post(
            "/threads", json={"patient_id": "HG0007"}, headers=_AUTH
        )

        assert resp.status_code == 200
        assert threads.created == ["HG0007"]
