"""Span context managers per span kind (Design §20.2, §20.3).

Every span in this codebase should be created via one of the context
managers below. Rationale:

- Uniform naming (``workflow.request``, ``workflow.executor``,
  ``specialist.<name>``, ``tool.call``, ``llm.call``,
  ``repository.<name>``, ``db.query``).
- Uniform attribute application via
  :func:`egp_maf.telemetry.phi_safe.safe_set_attribute` — the only
  path allowed to set attributes on our spans (import-linter rule).
- Uniform error-recording on span exit.

Each context manager yields the OTEL :class:`Span` so callers can set
domain-specific attributes with :func:`safe_set_attribute`. Errors are
recorded and the span is marked with status ``ERROR`` before being
re-raised.

Usage:

.. code-block:: python

    from egp_maf.telemetry import specialist_span, safe_set_attribute

    with specialist_span("prs", patient_id=pid) as span:
        safe_set_attribute(span, "specialist.tool_call_count", 3)
        # ... run specialist ...
"""

from __future__ import annotations

from contextlib import contextmanager
from enum import Enum
from time import monotonic
from typing import Any, Iterator

from opentelemetry import trace
from opentelemetry.trace import Span, SpanKind as _OtelSpanKind, Status, StatusCode

from egp_maf.telemetry.attributes import filter_safe_attributes
from egp_maf.telemetry.phi_safe import safe_set_attribute


class SpanKind(str, Enum):
    """Canonical span-kind identifiers used across the codebase."""

    WORKFLOW_REQUEST = "workflow.request"
    WORKFLOW_EXECUTOR = "workflow.executor"
    SPECIALIST = "workflow.specialist"
    TOOL_CALL = "tool.call"
    LLM_CALL = "llm.call"
    REPOSITORY = "repository"
    DB_QUERY = "db.query"


_TRACER_NAME = "egp_maf"


def _tracer() -> Any:
    return trace.get_tracer(_TRACER_NAME)


def _apply_attrs(span: Span, attrs: dict[str, object]) -> None:
    """Set every attribute in ``attrs`` via the PHI-safe path."""
    for key, value in attrs.items():
        try:
            safe_set_attribute(span, key, value)
        except Exception:  # noqa: BLE001 — never fail the workload on span attrs
            # Forbidden attribute or bad value — log at debug + drop.
            continue


def _record_exception(span: Span, exc: BaseException) -> None:
    """Attach error info to ``span`` before re-raising."""
    safe_set_attribute(span, "error.class", type(exc).__name__)
    # ``error.message`` may carry sensitive info — we truncate hard.
    message = str(exc)[:200]
    safe_set_attribute(span, "error.message", message)
    code = getattr(exc, "error_code", None)
    if isinstance(code, str):
        safe_set_attribute(span, "error.code", code)
    span.set_status(Status(StatusCode.ERROR, description=message))


# ── Public context managers per kind ────────────────────────────────


@contextmanager
def workflow_request_span(
    *,
    thread_id: str,
    clinician_id: str | None = None,
    patient_id: str | None = None,
    **extra: object,
) -> Iterator[Span]:
    """Root span for one clinician turn."""
    attrs = filter_safe_attributes(
        {
            "workflow.name": "egp_chat_workflow",
            "thread_id": thread_id,
            "clinician_id": clinician_id,
            "patient_id": patient_id,
            **extra,
        }
    )
    with _tracer().start_as_current_span(
        SpanKind.WORKFLOW_REQUEST.value,
        kind=_OtelSpanKind.SERVER,
    ) as span:
        _apply_attrs(span, attrs)
        try:
            yield span
        except BaseException as exc:
            _record_exception(span, exc)
            raise


@contextmanager
def workflow_executor_span(
    executor_name: str,
    **extra: object,
) -> Iterator[Span]:
    """Per-executor span inside the workflow."""
    attrs = filter_safe_attributes(
        {
            "workflow.executor": executor_name,
            **extra,
        }
    )
    with _tracer().start_as_current_span(
        SpanKind.WORKFLOW_EXECUTOR.value,
        kind=_OtelSpanKind.INTERNAL,
    ) as span:
        _apply_attrs(span, attrs)
        try:
            yield span
        except BaseException as exc:
            _record_exception(span, exc)
            raise


