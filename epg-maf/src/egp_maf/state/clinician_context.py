"""Request-scoped clinician identity.

Populated from the Entra ID access token in the auth workstream. In earlier
workstreams (foundation, repositories) the ``ClinicianContext`` is constructed
by a test factory so downstream code can be exercised without a real token.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ClinicianContext(BaseModel):
    """Immutable clinician identity carried through every workflow turn.

    Attributes
    ----------
    clinician_id:
        The stable clinician identifier. Sourced from the Entra ID token
        ``oid`` claim in production.
    tenant_id:
        Entra tenant id.
    roles:
        Frozen set of app roles granted to this clinician.
    token_expires_at:
        UTC expiry of the access token (informational — enforcement is at
        the API middleware layer).
    """

    clinician_id: str
    tenant_id: str
    roles: frozenset[str] = Field(default_factory=frozenset)
    token_expires_at: datetime | None = None

    model_config = ConfigDict(frozen=True, extra="forbid")

    def has_role(self, role: str) -> bool:
        return role in self.roles

    @classmethod
    def system(cls) -> "ClinicianContext":
        """Convenience factory for background jobs / tests."""
        return cls(
            clinician_id="system",
            tenant_id="system",
            roles=frozenset({"System"}),
            token_expires_at=None,
        )

    def to_span_attributes(self) -> dict[str, Any]:
        """Attributes safe to attach to OpenTelemetry spans (no PHI)."""
        return {
            "clinician_id": self.clinician_id,
            "tenant_id": self.tenant_id,
        }
