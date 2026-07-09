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
