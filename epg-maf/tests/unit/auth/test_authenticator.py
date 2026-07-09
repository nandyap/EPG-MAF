"""Tests for :mod:`egp_maf.auth.authenticator`.

Covers the stub authenticator (no PyJWT invocations) and the real
:class:`EntraTokenAuthenticator` with an injected signing-key resolver
so we can mint a locally signed test token and validate the full
decode + audience + issuer + expiry + role-check pipeline.
"""

from __future__ import annotations

import json
import os
import time
from typing import Any

import pytest

from egp_maf.auth.audit import AuditEvent, AuditEventEmitter
from egp_maf.auth.authenticator import (
    AuthenticationError,
    EntraTokenAuthenticator,
    StubAuthenticator,
    build_authenticator,
)
from egp_maf.config.settings import Settings
from egp_maf.errors import ConfigurationError

pytestmark = pytest.mark.unit

os.environ.setdefault("LLM_API_KEY", "test")


class _CapturingSink:
    def __init__(self) -> None:
        self.events: list[AuditEvent] = []

    def emit(self, event: AuditEvent) -> None:
        self.events.append(event)


def _stub_settings(**overrides: Any) -> Settings:
    return Settings(  # type: ignore[call-arg]
        EGP_AUTH_STUB_ENABLED=True,
        EGP_AUTH_REQUIRED_ROLE="Clinician",
        **overrides,
    )


# ── StubAuthenticator ────────────────────────────────────────────────


class TestStubAuthenticator:
    async def test_happy_path_produces_ctx(self) -> None:
        auth = StubAuthenticator(settings=_stub_settings())
        token = json.dumps(
            {"oid": "c", "tid": "t", "roles": ["Clinician"], "exp": int(time.time()) + 60}
        )
        ctx = await auth.authenticate(token)
        assert ctx.clinician_id == "c"
        assert ctx.tenant_id == "t"
        assert "Clinician" in ctx.roles

    async def test_missing_token_raises(self) -> None:
        auth = StubAuthenticator(settings=_stub_settings())
        with pytest.raises(AuthenticationError):
            await auth.authenticate("")

    async def test_bad_json_raises(self) -> None:
        auth = StubAuthenticator(settings=_stub_settings())
        with pytest.raises(AuthenticationError):
            await auth.authenticate("not-json")

    async def test_wrong_type_raises(self) -> None:
        auth = StubAuthenticator(settings=_stub_settings())
        with pytest.raises(AuthenticationError):
            await auth.authenticate(json.dumps([1, 2, 3]))

    async def test_missing_role_raises_role_denied(self) -> None:
        sink = _CapturingSink()
        auth = StubAuthenticator(
            settings=_stub_settings(),
            audit=AuditEventEmitter(sink=sink),
        )
        token = json.dumps(
            {"oid": "c", "tid": "t", "roles": ["Auditor"], "exp": int(time.time()) + 60}
        )
        with pytest.raises(AuthenticationError, match="required role"):
            await auth.authenticate(token)
        assert any(e.event == "auth.role_denied" for e in sink.events)

    async def test_missing_oid_emits_token_invalid(self) -> None:
        sink = _CapturingSink()
        auth = StubAuthenticator(
            settings=_stub_settings(),
            audit=AuditEventEmitter(sink=sink),
        )
        token = json.dumps({"tid": "t", "roles": ["Clinician"]})
        with pytest.raises(AuthenticationError):
            await auth.authenticate(token)
        assert any(e.event == "auth.token_invalid" for e in sink.events)

    def test_forbidden_in_production(self) -> None:
        prod_settings = _stub_settings(EGP_ENV="prod")
        with pytest.raises(ConfigurationError):
            StubAuthenticator(settings=prod_settings)


# ── EntraTokenAuthenticator ─────────────────────────────────────────


class _KeyPair:
    """Lazy RSA keypair for signing/verifying test tokens."""

    _cached: "_KeyPair | None" = None

    def __init__(self) -> None:
        from cryptography.hazmat.primitives.asymmetric import rsa

        self.private_key = rsa.generate_private_key(
            public_exponent=65537, key_size=2048
        )
        self.public_key = self.private_key.public_key()

    @classmethod
    def get(cls) -> "_KeyPair":
        if cls._cached is None:
            cls._cached = cls()
        return cls._cached


def _real_settings(**overrides: Any) -> Settings:
    return Settings(  # type: ignore[call-arg]
        ENTRA_TENANT_ID="tenant-x",
        ENTRA_EXPECTED_AUDIENCE="api://egp",
        ENTRA_EXPECTED_ISSUER="https://sts.windows.net/tenant-x/",
        ENTRA_JWKS_URL="https://example/keys",
        EGP_AUTH_STUB_ENABLED=False,
        EGP_AUTH_REQUIRED_ROLE="Clinician",
        **overrides,
    )


