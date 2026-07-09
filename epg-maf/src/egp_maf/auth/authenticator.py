"""JWT authenticator — bearer token → :class:`ClinicianContext`.

Two implementations behind an :class:`Authenticator` protocol:

- :class:`EntraTokenAuthenticator` (production): validates the token
  against an Entra JWKS endpoint using PyJWT; enforces issuer,
  audience, expiry (with configurable leeway); maps claims via
  :func:`egp_maf.auth.claims.claims_to_context`; enforces the required
  app role (default ``Clinician``); emits an audit event on any
  failure path.
- :class:`StubAuthenticator` (dev + unit tests): accepts a plain
  ``dict`` in place of the bytes; skips signature validation; used by
  the DI container when ``settings.auth_stub_enabled`` is true.

Both raise :class:`AuthenticationError` on failure so the API layer can
translate to a stable 401/403.

APIM already validates the JWT signature at the edge (Design §17.4).
The authenticator here re-validates defensively — belt and braces — and
because we need the parsed claims regardless.
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Protocol, runtime_checkable

from egp_maf.auth.audit import AuditEventEmitter
from egp_maf.auth.claims import (
    ClaimsMappingError,
    ClinicianTokenClaims,
    claims_to_context,
    decode_token_bytes_to_claims,
)
from egp_maf.config.settings import Settings
from egp_maf.errors import ConfigurationError, EgpError
from egp_maf.state.clinician_context import ClinicianContext

_logger = logging.getLogger(__name__)


class AuthenticationError(EgpError):
    """Raised when a bearer token cannot be validated or mapped."""

    error_code = "auth_failed"
    http_status = 401


@runtime_checkable
class Authenticator(Protocol):
    """Turns a bearer token into a :class:`ClinicianContext`."""

    async def authenticate(
        self,
        token: str,
        *,
        route: str | None = None,
        trace_id: str | None = None,
    ) -> ClinicianContext: ...


# ── Real MAF/Entra-backed implementation ────────────────────────────


class EntraTokenAuthenticator:
    """Production authenticator.

    Uses PyJWT + JWKS via :class:`jwt.PyJWKClient` to validate the
    token signature; enforces issuer, audience, and expiry (with
    :attr:`Settings.entra_leeway_seconds` leeway on ``nbf`` / ``exp``);
    maps to a :class:`ClinicianContext`; verifies the caller carries
    the required app role (defaults to :attr:`Settings.auth_required_role`).

    The JWKS client is created lazily so importing this module does not
    depend on network access. Callers can inject a
    ``signing_key_resolver`` to bypass the JWKS fetch in tests without
    touching the audience/issuer/expiry checks.
    """

    def __init__(
        self,
        *,
        settings: Settings,
        audit: AuditEventEmitter | None = None,
        signing_key_resolver: Callable[[str], Any] | None = None,
    ) -> None:
        self._settings = settings
        self._audit = audit or AuditEventEmitter()
        self._explicit_resolver = signing_key_resolver
        self._jwks_client: Any = None

        # Fail fast on incomplete config — better to crash at boot than
        # per-request. Stub authenticator is the escape hatch for dev.
        missing = [
            name
            for name, value in (
                ("ENTRA_TENANT_ID", settings.entra_tenant_id),
                ("ENTRA_EXPECTED_AUDIENCE", settings.entra_expected_audience),
                ("ENTRA_EXPECTED_ISSUER", settings.entra_expected_issuer),
                ("ENTRA_JWKS_URL", settings.entra_jwks_url),
            )
            if not value
        ]
        if missing and signing_key_resolver is None:
            raise ConfigurationError(
                "EntraTokenAuthenticator requires "
                + ", ".join(missing)
                + " (or an injected signing_key_resolver for tests)."
            )

    async def authenticate(
        self,
        token: str,
        *,
        route: str | None = None,
        trace_id: str | None = None,
    ) -> ClinicianContext:
        if not token:
            self._audit.emit_auth_token_invalid(
                reason="empty bearer token",
                route=route or "api.request",
                trace_id=trace_id,
            )
            raise AuthenticationError("Missing bearer token")

        try:
            claims_dict = self._decode_and_verify(token)
        except AuthenticationError:
            raise
        except Exception as exc:
            # PyJWT raises many specific exception subclasses; treat
            # every decode failure as 401 without leaking the message.
            reason = f"{type(exc).__name__}: {exc}"
            self._audit.emit_auth_token_invalid(
                reason=reason,
                route=route or "api.request",
                trace_id=trace_id,
            )
            raise AuthenticationError("Token validation failed") from exc

        try:
            typed = decode_token_bytes_to_claims(claims_dict)
            ctx = claims_to_context(typed)
        except ClaimsMappingError as exc:
            self._audit.emit_auth_token_invalid(
                reason=str(exc),
                route=route or "api.request",
                trace_id=trace_id,
            )
            raise AuthenticationError("Token claims invalid") from exc

        self._enforce_required_role(
            ctx=ctx, claims=typed, route=route, trace_id=trace_id
        )
        return ctx

    # ── Internals ──────────────────────────────────────────────────

    def _decode_and_verify(self, token: str) -> dict[str, Any]:
        import jwt  # local import — decouples module import from PyJWT

        resolver = self._explicit_resolver or self._default_resolver
        signing_key = resolver(token)
        return jwt.decode(
            token,
            signing_key,
            algorithms=["RS256"],
            audience=self._settings.entra_expected_audience,
            issuer=self._settings.entra_expected_issuer,
            leeway=self._settings.entra_leeway_seconds,
        )

    def _default_resolver(self, token: str) -> Any:
        import jwt  # local import

        if self._jwks_client is None:
            self._jwks_client = jwt.PyJWKClient(self._settings.entra_jwks_url or "")
        return self._jwks_client.get_signing_key_from_jwt(token).key

    def _enforce_required_role(
        self,
        *,
        ctx: ClinicianContext,
        claims: ClinicianTokenClaims,
        route: str | None,
        trace_id: str | None,
    ) -> None:
        required = self._settings.auth_required_role
        if not required:
            return
        if ctx.has_role(required):
            return
        self._audit.emit_auth_role_denied(
            clinician_id=ctx.clinician_id,
            tenant_id=ctx.tenant_id,
            required_role=required,
            roles_present=list(claims.roles),
            route=route or "api.request",
            trace_id=trace_id,
        )
        raise AuthenticationError(
            f"Caller lacks required role {required!r}"
        )


# ── Stub for dev + unit tests ───────────────────────────────────────


class StubAuthenticator:
    """Signature-less authenticator used in dev + tests.

    The ``token`` argument is treated as a JSON-encoded claim dict; no
    signature / audience / issuer checks. Only the same claims-mapping
    logic as production runs (so the ``ClinicianContext`` shape is
    identical).

    Enable in dev via ``EGP_AUTH_STUB_ENABLED=true``. Refuses to
    construct in production settings (``env='prod'``).
    """

    def __init__(
        self,
        *,
        settings: Settings,
        audit: AuditEventEmitter | None = None,
    ) -> None:
        if settings.is_production():
            raise ConfigurationError(
                "StubAuthenticator must not be used in production. "
                "Set EGP_AUTH_STUB_ENABLED=false."
            )
        self._settings = settings
        self._audit = audit or AuditEventEmitter()

    async def authenticate(
        self,
        token: str,
        *,
        route: str | None = None,
        trace_id: str | None = None,
    ) -> ClinicianContext:
        import json

        if not token:
            self._audit.emit_auth_token_invalid(
                reason="empty stub token",
                route=route or "api.request",
                trace_id=trace_id,
            )
            raise AuthenticationError("Missing bearer token (stub)")

        try:
            payload = json.loads(token)
            if not isinstance(payload, dict):
                raise TypeError(f"expected dict, got {type(payload).__name__}")
        except (json.JSONDecodeError, TypeError) as exc:
            self._audit.emit_auth_token_invalid(
                reason=f"stub-token not JSON dict: {exc}",
                route=route or "api.request",
                trace_id=trace_id,
            )
            raise AuthenticationError("Stub token is not a JSON dict") from exc

        try:
            typed = decode_token_bytes_to_claims(payload)
            ctx = claims_to_context(typed)
        except ClaimsMappingError as exc:
            self._audit.emit_auth_token_invalid(
                reason=str(exc),
                route=route or "api.request",
                trace_id=trace_id,
            )
            raise AuthenticationError("Stub token claims invalid") from exc

        required = self._settings.auth_required_role
        if required and not ctx.has_role(required):
            self._audit.emit_auth_role_denied(
                clinician_id=ctx.clinician_id,
                tenant_id=ctx.tenant_id,
                required_role=required,
                roles_present=list(typed.roles),
                route=route or "api.request",
                trace_id=trace_id,
            )
            raise AuthenticationError(
                f"Caller lacks required role {required!r} (stub)"
            )
        return ctx


# ── Factory used by the DI container ────────────────────────────────


def build_authenticator(
    settings: Settings,
    *,
    audit: AuditEventEmitter | None = None,
    signing_key_resolver: Callable[[str], Any] | None = None,
) -> Authenticator:
    """Return :class:`StubAuthenticator` when ``EGP_AUTH_STUB_ENABLED``
    is set, otherwise the real :class:`EntraTokenAuthenticator`.

    Prod cannot construct the stub (guarded in the class itself).
    """
    if settings.auth_stub_enabled:
        return StubAuthenticator(settings=settings, audit=audit)
    return EntraTokenAuthenticator(
        settings=settings,
        audit=audit,
        signing_key_resolver=signing_key_resolver,
    )
