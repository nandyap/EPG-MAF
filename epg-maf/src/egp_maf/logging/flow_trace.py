"""Opt-in end-to-end flow tracing.

Turns on a log line at every hop of a clinical turn: router decisions,
each LLM request and reply, every tool call and its row count, and each
of the ten specialist steps. Off by default; a turn emits ~6 lines
normally and ~60 with tracing on.

Written to answer "where did this content come from?" without guessing —
the 2026-09-10 HG0007 incident, where a specialist reported three
variants for a patient that does not exist, and the existing logs could
not show whether they came from the ReAct pass, the extraction pass or
synthesis.

Two flags, deliberately separate
--------------------------------

``EGP_TRACE_FLOW``
    Structure only: step names, decisions, counts, sizes, durations,
    tool names, row counts. **No clinical content.** Safe to leave on in
    dev and during UAT.

``EGP_TRACE_PAYLOADS``
    The actual prompts and replies. **This logs PHI.** Patient IDs,
    variants, diagnoses and family history all appear in LLM messages,
    and this writes them to the Container Apps log stream in plain text.

    It exists because the fabrication question cannot be answered
    without seeing what the model was shown. Use it for a targeted
    reproduction, read the logs, turn it off. Do not leave it on, do not
    enable it against real patient data, and treat any log export taken
    while it was on as PHI.

    Requires ``EGP_TRACE_FLOW`` as well — you cannot enable payloads
    alone by accident.

The W08 runtime attribute allowlist governs **span** attributes and does
not apply here, so it is not a second line of defence for this module.
That asymmetry is the reason for the flag, the boot warning and the
truncation below.

Correlating one turn
--------------------

``structlog.contextvars.merge_contextvars`` is already first in the
processor chain (``logging/setup.py``), so :func:`bind_turn` stamps every
subsequent line in the same asyncio context with the same ``turn_id``.
No plumbing through call signatures, and interleaved turns stay
separable — which matters, since a turn fans out to five specialists.
"""

from __future__ import annotations

import uuid
from typing import Any

import structlog

from egp_maf.logging import get_logger

_logger = get_logger("egp_maf.flow")

# Resolved once at boot by :func:`configure_flow_trace`. Module-level
# rather than read per call: this is consulted dozens of times per turn
# and ``get_settings()`` is only ``lru_cache``-cheap, not free.
_flow_enabled = False
_payloads_enabled = False

#: Characters of any single payload field written to the log. A ReAct
#: transcript can run to tens of kilobytes; whole ones would bury the
#: structure the trace exists to show, and Container Apps truncates very
#: long lines anyway. Enough to see which patient, which tool and which
#: values appear at the head of the text.
PAYLOAD_PREVIEW_CHARS = 2000


def configure_flow_trace(settings: Any) -> None:
    """Read the flags once, at container build.

    Payload tracing is refused unless flow tracing is also on, so the
    PHI-bearing mode cannot be reached by setting one variable.
    """
    global _flow_enabled, _payloads_enabled

    _flow_enabled = bool(getattr(settings, "trace_flow", False))
    want_payloads = bool(getattr(settings, "trace_payloads", False))

    if want_payloads and not _flow_enabled:
        _payloads_enabled = False
        _logger.warning(
            "flow_trace.payloads_ignored",
            reason="EGP_TRACE_PAYLOADS requires EGP_TRACE_FLOW=true",
        )
    else:
        _payloads_enabled = want_payloads

    if _payloads_enabled:
        # Loud, at boot, every boot. Someone reading the log stream after
        # the fact needs to know these lines contain patient data.
        _logger.warning(
            "flow_trace.payloads_enabled",
            warning=(
                "LLM prompts and replies are being written to logs IN FULL. "
                "These contain PHI. Disable EGP_TRACE_PAYLOADS and treat any "
                "log export taken during this period as PHI."
            ),
            preview_chars=PAYLOAD_PREVIEW_CHARS,
        )
    elif _flow_enabled:
        _logger.info("flow_trace.enabled", payloads=False)


def flow_enabled() -> bool:
    return _flow_enabled


def payloads_enabled() -> bool:
    return _payloads_enabled


