"""Authentication + authz-audit — W07.

W02 delivered the authorisation half of Design ADR-017: the
:class:`~egp_maf.services.authz.AllowlistAuthzPolicy` enforces a
per-patient allowlist at the Repository entry, and every specialist
already threads a :class:`~egp_maf.state.clinician_context.ClinicianContext`
through to it. What was missing was *where the ``ClinicianContext``
comes from* — production must build it from an Entra ID access token
rather than the ``ClinicianContext.system()`` factory tests use.

W07 delivers exactly that missing piece plus a proper audit trail:

- :mod:`.claims` — :class:`ClinicianTokenClaims` (typed subset of the
  Entra token) + a mapper that turns claims into a
  :class:`ClinicianContext`.
- :mod:`.authenticator` — :class:`Authenticator` protocol +
  :class:`EntraTokenAuthenticator` (production impl using PyJWT + JWKS)
  + :class:`StubAuthenticator` (test double that accepts unsigned JSON
  claims).
- :mod:`.audit` — :class:`AuditEvent` structured record +
  :class:`AuditEventEmitter` that publishes ``authz.*`` events on
  ``authz.denied`` / ``authz.granted`` / ``auth.token_invalid``.
- The :class:`AllowlistAuthzPolicy` is extended (backwards-compatibly)
  to emit a structured ``authz.denied`` audit event through the
  emitter, in addition to the log line it already emits.

No FastAPI / HTTP layer here — the plan (F09.2) puts the FastAPI
middleware in the API workstream. This module is what that middleware
will call.
"""

from egp_maf.auth.audit import (
    AuditEvent,
    AuditEventEmitter,
    AuditOutcome,
    LoggingAuditSink,
    NullAuditSink,
)
from egp_maf.auth.authenticator import (
    Authenticator,
    AuthenticationError,
    EntraTokenAuthenticator,
    StubAuthenticator,
    build_authenticator,
)
from egp_maf.auth.claims import (
    ClinicianTokenClaims,
    ClaimsMappingError,
    claims_to_context,
    decode_token_bytes_to_claims,
)

__all__ = [
    "AuditEvent",
    "AuditEventEmitter",
    "AuditOutcome",
    "AuthenticationError",
    "Authenticator",
    "ClaimsMappingError",
    "ClinicianTokenClaims",
    "EntraTokenAuthenticator",
    "LoggingAuditSink",
    "NullAuditSink",
    "StubAuthenticator",
    "build_authenticator",
    "claims_to_context",
    "decode_token_bytes_to_claims",
]
