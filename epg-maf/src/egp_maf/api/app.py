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

from contextlib import asynccontextmanager
from typing import Any

from fastapi import Depends, FastAPI, Header, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from pydantic import ValidationError as PydanticValidationError

from egp_maf.api.schemas import (
    ChatRequestBody,
    ChatResponseBody,
    ChatSpecialistSlotView,
    ErrorResponseBody,
    HealthResponseBody,
    ThreadCreateRequest,
    ThreadCreateResponse,
    ThreadDetailResponse,
    ThreadListItem,
    ThreadListResponse,
    ThreadMessageView,
    UserIdentityResponse,
)
from egp_maf.auth.audit import AuditEventEmitter
from egp_maf.auth.authenticator import AuthenticationError, Authenticator
from egp_maf.di.container import Container
from egp_maf.errors import (
    AccessDenied,
    EgpError,
    PatientUnavailable,
    ThreadPatientMismatch,
)
from egp_maf.logging.setup import get_logger
from egp_maf.resilience import format_error_response
from egp_maf.state.clinician_context import ClinicianContext
from egp_maf.state.session_document import SessionDocument
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

    @asynccontextmanager
    async def _lifespan(_app: FastAPI):
        # Open Cosmos client, Postgres pool, PromptService, telemetry.
        await container.startup()
        try:
            yield
        finally:
            await container.shutdown()

    app = FastAPI(
        title="EGP Window",
        description="Clinical genomics decision-support agent",
        version="0.1.0",
        lifespan=_lifespan,
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

            # Slice 1: enforce thread pin.
            # ``body.patient_id`` must equal the ``patient_id`` recorded
            # on the thread at creation time. A new patient means a new
            # thread. See ADR B-002 + B-005.
            #
            # Returns the loaded document so the turn reads Cosmos once:
            # the pin check, the history hydration below and the
            # write-back afterwards all share it.
            thread_doc = await _enforce_thread_pin(
                container=container,
                ctx=ctx,
                body_thread_id=body.thread_id,
                body_patient_id=body.patient_id,
                body_message=body.message,
            )

            # Slice 3: single-patient scope guardrail.
            # ScopeGuard is deterministic (regex + keyword rules) and
            # runs synchronously — no LLM call. A refusal short-circuits
            # the workflow and returns a clinician-friendly reply.
            trace_id_early, _ = get_current_trace_and_span_ids()
            scope_decision = container.scope_guard.check(
                message=body.message,
                session_patient_id=body.patient_id,
            )
            if scope_decision.is_refusal():
                # Emit both a structured log line and a real audit event
                # (B-006 sink deferred; the shape is stable).
                _logger.warning(
                    "scope.guard.refused",
                    thread_id=body.thread_id,
                    clinician_id=ctx.clinician_id,
                    patient_id=body.patient_id,
                    reason=scope_decision.reason,
                    matched_ids=scope_decision.matched_ids,
                )
                container.audit_emitter.emit_scope_violation(
                    clinician_id=ctx.clinician_id,
                    tenant_id=ctx.tenant_id,
                    patient_id=body.patient_id,
                    reason=scope_decision.reason,
                    trace_id=trace_id_early,
                )
                # Slice 5 (B-009): persist the refusal so history is
                # complete on refresh.
                await _persist_refusal_messages(
                    container=container,
                    ctx=ctx,
                    thread_id=body.thread_id,
                    user_message=body.message,
                    refusal_reply=scope_decision.refusal_message or "",
                    doc=thread_doc,
                )
                return _refusal_response(
                    body=body,
                    refusal_message=scope_decision.refusal_message or "",
                    trace_id=trace_id_early,
                )

            # Rehydrate the conversation and the cached specialist state
            # from the thread. Without this every turn looks like the
            # first one: the chat router sees no history and no cached
            # domains, so it can neither resolve a follow-up question
            # ("what about her sister?") nor skip a specialist that
            # already ran. ``ChatWorkflowState`` has always documented
            # itself as "rehydrated from SessionDocument at start of
            # turn" — this is the code that makes that true.
            initial = ChatWorkflowState(
                ctx=ctx,
                patient_id=body.patient_id,
                thread_id=body.thread_id,
                original_query=body.message,
                requested_diseases=body.requested_diseases,
                requested_genes=body.requested_genes,
                messages=[
                    *_history_from(thread_doc),
                    SessionMessage(role="user", content=body.message),
                ],
                agents_completed=list(
                    thread_doc.agents_completed if thread_doc else []
                ),
                **_slots_from(thread_doc),
            )

            result = await container.workflow_runtime.run_turn(initial)
            final = _extract_final_state(result)

            trace_id, _span_id = get_current_trace_and_span_ids()

            # Slice 5 (B-009): persist the user + assistant messages
            # back onto the thread so ``GET /threads/{id}`` returns the
            # full transcript on refresh.
            await _persist_turn_messages(
                container=container,
                ctx=ctx,
                thread_id=body.thread_id,
                user_message=body.message,
                final=final,
                doc=thread_doc,
            )

            return _project_response(final, trace_id=trace_id)

    # ── Threads (Slice 1 — B-002 + B-005) ──────────────────────────
    @app.post(
        "/threads",
        response_model=ThreadCreateResponse,
        responses={
            401: {"model": ErrorResponseBody},
            404: {"model": ErrorResponseBody},
        },
    )
    async def create_thread(
        body: ThreadCreateRequest,
        request: Request,
        authorization: str | None = Header(default=None),
    ) -> ThreadCreateResponse:
        """Open a new chat pinned to ``body.patient_id``.

        Returns HTTP 404 (``patient_unavailable``) with an identical body
        when the patient does not exist OR the clinician is not
        allow-listed. Prevents caller from enumerating patient existence
        by response inspection.
        """
        token = _extract_bearer(authorization)
        ctx = await container.authenticator.authenticate(
            token, route="/threads"
        )

        # Allowlist check — deliberately swallow ``AccessDenied`` and
        # translate to the identical ``PatientUnavailable`` used for
        # "patient does not exist".
        try:
            container.authz_policy.enforce_read(ctx, body.patient_id)
        except AccessDenied:
            _logger.debug(
                "threads.create.access_denied",
                clinician_id=ctx.clinician_id,
                patient_id=body.patient_id,
                reason="access_denied",
            )
            raise PatientUnavailable(
                f"Patient {body.patient_id} is not available for this session."
            )

        # Existence check would go here once a patient repository is wired.
        # For now the allowlist doubles as the existence check — a
        # patient a clinician isn't allow-listed for is indistinguishable
        # from a non-existent patient from the caller's perspective,
        # which is the exact enumeration-defence property we want.

        thread = await container.thread_state_provider.create_thread(
            clinician_id=ctx.clinician_id,
            tenant_id=ctx.tenant_id,
            patient_id=body.patient_id,
            title=body.title,
        )
        _logger.info(
            "threads.created",
            thread_id=thread.thread_id,
            clinician_id=ctx.clinician_id,
            patient_id=body.patient_id,
            has_title=body.title is not None,
        )
        return ThreadCreateResponse(
            thread_id=thread.thread_id,
            patient_id=thread.patient_id,
            title=thread.title,
            created_at=thread.created_at,
        )

    @app.get(
        "/threads",
        response_model=ThreadListResponse,
        responses={401: {"model": ErrorResponseBody}, 403: {"model": ErrorResponseBody}},
    )
    async def list_threads(
        request: Request,
        patient_id: str | None = None,
        limit: int = 50,
        authorization: str | None = Header(default=None),
    ) -> ThreadListResponse:
        """Return the clinician's threads.

        - ``?patient_id=X`` → threads for that patient only (403 if the
          clinician is not allow-listed for the patient).
        - No query param → the clinician's most recent threads across
          all patients (Slice 2 — sidebar initial load).
        """
        token = _extract_bearer(authorization)
        ctx = await container.authenticator.authenticate(
            token, route="/threads"
        )
        limit = max(1, min(limit, 200))

        if patient_id is not None:
            container.authz_policy.enforce_read(ctx, patient_id)
            docs = await container.thread_state_provider.list_by_patient(
                clinician_id=ctx.clinician_id,
                patient_id=patient_id,
                limit=limit,
            )
        else:
            docs = await container.thread_state_provider.list_recent(
                clinician_id=ctx.clinician_id,
                limit=limit,
            )

        items = [
            ThreadListItem(
                thread_id=d.thread_id,
                patient_id=d.patient_id,
                title=d.title,
                last_activity=d.last_activity,
            )
            for d in docs
        ]
        return ThreadListResponse(threads=items, count=len(items))

    @app.delete(
        "/threads/{thread_id}",
        status_code=204,
        responses={
            401: {"model": ErrorResponseBody},
            404: {"model": ErrorResponseBody},
        },
    )
    async def delete_thread(
        thread_id: str,
        request: Request,
        authorization: str | None = Header(default=None),
    ) -> Response:
        """Delete the clinician's own thread.

        - 204 No Content on success.
        - 404 ``patient_unavailable`` if the thread does not exist for
          this clinician — identical shape to the "unknown patient" 404
          so an attacker cannot enumerate thread ids belonging to other
          clinicians.
        """
        token = _extract_bearer(authorization)
        ctx = await container.authenticator.authenticate(
            token, route="/threads"
        )
        provider = container.thread_state_provider
        existing = await provider.load(thread_id, ctx.clinician_id)
        if existing is None:
            raise PatientUnavailable(
                f"Thread {thread_id} is not available for this session."
            )
        await provider.delete(thread_id, ctx.clinician_id)
        _logger.info(
            "threads.deleted",
            thread_id=thread_id,
            clinician_id=ctx.clinician_id,
        )
        return Response(status_code=204)

    # ── Slice 5: frontend-facing endpoints ─────────────────────────
    @app.get(
        "/api/me",
        response_model=UserIdentityResponse,
    )
    async def me(
        request: Request,
        authorization: str | None = Header(default=None),
    ) -> UserIdentityResponse:
        """Return the current user's identity.

        In prod behind Container Apps Easy Auth, the CAE injects
        ``X-MS-CLIENT-PRINCIPAL-*`` headers we could read here; for
        Slice 5 we keep parity with the rest of the API and derive
        identity from the bearer token so the smoke server works
        end-to-end.

        Returns ``authenticated=false`` (never raises) when no valid
        token is present — the frontend uses this to gate signed-in
        routes.
        """
        try:
            token = _extract_bearer(authorization)
            ctx = await container.authenticator.authenticate(
                token, route="/api/me"
            )
        except (AuthenticationError, EgpError):
            return UserIdentityResponse(authenticated=False)
        return UserIdentityResponse(
            authenticated=True,
            clinician_id=ctx.clinician_id,
            name=ctx.name if hasattr(ctx, "name") else ctx.clinician_id,
            roles=list(ctx.roles) if hasattr(ctx, "roles") else [],
        )

    @app.get(
        "/threads/{thread_id}",
        response_model=ThreadDetailResponse,
        responses={
            401: {"model": ErrorResponseBody},
            404: {"model": ErrorResponseBody},
        },
    )
    async def get_thread(
        thread_id: str,
        request: Request,
        authorization: str | None = Header(default=None),
    ) -> ThreadDetailResponse:
        """Return the full transcript of one thread.

        Powers B-009 chat-history persistence on refresh. Returns
        HTTP 404 (``patient_unavailable``) for both "thread doesn't
        exist" and "thread belongs to a different clinician" to
        preserve the enumeration defence.
        """
        token = _extract_bearer(authorization)
        ctx = await container.authenticator.authenticate(
            token, route="/threads"
        )
        doc = await container.thread_state_provider.load(
            thread_id, ctx.clinician_id
        )
        if doc is None:
            raise PatientUnavailable(
                f"Thread {thread_id} is not available for this session."
            )
        return ThreadDetailResponse(
            thread_id=doc.thread_id,
            patient_id=doc.patient_id,
            title=doc.title,
            created_at=doc.created_at,
            last_activity=doc.last_activity,
            messages=[
                ThreadMessageView(
                    role=m.role,
                    content=m.content,
                    timestamp=m.timestamp,
                )
                for m in doc.messages
            ],
        )

    # ── Error handlers ─────────────────────────────────────────────
    app.add_exception_handler(EgpError, _egp_error_handler)
    app.add_exception_handler(PydanticValidationError, _validation_error_handler)
    app.add_exception_handler(Exception, _unhandled_error_handler)

    return app


# ── Helpers ────────────────────────────────────────────────────────


async def _enforce_thread_pin(
    *,
    container: Container,
    ctx: ClinicianContext,
    body_thread_id: str,
    body_patient_id: str,
    body_message: str = "",
) -> "SessionDocument | None":
    """Ensure ``body_patient_id`` matches the thread's pinned patient.

    Returns the loaded (or freshly created) :class:`SessionDocument` so the
    caller can rehydrate conversation history and cached specialist state
    without a second Cosmos read.

    Three cases:

    - Thread exists and patient matches → return it.
    - Thread exists and patient differs → raise
      :class:`ThreadPatientMismatch` (409).
    - Thread does not exist yet:

      - Dev / stub-auth mode (``settings.auth_stub_enabled``):
        auto-create the thread with ``body_patient_id``. Preserves the
        smoke-server "just POST /chat" ergonomics.
      - Prod: raise :class:`PatientUnavailable` (404). Client MUST call
        ``POST /threads`` first.
    """
    provider = container.thread_state_provider
    existing = await provider.load(body_thread_id, ctx.clinician_id)

    if existing is not None:
        if existing.patient_id != body_patient_id:
            _logger.warning(
                "chat.thread_patient_mismatch",
                thread_id=body_thread_id,
                thread_patient_id=existing.patient_id,
                body_patient_id=body_patient_id,
                clinician_id=ctx.clinician_id,
            )
            raise ThreadPatientMismatch(
                f"This chat is pinned to a different patient. "
                f"Please start a new chat for patient {body_patient_id}."
            )
        return existing

    # Thread does not exist.
    if container.settings.auth_stub_enabled:
        # Dev-only convenience: auto-create so the smoke server can be
        # driven with a bare POST /chat.
        created = await provider.create_thread(
            clinician_id=ctx.clinician_id,
            tenant_id=ctx.tenant_id,
            patient_id=body_patient_id,
            thread_id=body_thread_id,
            title=_auto_title(body_message),
        )
        _logger.info(
            "chat.thread_auto_created",
            thread_id=body_thread_id,
            clinician_id=ctx.clinician_id,
            patient_id=body_patient_id,
            reason="auth_stub_enabled",
        )
        return created

    _logger.warning(
        "chat.thread_not_found",
        thread_id=body_thread_id,
        clinician_id=ctx.clinician_id,
    )
    raise PatientUnavailable(
        f"Patient {body_patient_id} is not available for this session."
    )


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


def _auto_title(message: str, *, max_len: int = 60) -> str | None:
    """Derive a human-readable thread title from the first user message.

    Returns ``None`` for empty input so the sidebar can render a
    fallback label. Never raises.
    """
    if not message:
        return None
    cleaned = " ".join(message.split())
    if not cleaned:
        return None
    if len(cleaned) <= max_len:
        return cleaned
    return cleaned[: max_len - 1].rstrip() + "\u2026"


def _extract_final_state(run_result: Any) -> ChatWorkflowState:
    """Pull the terminal :class:`ChatWorkflowState` from the run outputs."""
    outputs = run_result.get_outputs()
    for out in outputs:
        if isinstance(out, ChatWorkflowState):
            return out
    raise EgpError("Workflow produced no terminal ChatWorkflowState output")


# Conversation history forwarded into the workflow. The full transcript
# stays in Cosmos and is still returned by ``GET /threads/{id}``; this cap
# only bounds what reaches the router and synthesis prompts, so a long
# thread cannot grow the context window (and the per-turn cost) without
# limit. Turns are user+assistant pairs, so this is ~10 exchanges.
_MAX_HISTORY_MESSAGES = 20


def _history_from(doc: "SessionDocument | None") -> list[SessionMessage]:
    """Return the tail of the persisted transcript for prompt context.

    The current user message is appended by the caller, so it is not
    included here.
    """
    if doc is None or not doc.messages:
        return []
    return list(doc.messages[-_MAX_HISTORY_MESSAGES:])


def _slots_from(doc: "SessionDocument | None") -> dict[str, SpecialistSlot]:
    """Rebuild cached specialist slots from the persisted document.

    Enables the chat router's cache-invalidation contract (ADR-009): it
    can only decide *not* to re-run a specialist if it can see that one
    already produced output on an earlier turn.

    A slot that fails to validate (schema drift from an older thread) is
    dropped rather than failing the turn — the specialist simply re-runs.
    """
    if doc is None or not doc.results:
        return {}
    slots: dict[str, SpecialistSlot] = {}
    for name, payload in doc.results.items():
        if name not in _SPECIALIST_SLOT_NAMES or not isinstance(payload, dict):
            continue
        try:
            slots[name] = SpecialistSlot.model_validate(payload)
        except PydanticValidationError:
            _logger.warning(
                "chat.cached_slot_dropped",
                thread_id=doc.thread_id,
                specialist=name,
            )
    return slots


def _slots_to_results(final: ChatWorkflowState) -> dict[str, Any]:
    """Serialise the turn's specialist slots for persistence."""
    results: dict[str, Any] = {}
    for name in _SPECIALIST_SLOT_NAMES:
        slot = getattr(final, name, None)
        if slot is not None:
            results[name] = slot.model_dump(mode="json")
    return results


_SPECIALIST_SLOT_NAMES: tuple[str, ...] = (
    "prs",
    "genomic_variants",
    "family_history",
    "pgx",
    "phenotype",
)


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


def _refusal_response(
    *,
    body: ChatRequestBody,
    refusal_message: str,
    trace_id: str | None,
) -> ChatResponseBody:
    """Slice 3 — short-circuit response when :class:`ScopeGuard` refuses.

    HTTP 200 (this is a clinician-visible refusal, not a technical
    error). The response body carries the refusal text as the ``reply``
    and leaves every specialist slot empty so the frontend renders it
    as an ordinary assistant message.
    """
    return ChatResponseBody(
        thread_id=body.thread_id,
        patient_id=body.patient_id,
        trace_id=trace_id,
        reply=refusal_message,
        agents_completed=[],
        prs=None,
        genomic_variants=None,
        family_history=None,
        pgx=None,
        phenotype=None,
    )


async def _persist_turn_messages(
    *,
    container: Container,
    ctx: ClinicianContext,
    thread_id: str,
    user_message: str,
    final: ChatWorkflowState,
    doc: "SessionDocument | None" = None,
) -> None:
    """Slice 5 (B-009) — append the turn's user + assistant messages
    to the persisted thread so ``GET /threads/{id}`` returns the full
    transcript on refresh.

    Also persists ``agents_completed`` and the specialist slots, which is
    what makes the cross-turn cache real: the next turn rehydrates them
    via :func:`_slots_from` and the chat router can skip a specialist
    that has already answered.

    Best-effort — a persistence failure MUST NOT change the HTTP
    outcome the caller sees. Logs a warning and returns.
    """
    provider = container.thread_state_provider
    try:
        current = doc if doc is not None else await provider.load(
            thread_id, ctx.clinician_id
        )
        if current is None:
            return
        reply = _reply_from(final)
        updated = current.with_message(
            SessionMessage(role="user", content=user_message)
        )
        if reply:
            updated = updated.with_message(
                SessionMessage(role="assistant", content=reply)
            )
        updated = updated.model_copy(
            update={
                "agents_completed": list(final.agents_completed),
                "results": _slots_to_results(final),
            }
        )
        await provider.save(updated)
    except Exception as exc:  # noqa: BLE001
        # Best-effort by design, but log the cause. A bare warning here
        # hides real persistence faults behind a silently-dropped
        # transcript, which looks like a frontend bug.
        _logger.warning(
            "chat.persist_messages_failed",
            thread_id=thread_id,
            error=f"{type(exc).__name__}: {exc}",
            exc_info=exc,
        )


async def _persist_refusal_messages(
    *,
    container: Container,
    ctx: ClinicianContext,
    thread_id: str,
    user_message: str,
    refusal_reply: str,
    doc: "SessionDocument | None" = None,
) -> None:
    """Slice 5 (B-009) — persist the refusal turn too so the transcript
    is complete on refresh.
    """
    provider = container.thread_state_provider
    try:
        current = doc if doc is not None else await provider.load(
            thread_id, ctx.clinician_id
        )
        if current is None:
            return
        updated = current.with_message(
            SessionMessage(role="user", content=user_message)
        ).with_message(
            SessionMessage(role="assistant", content=refusal_reply)
        )
        await provider.save(updated)
    except Exception as exc:  # noqa: BLE001
        _logger.warning(
            "chat.persist_refusal_failed",
            thread_id=thread_id,
            error=f"{type(exc).__name__}: {exc}",
            exc_info=exc,
        )


# ── Exception handlers ────────────────────────────────────────────


async def _egp_error_handler(request: Request, exc: Exception) -> JSONResponse:
    """Map any :class:`EgpError` to the W09 response envelope."""
    assert isinstance(exc, EgpError)
    trace_id, _ = get_current_trace_and_span_ids()
    envelope = format_error_response(exc, trace_id=trace_id)
    # Log the full chain (including the underlying azure.cosmos / psycopg
    # exception) at INFO/exception level so operators can diagnose real
    # runtime problems. The response body still uses the generic envelope.
    _logger.exception(
        "http.egp_error",
        error_code=envelope.error_code,
        http_status=envelope.http_status,
        trace_id=trace_id,
        exc_info=exc,
    )
    return JSONResponse(
        status_code=envelope.http_status,
        content=envelope.to_dict(),
    )


async def _validation_error_handler(
    request: Request, exc: Exception
) -> JSONResponse:
    """Pydantic validation failure → HTTP 400 with a safe body.

    NOTE: this handler catches *any* ``ValidationError``, not only ones
    raised while parsing the request body — a model validated on the
    response path (e.g. a Cosmos document) lands here too. Log the full
    exception so a server-side schema mismatch is diagnosable instead of
    silently masquerading as a bad client request.
    """
    trace_id, _ = get_current_trace_and_span_ids()
    _logger.exception(
        "http.validation_error",
        path=request.url.path,
        method=request.method,
        trace_id=trace_id,
        exc_info=exc,
    )
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
