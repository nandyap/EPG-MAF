"""AuthZ test doubles.

Moved out of ``src/`` so production code cannot accidentally import them
(they were previously declared as "test-only" but lived alongside the
production :class:`AllowlistAuthzPolicy`).

Both classes conform to the :class:`~egp_maf.services.authz.AuthzPolicy`
protocol.
"""

from __future__ import annotations

from egp_maf.errors import AccessDenied
from egp_maf.state.clinician_context import ClinicianContext


class OpenAuthzPolicy:
    """Test-only policy that allows everything. Never used in production."""

    def can_read(self, ctx: ClinicianContext, patient_id: str) -> bool:  # noqa: ARG002
        return True

    def enforce_read(self, ctx: ClinicianContext, patient_id: str) -> None:
        return


class ClosedAuthzPolicy:
    """Test-only policy that denies everything. Never used in production."""

    def can_read(self, ctx: ClinicianContext, patient_id: str) -> bool:  # noqa: ARG002
        return False

    def enforce_read(self, ctx: ClinicianContext, patient_id: str) -> None:
        raise AccessDenied(
            f"Clinician '{ctx.clinician_id}' is not authorised (closed policy)."
        )
