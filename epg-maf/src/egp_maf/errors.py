"""Typed exceptions used across the codebase.

Grows per workstream. Every exception maps to a stable ``error_code`` and an
HTTP status once the API layer is added in a later workstream.
"""

from __future__ import annotations


class EgpError(Exception):
    """Base class for all typed EGP errors."""

    error_code: str = "internal_error"
    http_status: int = 500

    def __init__(self, message: str, *, cause: BaseException | None = None) -> None:
        super().__init__(message)
        self.__cause__ = cause


class ConfigurationError(EgpError):
    """Raised when a required configuration value is missing or invalid."""

    error_code = "configuration_error"
    http_status = 500


class PromptNotFound(EgpError):
    """Raised when a caller requests a prompt name not present in the bundle."""

    error_code = "prompt_not_found"
    http_status = 500


class DatabaseUnavailable(EgpError):
    """Raised when the Postgres pool cannot service a request."""

    error_code = "database_unavailable"
    http_status = 503


class CosmosUnavailable(EgpError):
    """Raised when Cosmos DB cannot service a request."""

    error_code = "cosmos_unavailable"
    http_status = 503


class AccessDenied(EgpError):
    """Raised when a clinician is not authorised to access the requested
    resource (typically a patient_id)."""

    error_code = "access_denied"
    http_status = 403


class SchemaEvolutionError(EgpError):
    """Raised when a persisted ``SessionDocument`` has an unsupported schema
    version."""

    error_code = "schema_evolution_error"
    http_status = 500


class ConcurrencyConflict(EgpError):
    """Raised when a Cosmos ETag-conditional write fails and cannot be
    reconciled."""

    error_code = "concurrency_conflict"
    http_status = 409


class RoutingBudgetExceeded(EgpError):
    """Raised when the orchestration router exhausts its iteration budget
    without producing an ``end`` decision. Design ADR-009 caps this at
    ``2 * n_specialists + 2 = 12`` in Phase 1.

    The workflow surfaces this as a graceful degradation — whatever
    specialists have completed are still returned; only the router loop stops.
    """

    error_code = "routing_budget_exceeded"
    http_status = 500


class SpecialistFailed(EgpError):
    """Raised when a specialist sub-executor fails. The orchestration
    sub-workflow catches this and returns a partial result rather than
    aborting the whole run (Design ADR-007).
    """

    error_code = "specialist_failed"
    http_status = 500


# ── W09: Upstream & LLM transients ─────────────────────────────────


class UpstreamTimeout(EgpError):
    """Raised when an upstream (LLM, Compass, JWKS, prompts) call times out.

    A transient class — the retry policy treats this as retryable up to
    the configured attempt cap.
    """

    error_code = "upstream_timeout"
    http_status = 504


class RateLimitExceeded(EgpError):
    """Raised when an upstream returns HTTP 429.

    The LLM-retry policy retries on this with jittered backoff; final
    failure surfaces as HTTP 429 to the caller so APIM / Front Door can
    apply their own retry-after logic.
    """

    error_code = "rate_limit_exceeded"
    http_status = 429


class LlmUnavailable(EgpError):
    """Raised when the LLM upstream cannot service a request (5xx after
    retry exhaustion, connection refused, DNS failure)."""

    error_code = "llm_unavailable"
    http_status = 503


class LlmError(EgpError):
    """Raised for terminal LLM errors that are NOT retryable (4xx other
    than 429, malformed responses, schema-validation failures).

    Distinct from :class:`LlmUnavailable` so retry policies can classify
    correctly (this one is *not* retryable)."""

    error_code = "llm_error"
    http_status = 502
