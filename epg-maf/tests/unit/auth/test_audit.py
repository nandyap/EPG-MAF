"""Tests for :mod:`egp_maf.auth.audit`."""

from __future__ import annotations

import logging

import pytest

from egp_maf.auth.audit import (
    AuditEvent,
    AuditEventEmitter,
    LoggingAuditSink,
    NullAuditSink,
)

pytestmark = pytest.mark.unit


class _CapturingSink:
    def __init__(self) -> None:
        self.events: list[AuditEvent] = []

    def emit(self, event: AuditEvent) -> None:
        self.events.append(event)


class TestAuditEventShape:
    def test_forbids_unknown_fields(self) -> None:
        with pytest.raises(Exception):
            AuditEvent(
                event="authz.granted",
                outcome="granted",
                unknown="x",  # type: ignore[call-arg]
            )

    def test_serialisable_json_shape(self) -> None:
        ev = AuditEvent(
            event="authz.denied",
            outcome="denied",
            clinician_id="c",
            tenant_id="t",
            patient_id="P1",
            reason="not on allowlist",
        )
        payload = ev.model_dump(mode="json")
        assert payload["event"] == "authz.denied"
        assert payload["outcome"] == "denied"
        assert "timestamp" in payload


class TestAuditEmitterMethods:
    def test_emit_granted(self) -> None:
        sink = _CapturingSink()
        emitter = AuditEventEmitter(sink=sink)
        emitter.emit_authz_granted(
            clinician_id="c", tenant_id="t", patient_id="P1"
        )
        assert len(sink.events) == 1
        ev = sink.events[0]
        assert ev.event == "authz.granted"
        assert ev.outcome == "granted"
        assert ev.clinician_id == "c"
        assert ev.patient_id == "P1"
        assert ev.route == "repository.read"

    def test_emit_denied(self) -> None:
        sink = _CapturingSink()
        emitter = AuditEventEmitter(sink=sink)
        emitter.emit_authz_denied(
            clinician_id="c",
            tenant_id="t",
            patient_id="P1",
            reason="not on allowlist",
        )
        assert sink.events[0].event == "authz.denied"
        assert sink.events[0].reason == "not on allowlist"

    def test_emit_token_invalid(self) -> None:
        sink = _CapturingSink()
        emitter = AuditEventEmitter(sink=sink)
        emitter.emit_auth_token_invalid(reason="bad signature")
        ev = sink.events[0]
        assert ev.event == "auth.token_invalid"
        assert ev.outcome == "invalid_token"
        assert ev.clinician_id is None

    def test_emit_role_denied(self) -> None:
        sink = _CapturingSink()
        emitter = AuditEventEmitter(sink=sink)
        emitter.emit_auth_role_denied(
            clinician_id="c",
            tenant_id="t",
            required_role="Clinician",
            roles_present=["Auditor"],
        )
        ev = sink.events[0]
        assert ev.event == "auth.role_denied"
        assert ev.outcome == "role_denied"
        assert "Clinician" in (ev.reason or "")


class TestLoggingAuditSink:
    def test_logs_event_at_info(self, caplog: pytest.LogCaptureFixture) -> None:
        sink = LoggingAuditSink()
        # LogCaptureFixture attaches at root level; explicitly enable
        # the audit logger for INFO regardless of default handler config.
        with caplog.at_level(logging.INFO, logger="egp_maf.audit"):
            sink.emit(
                AuditEvent(
                    event="authz.granted",
                    outcome="granted",
                    clinician_id="c",
                    tenant_id="t",
                    patient_id="P1",
                )
            )
        # At least one record with our message text.
        matches = [r for r in caplog.records if r.message == "authz.granted"]
        assert matches, "expected an authz.granted log record"
        rec = matches[0]
        assert getattr(rec, "outcome", None) == "granted"
        assert getattr(rec, "clinician_id", None) == "c"
        assert getattr(rec, "patient_id", None) == "P1"


class TestNullAuditSink:
    def test_null_sink_is_noop(self) -> None:
        sink = NullAuditSink()
        # Should not raise.
        sink.emit(AuditEvent(event="authz.granted", outcome="granted"))
