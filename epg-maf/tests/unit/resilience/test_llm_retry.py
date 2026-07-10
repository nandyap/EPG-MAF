"""Tests for :mod:`egp_maf.resilience.llm_retry`."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any

import pytest

from egp_maf.errors import (
    LlmError,
    LlmUnavailable,
    RateLimitExceeded,
    UpstreamTimeout,
)
from egp_maf.resilience.llm_retry import (
    RetryingSpecialistLlm,
    classify_llm_exception,
    default_llm_retry_policy,
)
from egp_maf.telemetry.metrics import NullMetricEmitter

pytestmark = pytest.mark.unit


# ── classify_llm_exception ─────────────────────────────────────────


class _SdkError(RuntimeError):
    def __init__(self, msg: str, status_code: int | None = None) -> None:
        super().__init__(msg)
        self.status_code = status_code


class TestClassifyLlmException:
    def test_timeout_maps_to_upstream_timeout(self) -> None:
        assert isinstance(
            classify_llm_exception(asyncio.TimeoutError()), UpstreamTimeout
        )
        assert isinstance(classify_llm_exception(TimeoutError()), UpstreamTimeout)

    def test_429_maps_to_rate_limit(self) -> None:
        assert isinstance(
            classify_llm_exception(_SdkError("rate limited", status_code=429)),
            RateLimitExceeded,
        )

    def test_5xx_maps_to_llm_unavailable(self) -> None:
        for code in (500, 502, 503, 504):
            typed = classify_llm_exception(_SdkError("boom", status_code=code))
            assert isinstance(typed, LlmUnavailable)

    def test_connection_error_maps_to_llm_unavailable(self) -> None:
        assert isinstance(
            classify_llm_exception(ConnectionError("refused")), LlmUnavailable
        )

    def test_4xx_non_429_maps_to_llm_error(self) -> None:
        typed = classify_llm_exception(_SdkError("bad request", status_code=400))
        assert isinstance(typed, LlmError)

    def test_typed_egp_error_is_passthrough(self) -> None:
        exc = RateLimitExceeded("already typed")
        assert classify_llm_exception(exc) is exc


# ── RetryingSpecialistLlm ──────────────────────────────────────────


@dataclass
class _StubLlm:
    """Minimal SpecialistLlm double that raises N-1 times then returns."""

    outcomes: list[Any] = field(default_factory=list)  # list of exc-or-value
    calls: int = 0

    async def run_react(self, request: Any) -> Any:  # noqa: ARG002
        return self._step()

    async def run_extraction(self, request: Any) -> Any:  # noqa: ARG002
        return self._step()

    def _step(self) -> Any:
        idx = self.calls
        self.calls += 1
        outcome = self.outcomes[idx] if idx < len(self.outcomes) else "ok"
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome


@dataclass
class _RecordingMetrics(NullMetricEmitter):
    rate_limit_hits: list[str] = field(default_factory=list)

    def emit_rate_limit_hit(self, *, upstream: str) -> None:  # type: ignore[override]
        self.rate_limit_hits.append(upstream)


def _fast_policy() -> Any:
    p = default_llm_retry_policy(max_attempts=3, base_delay_ms=0, max_delay_ms=0)
    return p


class TestRetryingSpecialistLlm:
    async def test_returns_on_first_success(self) -> None:
        inner = _StubLlm(outcomes=["ok"])
        metrics = _RecordingMetrics()
        wrapped = RetryingSpecialistLlm(inner, policy=_fast_policy(), metric_emitter=metrics)
        result = await wrapped.run_react(request=None)  # type: ignore[arg-type]
        assert result == "ok"
        assert inner.calls == 1
        assert metrics.rate_limit_hits == []

    async def test_retries_on_transient_then_returns(self) -> None:
        inner = _StubLlm(outcomes=[_SdkError("503", status_code=503), "ok"])
        wrapped = RetryingSpecialistLlm(inner, policy=_fast_policy())
        assert await wrapped.run_react(request=None) == "ok"  # type: ignore[arg-type]
        assert inner.calls == 2

    async def test_emits_rate_limit_metric_per_429(self) -> None:
        inner = _StubLlm(
            outcomes=[
                _SdkError("429", status_code=429),
                _SdkError("429", status_code=429),
                "ok",
            ]
        )
        metrics = _RecordingMetrics()
        wrapped = RetryingSpecialistLlm(
            inner, policy=_fast_policy(), metric_emitter=metrics, upstream_label="llm.test"
        )
        assert await wrapped.run_react(request=None) == "ok"  # type: ignore[arg-type]
        assert metrics.rate_limit_hits == ["llm.test", "llm.test"]

    async def test_terminal_error_raises_typed_llm_error(self) -> None:
        inner = _StubLlm(outcomes=[_SdkError("bad", status_code=400)])
        wrapped = RetryingSpecialistLlm(inner, policy=_fast_policy())
        with pytest.raises(LlmError):
            await wrapped.run_react(request=None)  # type: ignore[arg-type]
        assert inner.calls == 1

    async def test_exhausted_retries_raise_typed_error(self) -> None:
        inner = _StubLlm(
            outcomes=[
                _SdkError("503", status_code=503),
                _SdkError("503", status_code=503),
                _SdkError("503", status_code=503),
            ]
        )
        wrapped = RetryingSpecialistLlm(inner, policy=_fast_policy())
        with pytest.raises(LlmUnavailable):
            await wrapped.run_react(request=None)  # type: ignore[arg-type]
        assert inner.calls == 3

    async def test_run_extraction_shares_the_same_policy(self) -> None:
        inner = _StubLlm(outcomes=[asyncio.TimeoutError(), "ok"])
        wrapped = RetryingSpecialistLlm(inner, policy=_fast_policy())
        assert await wrapped.run_extraction(request=None) == "ok"  # type: ignore[arg-type]
        assert inner.calls == 2
