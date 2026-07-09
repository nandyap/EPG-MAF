"""Authorization policy — enforces patient-scope RBAC at the Repository layer.

Design references:

- Design ADR-017 (Deterministic ``patient_id`` scoping at the Repository layer).
- Design §19.3 (Auth model + Phase 1 allowlist).

Phase 1 policy is a JSON allowlist backed by a Key Vault secret (in prod) or
a plain file (in dev). Structure:

.. code-block:: json

    {
        "version": 1,
        "clinicians": {
            "clinician_id_1": ["P001", "P002"],
            "clinician_id_2": ["P003"]
        },
        "admins": ["a001", "a002"]
    }

Admins bypass the per-patient check. The ``system`` clinician (created by
``ClinicianContext.system()``) also bypasses — used by background jobs.

W07: :meth:`AllowlistAuthzPolicy.enforce_read` also emits a structured
``authz.denied`` / ``authz.granted`` audit event via an optional
:class:`~egp_maf.auth.audit.AuditEventEmitter`. Callers that don't
supply one (existing W02 callers, unit tests) get a
:class:`~egp_maf.auth.audit.NullAuditSink` and see no behaviour change.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Protocol

from egp_maf.errors import AccessDenied, ConfigurationError
from egp_maf.state.clinician_context import ClinicianContext

if TYPE_CHECKING:  # pragma: no cover
    from egp_maf.auth.audit import AuditEventEmitter

_logger = logging.getLogger(__name__)


class AuthzPolicy(Protocol):
    """Abstract policy — implementations decide whether a clinician can
    access a given patient_id.
    """

    def can_read(self, ctx: ClinicianContext, patient_id: str) -> bool:
        """Return True if the clinician is allowed to read ``patient_id``."""

    def enforce_read(self, ctx: ClinicianContext, patient_id: str) -> None:
        """Raise :class:`AccessDenied` if the clinician is NOT allowed."""


class _Allowlist:
    """Parsed allowlist document."""

    __slots__ = ("_clinicians", "_admins", "_version")

    def __init__(self, payload: dict[str, object]) -> None:
        version = payload.get("version")
        if version != 1:
            raise ConfigurationError(
                f"Allowlist schema version must be 1, got {version!r}"
            )
        self._version = 1

        clinicians = payload.get("clinicians", {}) or {}
        if not isinstance(clinicians, dict):
            raise ConfigurationError("Allowlist 'clinicians' must be an object")
        self._clinicians: dict[str, frozenset[str]] = {}
        for clinician_id, patients in clinicians.items():
            if not isinstance(patients, list):
                raise ConfigurationError(
                    f"Allowlist entry for {clinician_id!r} must be a list of patient IDs"
                )
            self._clinicians[str(clinician_id)] = frozenset(str(p) for p in patients)

        admins = payload.get("admins", []) or []
        if not isinstance(admins, list):
            raise ConfigurationError("Allowlist 'admins' must be a list")
        self._admins: frozenset[str] = frozenset(str(a) for a in admins)

    def is_admin(self, clinician_id: str) -> bool:
        return clinician_id in self._admins

    def can_read(self, clinician_id: str, patient_id: str) -> bool:
        if self.is_admin(clinician_id):
            return True
        return patient_id in self._clinicians.get(clinician_id, frozenset())


class AllowlistAuthzPolicy:
    """Concrete policy backed by a JSON file, with mtime-based hot reload.

    Behaviour:

    - If ``allowlist_path`` is ``None`` → deny everything except the
      built-in system context (``ClinicianContext.system()``).
    - If the file exists → parsed at first call and re-parsed on mtime change.
    - If the file is missing or invalid at load time → raise
      :class:`ConfigurationError`. This is a fail-closed choice: if the
      allowlist file goes missing in prod, the app refuses to serve rather
      than silently allowing.
    """

    def __init__(
        self,
        allowlist_path: Path | None,
        *,
        audit: "AuditEventEmitter | None" = None,
    ) -> None:
        self._path = allowlist_path
        self._allowlist: _Allowlist | None = None
        self._mtime: float | None = None
        # W07: audit sink is optional. When None, we fall back to the
        # log-only behaviour the W02 tests exercise. When provided (via
        # the DI container in production), every denial + grant produces
        # a structured audit event with a stable schema.
        if audit is None:
            from egp_maf.auth.audit import AuditEventEmitter, NullAuditSink

            audit = AuditEventEmitter(sink=NullAuditSink())
        self._audit = audit
        if allowlist_path is not None:
            # Eager load so a missing/invalid file fails startup.
            self._reload_if_stale()

    def _reload_if_stale(self) -> None:
        if self._path is None:
            return
        try:
            mtime = self._path.stat().st_mtime
        except FileNotFoundError as exc:
            raise ConfigurationError(
                f"AuthZ allowlist file not found: {self._path}"
            ) from exc

        if self._mtime is not None and mtime == self._mtime:
            return  # up to date

        try:
            with self._path.open("r", encoding="utf-8") as fh:
                payload = json.load(fh)
        except json.JSONDecodeError as exc:
            raise ConfigurationError(
                f"AuthZ allowlist file is not valid JSON: {self._path}"
            ) from exc

        self._allowlist = _Allowlist(payload)
        self._mtime = mtime
        _logger.info(
            "authz.allowlist.reloaded",
            extra={
                "path": str(self._path),
                "mtime": mtime,
                "clinician_count": len(self._allowlist._clinicians),  # noqa: SLF001
                "admin_count": len(self._allowlist._admins),  # noqa: SLF001
            },
        )

    def can_read(self, ctx: ClinicianContext, patient_id: str) -> bool:
        # System context is always allowed. Background jobs and tests use this.
        if ctx.clinician_id == "system" and "System" in ctx.roles:
            return True

        # No allowlist configured → deny everyone else. Fail closed.
        if self._path is None or self._allowlist is None:
            return False

        self._reload_if_stale()
        assert self._allowlist is not None  # narrowed by reload
        return self._allowlist.can_read(ctx.clinician_id, patient_id)

    def enforce_read(self, ctx: ClinicianContext, patient_id: str) -> None:
        if not self.can_read(ctx, patient_id):
            _logger.warning(
                "authz.denied",
                extra={
                    "clinician_id": ctx.clinician_id,
                    "patient_id": patient_id,
                    "route": "repository.read",
                },
            )
            self._audit.emit_authz_denied(
                clinician_id=ctx.clinician_id,
                tenant_id=ctx.tenant_id,
                patient_id=patient_id,
                reason=(
                    "clinician not on allowlist"
                    if self._path is not None
                    else "no allowlist configured (fail-closed)"
                ),
            )
            raise AccessDenied(
                f"Clinician '{ctx.clinician_id}' is not authorised to read "
                f"patient '{patient_id}'."
            )
        # Granted path — audit event lets us prove access AFTER the fact
        # (Design §21 audit retention). Not chatty on the console: the
        # LoggingAuditSink writes to the dedicated ``egp_maf.audit``
        # logger which is separately routed to the audit workspace in
        # prod. NullAuditSink (default in W02-era construction) is a
        # no-op.
        self._audit.emit_authz_granted(
            clinician_id=ctx.clinician_id,
            tenant_id=ctx.tenant_id,
            patient_id=patient_id,
        )
