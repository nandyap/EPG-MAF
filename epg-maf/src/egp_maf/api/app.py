"""FastAPI application factory.

:func:`create_app` returns a fully wired :class:`fastapi.FastAPI`
instance whose ``POST /chat`` route:

1. Requires an ``Authorization: Bearer <token>`` header.
2. Delegates token verification + role check to the DI-container's
   :class:`Authenticator` (W07 — Entra JWT in prod, stub in dev/tests).
3. Opens a root :func:`workflow_request_span` for the turn (W08).
4. Runs :meth:`WorkflowRuntime.run_turn` with a fresh
   :class:`ChatWorkflowState` built from the request body + the
   authenticated :class:`ClinicianContext` (W04+W05).
5. Extracts the terminal :class:`ChatWorkflowState`, projects it onto
   :class:`ChatResponseBody`, and stamps the response with the active
   trace id.
6. Any raised :class:`EgpError` (auth, access denied, budget, LLM
   error, DB unavailable, …) or unhandled exception is trapped by the
   W09 error handler and returned as
   :class:`ErrorResponseBody` with the mapped HTTP status.
"""

from __future__ import annotations

from typing import Any

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import ValidationError as PydanticValidationError

from egp_maf.api.schemas import (
    ChatRequestBody,
    ChatResponseBody,
    ChatSpecialistSlotView,
    ErrorResponseBody,
    HealthResponseBody,
)
from egp_maf.auth.audit import AuditEventEmitter
from egp_maf.auth.authenticator import AuthenticationError, Authenticator
from egp_maf.di.container import Container
from egp_maf.errors import EgpError
from egp_maf.logging.setup import get_logger
from egp_maf.resilience import format_error_response
from egp_maf.state.clinician_context import ClinicianContext
from egp_maf.telemetry.otel import get_current_trace_and_span_ids
from egp_maf.telemetry.spans import workflow_request_span
from egp_maf.workflow.state import (
    ChatWorkflowState,
    SessionMessage,
    SpecialistSlot,
)

_logger = get_logger(__name__)


def create_app(container: Container) -> FastAPI:
    """Return a FastAPI app wired to ``container``.

    ``container`` is a fully-built :class:`egp_maf.di.container.Container`
    (via :func:`build_container`) whose singletons this app closes over.
    """
    app = FastAPI(
        title="EGP Window",
        description="Clinical genomics decision-support agent",
        version="0.1.0",
    )
    app.state.container = container

    # ── Health probe ───────────────────────────────────────────────
    @app.get("/healthz", response_model=HealthResponseBody)
    async def healthz() -> HealthResponseBody:
        return HealthResponseBody(status="ok", env=container.settings.env)

    # ── Chat turn ──────────────────────────────────────────────────
    @app.post(
        "/chat",
        response_model=ChatResponseBody,
        responses={
            401: {"model": ErrorResponseBody},
            403: {"model": ErrorResponseBody},
            409: {"model": ErrorResponseBody},
            429: {"model": ErrorResponseBody},
            500: {"model": ErrorResponseBody},
            502: {"model": ErrorResponseBody},
            503: {"model": ErrorResponseBody},
            504: {"model": ErrorResponseBody},
        },
    )
    async def chat(
        body: ChatRequestBody,
        request: Request,
        authorization: str | None = Header(default=None),
    ) -> ChatResponseBody:
        # Root span for the whole turn so every downstream span
        # inherits the trace id.
        with workflow_request_span(
            thread_id=body.thread_id,
            patient_id=body.patient_id,
        ):
            token = _extract_bearer(authorization)
            ctx = await container.authenticator.authenticate(
                token, route="/chat"
            )

            initial = ChatWorkflowState(
                ctx=ctx,
                patient_id=body.patient_id,
                thread_id=body.thread_id,
                original_query=body.message,
                requested_diseases=body.requested_diseases,
                requested_genes=body.requested_genes,
                messages=[
                    SessionMessage(role="user", content=body.message)
                ],
            )

            result = await container.workflow_runtime.run_turn(initial)
            final = _extract_final_state(result)

            trace_id, _span_id = get_current_trace_and_span_ids()
            return _project_response(final, trace_id=trace_id)

    # ── Error handlers ─────────────────────────────────────────────
    app.add_exception_handler(EgpError, _egp_error_handler)
    app.add_exception_handler(PydanticValidationError, _validation_error_handler)
    app.add_exception_handler(Exception, _unhandled_error_handler)

    return app


