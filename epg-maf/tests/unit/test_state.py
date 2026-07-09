"""Unit tests for :class:`egp_maf.state.session_document.SessionDocument` and
:class:`egp_maf.state.clinician_context.ClinicianContext`."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from egp_maf.state.clinician_context import ClinicianContext
from egp_maf.state.session_document import (
    CURRENT_SCHEMA_VERSION,
    SessionDocument,
    SessionMessage,
)


# ── ClinicianContext ─────────────────────────────────────────────────


class TestClinicianContext:
    def test_construction(self) -> None:
        ctx = ClinicianContext(
            clinician_id="c1",
            tenant_id="t1",
            roles=frozenset({"Clinician"}),
        )
        assert ctx.has_role("Clinician") is True
        assert ctx.has_role("Admin") is False

    def test_frozen(self) -> None:
        ctx = ClinicianContext(clinician_id="c1", tenant_id="t1")
        with pytest.raises(ValidationError):
            ctx.clinician_id = "other"  # type: ignore[misc]

    def test_system_factory(self) -> None:
        ctx = ClinicianContext.system()
        assert ctx.clinician_id == "system"
        assert ctx.has_role("System")

    def test_to_span_attributes_no_phi(self) -> None:
        ctx = ClinicianContext(
            clinician_id="c1",
            tenant_id="t1",
            roles=frozenset({"Clinician"}),
        )
        attrs = ctx.to_span_attributes()
        assert attrs == {"clinician_id": "c1", "tenant_id": "t1"}
        assert "roles" not in attrs
        assert "token_expires_at" not in attrs


# ── SessionMessage ───────────────────────────────────────────────────


class TestSessionMessage:
    def test_construction(self) -> None:
        m = SessionMessage(role="user", content="hi")
        assert m.role == "user"
        assert m.timestamp.tzinfo == timezone.utc

    def test_invalid_role_rejected(self) -> None:
        with pytest.raises(ValidationError):
            SessionMessage(role="not-a-role", content="x")  # type: ignore[arg-type]


# ── SessionDocument ──────────────────────────────────────────────────


def _fresh_doc() -> SessionDocument:
    return SessionDocument(
        thread_id="th-1",
        clinician_id="c1",
        tenant_id="t1",
        patient_id="P001",
    )


class TestSessionDocument:
    def test_minimal_construction(self) -> None:
        d = _fresh_doc()
        assert d.schema_version == CURRENT_SCHEMA_VERSION
        assert d.ttl == 86400
        assert d.messages == []
        assert d.agents_completed == []
        assert d.results == {}
        assert d.etag is None

    def test_round_trip_json(self) -> None:
        d = _fresh_doc()
        payload = d.model_dump(mode="json")
        # ETag is excluded from serialisation.
        assert "etag" not in payload
        rehydrated = SessionDocument.model_validate(payload)
        assert rehydrated.thread_id == d.thread_id
        assert rehydrated.patient_id == d.patient_id

    def test_extra_fields_rejected(self) -> None:
        with pytest.raises(ValidationError):
            SessionDocument.model_validate(
                {
                    "thread_id": "t",
                    "clinician_id": "c",
                    "tenant_id": "t1",
                    "patient_id": "p",
                    "unexpected_field": "boom",
                }
            )

    def test_with_message_appends(self) -> None:
        d = _fresh_doc()
        d2 = d.with_message(SessionMessage(role="user", content="hi"))
        assert len(d.messages) == 0
        assert len(d2.messages) == 1
        assert d2.messages[0].content == "hi"

    def test_with_agent_completed_dedupes(self) -> None:
        d = _fresh_doc()
        d2 = d.with_agent_completed("prs")
        d3 = d2.with_agent_completed("prs")
        assert d3.agents_completed == ["prs"]

    def test_with_agent_completed_sorted(self) -> None:
        d = _fresh_doc()
        d2 = d.with_agent_completed("prs").with_agent_completed("chat")
        # Sort provides deterministic order regardless of insertion.
        assert d2.agents_completed == sorted(d2.agents_completed)

    def test_without_agent_removes_slot_and_completion(self) -> None:
        d = _fresh_doc().model_copy(
            update={
                "agents_completed": ["prs", "phenotype"],
                "results": {"prs": {"status": "complete"}, "phenotype": {}},
            }
        )
        d2 = d.without_agent("prs")
        assert "prs" not in d2.agents_completed
        assert "prs" not in d2.results
        assert "phenotype" in d2.agents_completed
        assert "phenotype" in d2.results

    def test_immutability_by_copy(self) -> None:
        d = _fresh_doc()
        _ = d.with_message(SessionMessage(role="user", content="x"))
        # Original untouched.
        assert d.messages == []
