"""Error → response formatter (F11.1).

Design §25.1 defines the stable client-visible envelope::

    { "error_code": "<stable-code>", "message": "<short-safe-message>",
      "trace_id": "<hex or null>" }

This module is transport-agnostic — the FastAPI middleware in W11 will
call :func:`format_error_response` and wrap the returned dict in an
:class:`http.HTTPException` / JSON response. Keeping the formatter
here means:

- CLI tools, background jobs, and evaluation harnesses can use the same
  envelope shape.
- The mapping between ``EgpError`` subclasses and the response body is
  covered by unit tests in this workstream, not by W11's HTTP tests.

PHI-safety
----------

- The ``message`` field is taken from ``EgpError.args[0]`` when
  available, otherwise from a stable per-class fallback string. Callers
  MUST NOT put PHI in exception messages; the tests assert PHI-adjacent
  attributes (``patient_id``, tool result bodies) never appear here.
- Stack traces are never returned. If a bare :class:`Exception` slips
  through, it is coerced to ``internal_error`` with a fixed message.
"""

from __future__ import annotations

from dataclasses import dataclass

from egp_maf.errors import EgpError


@dataclass(frozen=True)
class ErrorResponse:
    """Stable envelope; serialise via :meth:`to_dict`."""

    error_code: str
    message: str
    trace_id: str | None
    http_status: int

    def to_dict(self) -> dict[str, object]:
        return {
            "error_code": self.error_code,
            "message": self.message,
            "trace_id": self.trace_id,
        }


# Per-class fallback messages for callers that raise with no message.
_FALLBACK_MESSAGES: dict[str, str] = {
    "configuration_error": "Service is misconfigured.",
    "prompt_not_found": "Prompt not found.",
    "database_unavailable": "The clinical database is temporarily unavailable.",
    "cosmos_unavailable": "Session storage is temporarily unavailable.",
    "access_denied": "You are not authorised to access this resource.",
    "schema_evolution_error": "Session document schema is not supported.",
    "concurrency_conflict": "The session was modified concurrently. Retry.",
    "routing_budget_exceeded": "Query too complex; returning partial results.",
    "specialist_failed": "A specialist could not be completed.",
    "upstream_timeout": "Upstream service did not respond in time.",
    "rate_limit_exceeded": "Rate limit exceeded. Retry shortly.",
    "llm_unavailable": "AI model service is temporarily unavailable.",
    "llm_error": "AI model returned an unexpected error.",
    "internal_error": "An internal error occurred.",
    "phi_attribute_forbidden": "An internal error occurred.",
}

# Fallback response when we get an untyped exception.
_INTERNAL_ERROR_CODE = "internal_error"
_INTERNAL_HTTP_STATUS = 500


def format_error_response(
    exc: BaseException,
    *,
    trace_id: str | None = None,
) -> ErrorResponse:
    """Return the client-visible envelope for ``exc``.

    Unknown exceptions are coerced to ``internal_error`` with a fixed
    message — no leakage of unhandled exception state to clients.
    """
    if isinstance(exc, EgpError):
        code = exc.error_code or _INTERNAL_ERROR_CODE
        status = exc.http_status or _INTERNAL_HTTP_STATUS
        raw = _first_arg_message(exc)
        message = raw or _FALLBACK_MESSAGES.get(code, _FALLBACK_MESSAGES[_INTERNAL_ERROR_CODE])
        return ErrorResponse(
            error_code=code,
            message=message,
            trace_id=trace_id,
            http_status=status,
        )

    return ErrorResponse(
        error_code=_INTERNAL_ERROR_CODE,
        message=_FALLBACK_MESSAGES[_INTERNAL_ERROR_CODE],
        trace_id=trace_id,
        http_status=_INTERNAL_HTTP_STATUS,
    )


def _first_arg_message(exc: BaseException) -> str | None:
    """Return the first argument if it is a non-empty string, else None."""
    if not exc.args:
        return None
    first = exc.args[0]
    if isinstance(first, str) and first.strip():
        return first
    return None