@contextmanager
def specialist_span(
    specialist_name: str,
    *,
    patient_id: str | None = None,
    **extra: object,
) -> Iterator[Span]:
    """One specialist run."""
    started = monotonic()
    attrs = filter_safe_attributes(
        {
            "specialist.name": specialist_name,
            "patient_id": patient_id,
            **extra,
        }
    )
    with _tracer().start_as_current_span(
        f"{SpanKind.SPECIALIST.value}.{specialist_name}",
        kind=_OtelSpanKind.INTERNAL,
    ) as span:
        _apply_attrs(span, attrs)
        try:
            yield span
        except BaseException as exc:
            _record_exception(span, exc)
            safe_set_attribute(span, "specialist.status", "failed")
            raise
        else:
            safe_set_attribute(span, "specialist.status", "completed")
        finally:
            safe_set_attribute(
                span,
                "specialist.duration_ms",
                int((monotonic() - started) * 1000),
            )


@contextmanager
def tool_span(tool_name: str, **extra: object) -> Iterator[Span]:
    """One tool invocation."""
    started = monotonic()
    attrs = filter_safe_attributes({"tool.name": tool_name, **extra})
    with _tracer().start_as_current_span(
        SpanKind.TOOL_CALL.value, kind=_OtelSpanKind.INTERNAL
    ) as span:
        _apply_attrs(span, attrs)
        try:
            yield span
        except BaseException as exc:
            _record_exception(span, exc)
            raise
        finally:
            safe_set_attribute(
                span, "tool.duration_ms", int((monotonic() - started) * 1000)
            )


@contextmanager
def llm_span(
    model: str,
    phase: str,
    *,
    structured_output: bool = False,
    **extra: object,
) -> Iterator[Span]:
    """One LLM API call. ``phase`` = ``react`` | ``extract`` | ``synthesize`` | …"""
    started = monotonic()
    attrs = filter_safe_attributes(
        {
            "llm.model": model,
            "llm.phase": phase,
            "llm.structured_output": structured_output,
            **extra,
        }
    )
    with _tracer().start_as_current_span(
        SpanKind.LLM_CALL.value, kind=_OtelSpanKind.CLIENT
    ) as span:
        _apply_attrs(span, attrs)
        try:
            yield span
        except BaseException as exc:
            _record_exception(span, exc)
            raise
        finally:
            safe_set_attribute(
                span, "llm.duration_ms", int((monotonic() - started) * 1000)
            )


@contextmanager
def repository_span(
    name: str,
    method: str,
    **extra: object,
) -> Iterator[Span]:
    """One Repository call (higher-level than :func:`db_span`)."""
    started = monotonic()
    attrs = filter_safe_attributes(
        {
            "repository.name": name,
            "repository.method": method,
            **extra,
        }
    )
    with _tracer().start_as_current_span(
        f"{SpanKind.REPOSITORY.value}.{name}.{method}",
        kind=_OtelSpanKind.INTERNAL,
    ) as span:
        _apply_attrs(span, attrs)
        try:
            yield span
        except BaseException as exc:
            _record_exception(span, exc)
            raise
        finally:
            safe_set_attribute(
                span,
                "repository.duration_ms",
                int((monotonic() - started) * 1000),
            )


@contextmanager
def db_span(
    table: str,
    operation: str = "SELECT",
    **extra: object,
) -> Iterator[Span]:
    """One SQL statement."""
    started = monotonic()
    attrs = filter_safe_attributes(
        {
            "db.system": "postgresql",
            "db.table": table,
            "db.operation": operation,
            **extra,
        }
    )
    with _tracer().start_as_current_span(
        SpanKind.DB_QUERY.value, kind=_OtelSpanKind.CLIENT
    ) as span:
        _apply_attrs(span, attrs)
        try:
            yield span
        except BaseException as exc:
            _record_exception(span, exc)
            raise
        finally:
            safe_set_attribute(
                span, "db.duration_ms", int((monotonic() - started) * 1000)
            )