def new_turn_id() -> str:
    """Short correlation id. Not a trace id — OTEL is not exported."""
    return uuid.uuid4().hex[:12]


def bind_turn(**fields: Any) -> None:
    """Stamp ``fields`` onto every log line in this asyncio context."""
    structlog.contextvars.bind_contextvars(**fields)


def clear_turn() -> None:
    """Drop the contextvars bound by :func:`bind_turn`.

    Container Apps reuses worker tasks, so leaving them bound risks one
    turn's ``turn_id`` appearing on the next turn's lines — which would
    make the trace actively misleading rather than merely noisy.
    """
    structlog.contextvars.clear_contextvars()


def trace(event: str, **fields: Any) -> None:
    """Structural trace line. No-op unless ``EGP_TRACE_FLOW``.

    Swallows errors raised *while emitting*. It cannot protect against a
    bad field expression, because Python evaluates arguments at the call
    site before this function is entered — during development of this
    module a wrong attribute access in a ``trace(...)`` argument took
    down a whole clinical turn from inside a workflow handler.

    So the real safeguard is the call sites, not this wrapper: keep
    argument expressions trivial (``getattr`` with a default, ``len``,
    ``list``) and never reach into a structure whose shape is assumed
    rather than checked.
    """
    if not _flow_enabled:
        return
    try:
        _logger.info(event, **fields)
    except Exception as exc:  # noqa: BLE001 — see docstring
        _report_emit_failure(event, exc)


def trace_payload(event: str, **fields: Any) -> None:
    """Content-bearing trace line. No-op unless ``EGP_TRACE_PAYLOADS``.

    Every caller must route prompt/reply text through here rather than
    :func:`trace`, so one flag governs all PHI-bearing output. Same
    emit-time guarantee and same call-site caveat as :func:`trace`.
    """
    if not _payloads_enabled:
        return
    try:
        _logger.info(event, **fields)
    except Exception as exc:  # noqa: BLE001 — see :func:`trace`
        _report_emit_failure(event, exc)


def _report_emit_failure(event: str, exc: BaseException) -> None:
    """Last-resort notice that a trace line could not be written.

    Note ``failed_event``, not ``event``: structlog's bound logger takes
    the message as a parameter *named* ``event``, so passing a field of
    that name raises ``TypeError: got multiple values for argument
    'event'``. The first version of this handler did exactly that, so the
    guard clause in :func:`trace` re-raised from inside its own
    ``except`` — turning a swallowed error back into a live one.

    Wrapped in its own ``try`` for the same reason: whatever is wrong
    with the fields may also be wrong here, and a diagnostic that can
    raise is worse than no diagnostic.
    """
    try:
        _logger.warning(
            "flow_trace.emit_failed",
            failed_event=event,
            error=f"{exc.__class__.__name__}: {exc}",
        )
    except Exception:  # noqa: BLE001 — nothing left to fall back to
        pass


def preview(value: Any, limit: int = PAYLOAD_PREVIEW_CHARS) -> str:
    """Truncate for logging, marking the cut so a short value is never
    mistaken for a complete one."""
    if value is None:
        return ""
    text = value if isinstance(value, str) else str(value)
    if len(text) <= limit:
        return text
    return f"{text[:limit]}… [+{len(text) - limit} chars truncated]"


def summarise_messages(messages: Any) -> list[dict[str, Any]]:
    """Per-message ``{role, chars}`` — shape of a prompt without its content.

    Safe under ``EGP_TRACE_FLOW`` alone: reveals how much context each
    turn carried and in what order, which is usually enough to spot a
    transcript that arrived empty.
    """
    out: list[dict[str, Any]] = []
    for m in messages or []:
        if isinstance(m, dict):
            role = str(m.get("role", "?"))
            content = m.get("content", "")
        else:
            role = str(getattr(m, "role", "?"))
            content = getattr(m, "content", None)
            if content is None:
                content = " ".join(
                    getattr(c, "text", "") or ""
                    for c in getattr(m, "contents", None) or []
                )
        out.append({"role": role, "chars": len(str(content))})
    return out