# ── Helpers ────────────────────────────────────────────────────────


def _extract_bearer(header: str | None) -> str:
    """Return the bearer token from an ``Authorization`` header value.

    Raises :class:`AuthenticationError` on missing / malformed input so
    the W09 error handler maps it to HTTP 401.
    """
    if not header or not header.startswith("Bearer "):
        raise AuthenticationError("Missing or malformed bearer token")
    token = header[len("Bearer "):].strip()
    if not token:
        raise AuthenticationError("Empty bearer token")
    return token


def _extract_final_state(run_result: Any) -> ChatWorkflowState:
    """Pull the terminal :class:`ChatWorkflowState` from the run outputs."""
    outputs = run_result.get_outputs()
    for out in outputs:
        if isinstance(out, ChatWorkflowState):
            return out
    raise EgpError("Workflow produced no terminal ChatWorkflowState output")


def _slot_to_view(slot: SpecialistSlot | None) -> ChatSpecialistSlotView | None:
    if slot is None:
        return None
    return ChatSpecialistSlotView(
        status=slot.status,
        output=slot.output,
        errors=list(slot.errors),
    )


def _reply_from(final: ChatWorkflowState) -> str:
    """Extract the assistant reply from the terminal state.

    Synthesis appends an ``assistant`` message; if the workflow ran to
    completion with clinical data the last assistant message is the
    clinician-visible answer. If not, we return an empty string and
    the client sees only the slots.
    """
    for msg in reversed(final.messages):
        if msg.role == "assistant":
            return msg.content
    return ""


def _project_response(
    final: ChatWorkflowState, *, trace_id: str | None
) -> ChatResponseBody:
    return ChatResponseBody(
        thread_id=final.thread_id,
        patient_id=final.patient_id,
        trace_id=trace_id,
        reply=_reply_from(final),
        agents_completed=list(final.agents_completed),
        prs=_slot_to_view(final.prs),
        genomic_variants=_slot_to_view(final.genomic_variants),
        family_history=_slot_to_view(final.family_history),
        pgx=_slot_to_view(final.pgx),
        phenotype=_slot_to_view(final.phenotype),
    )


# ── Exception handlers ────────────────────────────────────────────


async def _egp_error_handler(request: Request, exc: Exception) -> JSONResponse:
    """Map any :class:`EgpError` to the W09 response envelope."""
    assert isinstance(exc, EgpError)
    trace_id, _ = get_current_trace_and_span_ids()
    envelope = format_error_response(exc, trace_id=trace_id)
    _logger.warning(
        "http.egp_error",
        error_code=envelope.error_code,
        http_status=envelope.http_status,
        trace_id=trace_id,
    )
    return JSONResponse(
        status_code=envelope.http_status,
        content=envelope.to_dict(),
    )


async def _validation_error_handler(
    request: Request, exc: Exception
) -> JSONResponse:
    """FastAPI request-body validation → HTTP 400 with a safe body."""
    trace_id, _ = get_current_trace_and_span_ids()
    return JSONResponse(
        status_code=400,
        content={
            "error_code": "validation_error",
            "message": "Request body failed validation.",
            "trace_id": trace_id,
        },
    )


async def _unhandled_error_handler(
    request: Request, exc: Exception
) -> JSONResponse:
    """Last-resort handler — coerces anything unknown to ``internal_error``."""
    if isinstance(exc, HTTPException):
        # FastAPI's own exceptions carry their own status; re-raise so
        # the default handler runs.
        raise exc
    trace_id, _ = get_current_trace_and_span_ids()
    envelope = format_error_response(exc, trace_id=trace_id)
    _logger.exception(
        "http.unhandled_error",
        error_code=envelope.error_code,
        trace_id=trace_id,
    )
    return JSONResponse(
        status_code=envelope.http_status,
        content=envelope.to_dict(),
    )
