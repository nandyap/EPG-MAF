"""Unit tests for :mod:`egp_maf.errors`."""

from __future__ import annotations

from egp_maf.errors import (
    ConcurrencyConflict,
    ConfigurationError,
    CosmosUnavailable,
    DatabaseUnavailable,
    EgpError,
    PromptNotFound,
    SchemaEvolutionError,
)


class TestErrorTaxonomy:
    def test_all_error_classes_have_stable_error_code_and_http_status(self) -> None:
        matrix: dict[type[EgpError], tuple[str, int]] = {
            ConfigurationError: ("configuration_error", 500),
            PromptNotFound: ("prompt_not_found", 500),
            DatabaseUnavailable: ("database_unavailable", 503),
            CosmosUnavailable: ("cosmos_unavailable", 503),
            SchemaEvolutionError: ("schema_evolution_error", 500),
            ConcurrencyConflict: ("concurrency_conflict", 409),
        }
        for cls, (code, status) in matrix.items():
            instance = cls("message")
            assert instance.error_code == code
            assert instance.http_status == status
            assert isinstance(instance, EgpError)
            assert str(instance) == "message"

    def test_error_chain(self) -> None:
        try:
            raise ValueError("inner")
        except ValueError as inner:
            # PEP 3110: `inner` is deleted when the `except` block exits, so
            # assert inside the block (or save a reference beforehand).
            outer = ConfigurationError("outer", cause=inner)
            assert outer.__cause__ is inner
