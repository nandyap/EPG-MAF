"""Structured audit events for authn/authz outcomes.

W07 F09.4: every allowed or denied read produces a structured audit
event with a stable schema. The event schema is:

.. code-block:: json

    {
        "event": "authz.denied",
        "clinician_id": "abc-…",
        "tenant_id": "…",
        "patient_id": "P0001",
        "route": "repository.read",
        "outcome": "denied",
        "reason": "not on allowlist",
        "trace_id": null,
        "timestamp": "2026-07-10T10:00:00Z"
    }

Sinks are pluggable:

- :class:`LoggingAuditSink` — production default; emits to the process
  logger under the ``authz`` category with the event payload as
  ``extra``. W08 (OTEL) will replace or complement this with an
  ``application-audit`` LAW workspace shipper.
- :class:`NullAuditSink` — for tests that don't care about audit
  side-effects.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field

AuditOutcome = Literal["granted", "denied", "invalid_token", "role_denied"]

_AUDIT_LOGGER_NAME = "egp_maf.audit"


class AuditEvent(BaseModel):
    """One authz/authn audit event.

    Held as a Pydantic model so serialisation is deterministic across
    sinks and the shape can be validated in tests.
    """

    event: str = Field(
        description=(
            "Event name — one of ``authz.granted``, ``authz.denied``, "
            "``auth.token_invalid``, ``auth.role_denied``."
        )
    )
    outcome: AuditOutcome
    clinician_id: str | None = None
    tenant_id: str | None = None
    patient_id: str | None = None
    route: str | None = None
    reason: str | None = None
    trace_id: str | None = None
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )

    model_config = ConfigDict(extra="forbid")


class AuditSink(Protocol):
    """Where audit events go."""

    def emit(self, event: AuditEvent) -> None: ...


class NullAuditSink:
    """No-op sink. Useful in unit tests that don't care about audit."""

    def emit(self, event: AuditEvent) -> None:  # noqa: ARG002 — intentional
        return None


class LoggingAuditSink:
    """Emits each event as a structured log record on the
    ``egp_maf.audit`` logger.

    Log shape: message = ``event.event``; extras contain every populated
    field on the event (timestamp serialised as ISO string). Consumers
    (App Insights, LAW workspace) parse the extras as structured
    columns.
    """

    def __init__(self, logger_name: str = _AUDIT_LOGGER_NAME) -> None:
        self._logger = logging.getLogger(logger_name)

    def emit(self, event: AuditEvent) -> None:
        payload = event.model_dump(mode="json")
        # ``event`` is the log-level message; the rest goes as extras.
        message = payload.pop("event", "authz.event")
        self._logger.info(message, extra=payload)


class AuditEventEmitter:
    """Thin façade over an :class:`AuditSink` with domain-specific
    ``emit_*`` methods so callers don't have to build the event manually.
    """

    def __init__(self, sink: AuditSink | None = None) -> None:
        self._sink: AuditSink = sink or LoggingAuditSink()

    def emit_authz_granted(
        self,
        *,
        clinician_id: str,
        tenant_id: str,
        patient_id: str,
        route: str = "repository.read",
        trace_id: str | None = None,
    ) -> None:
        self._sink.emit(
            AuditEvent(
                event="authz.granted",
                outcome="granted",
                clinician_id=clinician_id,
                tenant_id=tenant_id,
                patient_id=patient_id,
                route=route,
                trace_id=trace_id,
            )
        )

    def emit_authz_denied(
        self,
        *,
        clinician_id: str,
        tenant_id: str,
        patient_id: str,
        reason: str,
        route: str = "repository.read",
        trace_id: str | None = None,
    ) -> None:
        self._sink.emit(
            AuditEvent(
                event="authz.denied",
                outcome="denied",
                clinician_id=clinician_id,
                tenant_id=tenant_id,
                patient_id=patient_id,
                route=route,
                reason=reason,
                trace_id=trace_id,
            )
        )

    def emit_auth_token_invalid(
        self,
        *,
        reason: str,
        route: str = "api.request",
        trace_id: str | None = None,
    ) -> None:
        self._sink.emit(
            AuditEvent(
                event="auth.token_invalid",
                outcome="invalid_token",
                route=route,
                reason=reason,
                trace_id=trace_id,
            )
        )

    def emit_auth_role_denied(
        self,
        *,
        clinician_id: str,
        tenant_id: str,
        required_role: str,
        roles_present: list[str],
        route: str = "api.request",
        trace_id: str | None = None,
    ) -> None:
        reason = (
            f"required role {required_role!r} not present; "
            f"roles={sorted(roles_present)!r}"
        )
        self._sink.emit(
            AuditEvent(
                event="auth.role_denied",
                outcome="role_denied",
                clinician_id=clinician_id,
                tenant_id=tenant_id,
                route=route,
                reason=reason,
                trace_id=trace_id,
            )
        )
