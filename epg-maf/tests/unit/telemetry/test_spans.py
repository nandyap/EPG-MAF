"""Tests for :mod:`egp_maf.telemetry.spans`."""

from __future__ import annotations

import pytest
from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
    InMemorySpanExporter,
)

from egp_maf.telemetry.phi_safe import ForbiddenAttributeError, safe_set_attribute
from egp_maf.telemetry.spans import (
    SpanKind,
    db_span,
    llm_span,
    repository_span,
    specialist_span,
    tool_span,
    workflow_executor_span,
    workflow_request_span,
)

pytestmark = pytest.mark.unit


class TestWorkflowRequestSpan:
    def test_emits_span_with_expected_attributes(
        self, telemetry_exporter: InMemorySpanExporter
    ) -> None:
        with workflow_request_span(
            thread_id="T1", clinician_id="c-1", patient_id="P1"
        ):
            pass
        spans = telemetry_exporter.get_finished_spans()
        assert any(s.name == SpanKind.WORKFLOW_REQUEST.value for s in spans)
        span = next(s for s in spans if s.name == SpanKind.WORKFLOW_REQUEST.value)
        assert span.attributes.get("thread_id") == "T1"
        assert span.attributes.get("clinician_id") == "c-1"
        assert span.attributes.get("patient_id") == "P1"

    def test_records_exception_and_error_status(
        self, telemetry_exporter: InMemorySpanExporter
    ) -> None:
        with pytest.raises(RuntimeError, match="boom"):
            with workflow_request_span(thread_id="T1"):
                raise RuntimeError("boom")
        spans = telemetry_exporter.get_finished_spans()
        span = next(s for s in spans if s.name == SpanKind.WORKFLOW_REQUEST.value)
        assert span.status.status_code.name == "ERROR"
        assert span.attributes.get("error.class") == "RuntimeError"


class TestNestedSpans:
    def test_child_inherits_trace_id(
        self, telemetry_exporter: InMemorySpanExporter
    ) -> None:
        with workflow_request_span(thread_id="T1"):
            with workflow_executor_span("chat_router"):
                pass
        spans = telemetry_exporter.get_finished_spans()
        parent = next(s for s in spans if s.name == SpanKind.WORKFLOW_REQUEST.value)
        child = next(s for s in spans if s.name == SpanKind.WORKFLOW_EXECUTOR.value)
        assert child.context.trace_id == parent.context.trace_id
        assert child.parent.span_id == parent.context.span_id


class TestSpecialistSpan:
    def test_success_records_completed_status(
        self, telemetry_exporter: InMemorySpanExporter
    ) -> None:
        with specialist_span("prs", patient_id="P1"):
            pass
        spans = telemetry_exporter.get_finished_spans()
        span = next(
            s for s in spans if s.name == f"{SpanKind.SPECIALIST.value}.prs"
        )
        assert span.attributes.get("specialist.name") == "prs"
        assert span.attributes.get("specialist.status") == "completed"
        assert "specialist.duration_ms" in span.attributes

    def test_failure_records_failed_status(
        self, telemetry_exporter: InMemorySpanExporter
    ) -> None:
        with pytest.raises(ValueError):
            with specialist_span("prs"):
                raise ValueError("boom")
        spans = telemetry_exporter.get_finished_spans()
        span = next(
            s for s in spans if s.name == f"{SpanKind.SPECIALIST.value}.prs"
        )
        assert span.attributes.get("specialist.status") == "failed"


class TestToolAndLlmAndDbSpans:
    def test_tool_span(self, telemetry_exporter: InMemorySpanExporter) -> None:
        with tool_span("get_patient_prs") as span:
            safe_set_attribute(span, "tool.row_count", 3)
        span = next(
            s for s in telemetry_exporter.get_finished_spans()
            if s.name == SpanKind.TOOL_CALL.value
        )
        assert span.attributes.get("tool.name") == "get_patient_prs"
        assert span.attributes.get("tool.row_count") == 3
        assert "tool.duration_ms" in span.attributes

    def test_llm_span(self, telemetry_exporter: InMemorySpanExporter) -> None:
        with llm_span(model="gpt-4o-mini", phase="react") as span:
            safe_set_attribute(span, "llm.prompt_tokens", 128)
        span = next(
            s for s in telemetry_exporter.get_finished_spans()
            if s.name == SpanKind.LLM_CALL.value
        )
        assert span.attributes.get("llm.model") == "gpt-4o-mini"
        assert span.attributes.get("llm.phase") == "react"
        assert span.attributes.get("llm.prompt_tokens") == 128
        assert "llm.duration_ms" in span.attributes

    def test_db_span_with_row_count(
        self, telemetry_exporter: InMemorySpanExporter
    ) -> None:
        with db_span("patient_prs") as span:
            safe_set_attribute(span, "db.row_count", 42)
        span = next(
            s for s in telemetry_exporter.get_finished_spans()
            if s.name == SpanKind.DB_QUERY.value
        )
        assert span.attributes.get("db.table") == "patient_prs"
        assert span.attributes.get("db.operation") == "SELECT"
        assert span.attributes.get("db.row_count") == 42

    def test_repository_span(self, telemetry_exporter: InMemorySpanExporter) -> None:
        with repository_span("PRSRepository", "get_patient_prs"):
            pass
        # Note: span name is namespaced per repo + method
        span = next(
            s for s in telemetry_exporter.get_finished_spans()
            if "repository.PRSRepository.get_patient_prs" in s.name
        )
        assert span.attributes.get("repository.method") == "get_patient_prs"


class TestPhiSafetyInSpans:
    def test_span_helper_ignores_forbidden_extras(
        self, telemetry_exporter: InMemorySpanExporter
    ) -> None:
        """Filter drops forbidden extras silently at the helper boundary."""
        with specialist_span(
            "prs",
            patient_id="P1",
            search_context_notes="MUST-NOT-APPEAR",
        ):
            pass
        span = next(
            s for s in telemetry_exporter.get_finished_spans()
            if s.name == f"{SpanKind.SPECIALIST.value}.prs"
        )
        assert "search_context_notes" not in (span.attributes or {})

    def test_direct_safe_set_forbidden_raises(
        self, telemetry_exporter: InMemorySpanExporter
    ) -> None:
        with pytest.raises(ForbiddenAttributeError):
            with specialist_span("prs") as span:
                safe_set_attribute(span, "prompt_text", "no")
