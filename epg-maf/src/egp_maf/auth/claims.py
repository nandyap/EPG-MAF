"""Entra ID token claims → :class:`ClinicianContext`.

This module is intentionally free of any JWT-library dependency — it
takes an already-decoded ``dict[str, Any]`` (as PyJWT returns) and
returns a typed :class:`ClinicianTokenClaims` + a mapped
:class:`ClinicianContext`. The
:mod:`egp_maf.auth.authenticator` module owns the actual decode +
signature validation.

We only surface the four claims the design needs (Design ADR-008):

- ``oid`` → ``ClinicianContext.clinician_id`` (Entra object id — stable).
- ``tid`` → ``ClinicianContext.tenant_id``.
- ``roles`` → ``ClinicianContext.roles`` (app roles: ``Clinician``,
  ``Auditor``, ``Admin``).
- ``exp`` → ``ClinicianContext.token_expires_at`` (informational).

Extra claims are preserved on :class:`ClinicianTokenClaims.raw` so
downstream code can peek at them without re-decoding.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from egp_maf.errors import EgpError
from egp_maf.state.clinician_context import ClinicianContext


class ClaimsMappingError(EgpError):
    """Raised when the decoded claim set can't produce a valid
    :class:`ClinicianContext` (missing ``oid`` / ``tid`` /
    ``roles`` / malformed ``exp``)."""

    error_code = "auth_claims_invalid"
    http_status = 401


class ClinicianTokenClaims(BaseModel):
    """Typed subset of an Entra ID access token used by the auth flow.

    Uses Pydantic aliases so we can pass the raw claim dict from PyJWT
    directly (``model_validate({...})``).
    """

    oid: str = Field(description="Entra object id — stable clinician identifier")
    tid: str = Field(description="Entra tenant id")
    roles: list[str] = Field(
        default_factory=list,
        description="App roles assigned in the Entra app registration",
    )
    exp: int | None = Field(
        default=None,
        description="Unix seconds — informational (JWT lib already enforced expiry)",
    )
    raw: dict[str, Any] = Field(
        default_factory=dict,
        description="Full decoded claim set for downstream inspection",
    )

    model_config = ConfigDict(extra="ignore")


def decode_token_bytes_to_claims(
    decoded_claims: dict[str, Any],
) -> ClinicianTokenClaims:
    """Turn a PyJWT-decoded claim dict into a :class:`ClinicianTokenClaims`.

    ``raw`` is populated with the whole decoded claim set (before any
    validation), which is what audit records should log for the token
    (excluding the signature). Signature/expiry/audience checks are the
    caller's job — see :class:`~egp_maf.auth.authenticator.EntraTokenAuthenticator`.
    """
    payload = dict(decoded_claims)
    payload["raw"] = dict(decoded_claims)
    try:
        return ClinicianTokenClaims.model_validate(payload)
    except ValidationError as exc:
        raise ClaimsMappingError(f"Token claims failed validation: {exc}") from exc


def claims_to_context(claims: ClinicianTokenClaims) -> ClinicianContext:
    """Map :class:`ClinicianTokenClaims` to :class:`ClinicianContext`.

    Fails with :class:`ClaimsMappingError` if required identity claims
    are missing. Roles are copied verbatim; downstream code checks
    ``ctx.has_role(...)`` for the required role.
    """
    if not claims.oid:
        raise ClaimsMappingError("Missing required claim 'oid' (Entra object id)")
    if not claims.tid:
        raise ClaimsMappingError("Missing required claim 'tid' (Entra tenant id)")

    expires_at: datetime | None = None
    if claims.exp is not None:
        try:
            expires_at = datetime.fromtimestamp(int(claims.exp), tz=timezone.utc)
        except (TypeError, ValueError, OSError) as exc:
            raise ClaimsMappingError(
                f"Malformed 'exp' claim: {claims.exp!r} ({exc})"
            ) from exc

    return ClinicianContext(
        clinician_id=claims.oid,
        tenant_id=claims.tid,
        roles=frozenset(claims.roles),
        token_expires_at=expires_at,
    )