def _mint_token(
    *,
    keypair: _KeyPair | None = None,
    audience: str = "api://egp",
    issuer: str = "https://sts.windows.net/tenant-x/",
    roles: list[str] | None = None,
    oid: str = "clinician-1",
    tid: str = "tenant-x",
    ttl_seconds: int = 60,
) -> str:
    import jwt

    kp = keypair or _KeyPair.get()
    now = int(time.time())
    payload = {
        "oid": oid,
        "tid": tid,
        "roles": roles if roles is not None else ["Clinician"],
        "iss": issuer,
        "aud": audience,
        "iat": now,
        "nbf": now,
        "exp": now + ttl_seconds,
    }
    return jwt.encode(payload, kp.private_key, algorithm="RS256")


def _resolver_returning(keypair: _KeyPair) -> Any:
    def _resolve(_token: str) -> Any:
        return keypair.public_key

    return _resolve


class TestEntraTokenAuthenticator:
    async def test_happy_path_end_to_end(self) -> None:
        kp = _KeyPair.get()
        auth = EntraTokenAuthenticator(
            settings=_real_settings(),
            signing_key_resolver=_resolver_returning(kp),
        )
        token = _mint_token()
        ctx = await auth.authenticate(token)
        assert ctx.clinician_id == "clinician-1"
        assert ctx.tenant_id == "tenant-x"
        assert "Clinician" in ctx.roles

    async def test_wrong_audience_raises(self) -> None:
        kp = _KeyPair.get()
        sink = _CapturingSink()
        auth = EntraTokenAuthenticator(
            settings=_real_settings(),
            audit=AuditEventEmitter(sink=sink),
            signing_key_resolver=_resolver_returning(kp),
        )
        token = _mint_token(keypair=kp, audience="api://other")
        with pytest.raises(AuthenticationError):
            await auth.authenticate(token)
        assert any(e.event == "auth.token_invalid" for e in sink.events)

    async def test_expired_token_raises(self) -> None:
        kp = _KeyPair.get()
        auth = EntraTokenAuthenticator(
            settings=_real_settings(ENTRA_LEEWAY_SECONDS=0),
            signing_key_resolver=_resolver_returning(kp),
        )
        token = _mint_token(keypair=kp, ttl_seconds=-60)
        with pytest.raises(AuthenticationError):
            await auth.authenticate(token)

    async def test_wrong_issuer_raises(self) -> None:
        kp = _KeyPair.get()
        auth = EntraTokenAuthenticator(
            settings=_real_settings(),
            signing_key_resolver=_resolver_returning(kp),
        )
        token = _mint_token(keypair=kp, issuer="https://sts.windows.net/other/")
        with pytest.raises(AuthenticationError):
            await auth.authenticate(token)

    async def test_bad_signature_raises(self) -> None:
        # Sign with keypair A, verify with keypair B.
        good = _KeyPair.get()

        class _OtherKp(_KeyPair):
            pass

        other = _OtherKp()
        auth = EntraTokenAuthenticator(
            settings=_real_settings(),
            signing_key_resolver=_resolver_returning(good),
        )
        token = _mint_token(keypair=other)
        with pytest.raises(AuthenticationError):
            await auth.authenticate(token)

    async def test_missing_required_role_denied(self) -> None:
        kp = _KeyPair.get()
        sink = _CapturingSink()
        auth = EntraTokenAuthenticator(
            settings=_real_settings(),
            audit=AuditEventEmitter(sink=sink),
            signing_key_resolver=_resolver_returning(kp),
        )
        token = _mint_token(keypair=kp, roles=["Auditor"])
        with pytest.raises(AuthenticationError, match="required role"):
            await auth.authenticate(token)
        assert any(e.event == "auth.role_denied" for e in sink.events)

    def test_missing_config_raises_at_construction(self) -> None:
        # No signing_key_resolver + missing ENTRA_* config → fail closed.
        with pytest.raises(ConfigurationError):
            EntraTokenAuthenticator(settings=Settings())  # type: ignore[call-arg]


# ── Factory ─────────────────────────────────────────────────────────


class TestBuildAuthenticator:
    def test_returns_stub_when_flag_set(self) -> None:
        auth = build_authenticator(_stub_settings())
        assert isinstance(auth, StubAuthenticator)

    def test_returns_real_when_flag_unset_and_config_present(self) -> None:
        kp = _KeyPair.get()
        settings = _real_settings()
        auth = build_authenticator(
            settings, signing_key_resolver=_resolver_returning(kp)
        )
        assert isinstance(auth, EntraTokenAuthenticator)
