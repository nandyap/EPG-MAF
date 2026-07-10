"""Tests for :mod:`egp_maf.resilience.retry`."""

from __future__ import annotations

import random
from typing import Any

import pytest

from egp_maf.resilience.retry import RetryPolicy, RetryStats, retry_async

pytestmark = pytest.mark.unit


async def _sleep_noop(_delay: float) -> None:
    return None


class _Attempts:
    def __init__(self) -> None:
        self.count = 0
        self.recorded: list[float] = []


class TestRetryPolicyDelay:
    def test_first_attempt_has_no_delay(self) -> None:
        policy = RetryPolicy(base_delay_ms=100, max_delay_ms=1_000, jitter=0.0)
        assert policy.delay_for_attempt(1) == 0.0

    def test_exponential_growth_without_jitter(self) -> None:
        policy = RetryPolicy(base_delay_ms=100, max_delay_ms=10_000, jitter=0.0)
        # attempt=2 → 100ms, attempt=3 → 200ms, attempt=4 → 400ms
        assert policy.delay_for_attempt(2, rand=random.Random(0)) == pytest.approx(0.1)
        assert policy.delay_for_attempt(3, rand=random.Random(0)) == pytest.approx(0.2)
        assert policy.delay_for_attempt(4, rand=random.Random(0)) == pytest.approx(0.4)

    def test_max_delay_caps_growth(self) -> None:
        policy = RetryPolicy(base_delay_ms=1_000, max_delay_ms=1_500, jitter=0.0)
        # attempt=10 would be 512s uncapped
        assert policy.delay_for_attempt(10, rand=random.Random(0)) == pytest.approx(1.5)

    def test_jitter_in_range(self) -> None:
        policy = RetryPolicy(base_delay_ms=100, max_delay_ms=10_000, jitter=0.5)
        # With jitter=0.5 the delay for attempt=2 lies in [50ms, 150ms].
        rng = random.Random(42)
        for _ in range(20):
            d = policy.delay_for_attempt(2, rand=rng)
            assert 0.05 <= d <= 0.15


class TestRetryAsync:
    async def test_returns_on_first_success(self) -> None:
        attempts = _Attempts()

        async def _ok() -> str:
            attempts.count += 1
            return "ok"

        result = await retry_async(
            RetryPolicy(retryable=lambda _: True), _ok, sleeper=_sleep_noop
        )
        assert result == "ok"
        assert attempts.count == 1

    async def test_retries_up_to_max_attempts_then_raises(self) -> None:
        attempts = _Attempts()

        class Boom(RuntimeError):
            pass

        async def _bad() -> Any:
            attempts.count += 1
            raise Boom("nope")

        stats = RetryStats()
        with pytest.raises(Boom):
            await retry_async(
                RetryPolicy(max_attempts=3, retryable=lambda _: True),
                _bad,
                sleeper=_sleep_noop,
                stats=stats,
            )
        assert attempts.count == 3
        assert stats.attempts == 3
        assert isinstance(stats.last_exception, Boom)

    async def test_does_not_retry_when_predicate_returns_false(self) -> None:
        attempts = _Attempts()

        async def _bad() -> Any:
            attempts.count += 1
            raise ValueError("terminal")

        with pytest.raises(ValueError):
            await retry_async(
                RetryPolicy(max_attempts=5, retryable=lambda _: False),
                _bad,
                sleeper=_sleep_noop,
            )
        assert attempts.count == 1

    async def test_retries_transient_then_returns_on_success(self) -> None:
        attempts = _Attempts()

        async def _flaky() -> str:
            attempts.count += 1
            if attempts.count < 3:
                raise ConnectionError("blip")
            return "ok"

        result = await retry_async(
            RetryPolicy(
                max_attempts=3,
                retryable=lambda exc: isinstance(exc, ConnectionError),
            ),
            _flaky,
            sleeper=_sleep_noop,
        )
        assert result == "ok"
        assert attempts.count == 3

    async def test_records_total_delay(self) -> None:
        attempts = _Attempts()

        async def _bad() -> Any:
            attempts.count += 1
            raise RuntimeError("blip")

        recorded: list[float] = []

        async def _sleep(delay: float) -> None:
            recorded.append(delay)

        stats = RetryStats()
        rng = random.Random(0)
        with pytest.raises(RuntimeError):
            await retry_async(
                RetryPolicy(
                    max_attempts=3,
                    base_delay_ms=100,
                    max_delay_ms=1_000,
                    jitter=0.0,
                    retryable=lambda _: True,
                ),
                _bad,
                sleeper=_sleep,
                stats=stats,
                rand=rng,
            )
        # Two sleeps happened (after attempts 1 and 2).
        assert len(recorded) == 2
        assert stats.total_delay_ms >= 100
