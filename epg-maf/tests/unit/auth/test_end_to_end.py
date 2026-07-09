"""End-to-end test: bearer token → ClinicianContext → Repository call.

Proves the W07 wiring works with real production classes (only the
Repository's DB pool is stubbed). The specific interactions covered:

1. StubAuthenticator maps a JSON claim dict to a valid ClinicianContext.
2. That ctx is passed to a real Repository.
3. AllowlistAuthzPolicy allows or denies based on the effective allowlist.
4. A denial produces (a) an AccessDenied exception and (b) a structured
   authz.denied audit event via the shared emitter.
5. A grant produces an authz.granted audit event.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import pytest

from egp_maf.auth.audit import AuditEvent, AuditEventEmitter
from egp_maf.auth.authenticator import StubAuthenticator
from egp_maf.config.settings import Settings
from egp_maf.errors import AccessDenied
from egp_maf.services.authz import AllowlistAuthzPolicy
from egp_maf.services.provenance import ProvenanceService
from egp_maf.services.repositories import PRSRepository
from tests.support.fake_pool import FakePool, FakePoolFactory

pytestmark = pytest.mark.unit


class _CapturingSink:
    def __init__(self) -> None:
        self.events: list[AuditEvent] = []

    def emit(self, event: AuditEvent) -> None:
        self.events.append(event)


def _mint_token(oid: str = "c-1", tid: str = "t-1") -> str:
    return json.dumps(
        {"oid": oid, "tid": tid, "roles": ["Clinician"], "exp": int(time.time()) + 60}
    )


def _allowlist_file(tmp_path: Path, clinician: str, patients: list[str]) -> Path:
    payload = {
        "version": 1,
        "clinicians": {clinician: patients},
        "admins": [],
    }
    p = tmp_path / "allowlist.json"
    p.write_text(json.dumps(payload), encoding="utf-8")
    return p


class TestBearerTokenToRepository:
    async def test_authorised_read_produces_authz_granted_audit(
        self, tmp_path: Path
    ) -> None:
        sink = _CapturingSink()
        emitter = AuditEventEmitter(sink=sink)

        # Authenticator maps token → ctx.
        settings = Settings(  # type: ignore[call-arg]
            EGP_AUTH_STUB_ENABLED=True,
            EGP_AUTH_REQUIRED_ROLE="Clinician",
        )
        authenticator = StubAuthenticator(settings=settings, audit=emitter)
        ctx = await authenticator.authenticate(_mint_token(oid="c-1"))

        # Allowlist grants c-1 access to P1.
        policy = AllowlistAuthzPolicy(
            _allowlist_file(tmp_path, "c-1", ["P1"]), audit=emitter
        )
        pool = FakePool()
        pool.push_response(rows=[], column_names=["patient_id", "prs_name", "disease_name", "risk_band"])  # empty result is fine
        repo = PRSRepository(
            pool_factory=FakePoolFactory(pool),
            authz=policy,
            provenance=ProvenanceService(),
        )
        result = await repo.explore_patient_prs(ctx, "P1")
        assert result == []

        # Audit shows both the ctx creation (no explicit event on the
        # happy path — that's stubbed above) and the grant.
        granted = [e for e in sink.events if e.event == "authz.granted"]
        assert len(granted) == 1
        assert granted[0].clinician_id == "c-1"
        assert granted[0].patient_id == "P1"

    async def test_denied_read_produces_authz_denied_audit(
        self, tmp_path: Path
    ) -> None:
        sink = _CapturingSink()
        emitter = AuditEventEmitter(sink=sink)

        settings = Settings(  # type: ignore[call-arg]
            EGP_AUTH_STUB_ENABLED=True,
            EGP_AUTH_REQUIRED_ROLE="Clinician",
        )
        authenticator = StubAuthenticator(settings=settings, audit=emitter)
        ctx = await authenticator.authenticate(_mint_token(oid="c-2"))

        # Allowlist grants c-1 access to P1, but c-2 has no entry.
        policy = AllowlistAuthzPolicy(
            _allowlist_file(tmp_path, "c-1", ["P1"]), audit=emitter
        )
        repo = PRSRepository(
            pool_factory=FakePoolFactory(FakePool()),
            authz=policy,
            provenance=ProvenanceService(),
        )
        with pytest.raises(AccessDenied):
            await repo.explore_patient_prs(ctx, "P1")

        denied = [e for e in sink.events if e.event == "authz.denied"]
        assert len(denied) == 1
        assert denied[0].clinician_id == "c-2"
        assert denied[0].patient_id == "P1"
        assert denied[0].reason is not None and "allowlist" in denied[0].reason.lower()

    async def test_wrong_role_stops_at_authenticator(self) -> None:
        sink = _CapturingSink()
        emitter = AuditEventEmitter(sink=sink)
        settings = Settings(  # type: ignore[call-arg]
            EGP_AUTH_STUB_ENABLED=True,
            EGP_AUTH_REQUIRED_ROLE="Clinician",
        )
        authenticator = StubAuthenticator(settings=settings, audit=emitter)
        token = json.dumps(
            {"oid": "c-3", "tid": "t-1", "roles": ["Auditor"], "exp": int(time.time()) + 60}
        )
        with pytest.raises(Exception, match="required role"):
            await authenticator.authenticate(token)
        role_denials = [e for e in sink.events if e.event == "auth.role_denied"]
        assert len(role_denials) == 1
        assert role_denials[0].clinician_id == "c-3"
