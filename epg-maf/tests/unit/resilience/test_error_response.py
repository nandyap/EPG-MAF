"""Tests for :mod:`egp_maf.resilience.error_response`."""

from __future__ import annotations

import pytest

from egp_maf.errors import (
    AccessDenied,
    ConcurrencyConflict,
    ConfigurationError,
    DatabaseUnavailable,
    LlmError,
    LlmUnavailable,
    RateLimitExceeded,
    RoutingBudgetExceeded,
    SpecialistFailed,
    UpstreamTimeout,
)
from egp_maf.resilience.error_response import format_error_response

pytestmark = pytest.mark.unit


class TestFormatErrorResponse:
    def test_untyped_exception_coerced_to_internal_error(self) -> None:
        resp = format_error_response(RuntimeError("something raw"), trace_id="abc")
        assert resp.error_code == "internal_error"
        assert resp.http_status == 500
        assert resp.trace_id == "abc"
        # No leakage of the raw message.
        assert "something raw" not in resp.message

    @pytest.mark.parametrize(
        "exc_cls,expected_code,expected_status",
        [
            (AccessDenied, "access_denied", 403),
            (DatabaseUnavailable, "database_unavailable", 503),
            (ConcurrencyConflict, "concurrency_conflict", 409),
            (RoutingBudgetExceeded, "routing_budget_exceeded", 500),
            (SpecialistFailed, "specialist_failed", 500),
            (UpstreamTimeout, "upstream_timeout", 504),
            (RateLimitExceeded, "rate_limit_exceeded", 429),
            (LlmUnavailable, "llm_unavailable", 503),
            (LlmError, "llm_error", 502),
            (ConfigurationError, "configuration_error", 500),
        ],
    )
    def test_typed_exception_carries_stable_code_and_status(
        self,
        exc_cls: type,
        expected_code: str,
        expected_status: int,
    ) -> None:
        resp = format_error_response(exc_cls("boom"), trace_id="t")
        assert resp.error_code == expected_code
        assert resp.http_status == expected_status
        # First-arg message is surfaced when set.
        assert resp.message == "boom"

    def test_empty_message_falls_back_to_class_default(self) -> None:
        resp = format_error_response(AccessDenied(""), trace_id=None)
        # Fallback message is not empty and does not include "boom".
        assert resp.message
        assert resp.error_code == "access_denied"

    def test_to_dict_produces_stable_shape(self) -> None:
        resp = format_error_response(AccessDenied("nope"), trace_id="t-1")
        d = resp.to_dict()
        assert set(d.keys()) == {"error_code", "message", "trace_id"}
        # http_status is intentionally NOT in the body — it goes on the response.
        assert "http_status" not in d
        assert d["trace_id"] == "t-1"

    def test_trace_id_defaults_to_none(self) -> None:
        resp = format_error_response(AccessDenied("nope"))
        assert resp.trace_id is None
