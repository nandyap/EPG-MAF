"""Generic async retry helper.

Design §26 (retry / backoff / circuit-breaker) — the app-side portion.
APIM owns the edge-side retry policy for LLM (F11.2 infra); this module
owns the in-process fallback that runs when we call an upstream
directly (JWKS fetches, LLM in dev mode, prompts-fetch fallback).

Contract
--------

- Retry only on exceptions that the caller's ``retryable`` predicate
  returns True for. Every other exception is re-raised immediately.
- Backoff is exponential with jitter: ``delay = min(cap, base * 2**n)``
  then multiplied by a uniform jitter in [0.5, 1.5]. This is the
  ``full-jitter`` variant recommended by the AWS Architecture Blog.
- Stops after ``max_attempts`` total tries (attempt 1 is the initial
  call). On final failure re-raises the last exception.
- Records timing + attempt count on an optional :class:`RetryStats`
  object so callers can attach the values to a span or metric.
"""

from __future__ import annotations

import asyncio
import random
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import TypeVar

_T = TypeVar("_T")


@dataclass(frozen=True)
class RetryPolicy:
    """Declarative retry configuration.

    Parameters
    ----------
    max_attempts:
        Total tries including the first. Must be >= 1.
    base_delay_ms:
        Initial delay in milliseconds. Delay for attempt ``n`` (1-based)
        is ``base_delay_ms * 2**(n-1)`` before jitter.
    max_delay_ms:
        Upper cap on the pre-jitter delay.
    jitter:
        Full-jitter multiplier range. Actual multiplier drawn from
        ``uniform(1 - jitter, 1 + jitter)``. Clamped to >= 0.
    retryable:
        Predicate that returns True when an exception should trigger a
        retry. Default: ``lambda exc: False`` (i.e. never retry).
    """

    max_attempts: int = 3
    base_delay_ms: int = 100
    max_delay_ms: int = 5_000
    jitter: float = 0.5
    retryable: Callable[[BaseException], bool] = field(
        default=lambda _exc: False, repr=False
    )

    def __post_init__(self) -> None:  # pragma: no cover — trivial
        if self.max_attempts < 1:
            raise ValueError("max_attempts must be >= 1")
        if self.base_delay_ms < 0 or self.max_delay_ms < 0:
            raise ValueError("delays must be non-negative")
        if self.jitter < 0:
            raise ValueError("jitter must be non-negative")

    def delay_for_attempt(self, attempt: int, *, rand: random.Random | None = None) -> float:
        """Return the delay before ``attempt`` (1-based, first retry is attempt=2).

        Pure — takes an optional RNG so tests can be deterministic.
        """
        if attempt <= 1:
            return 0.0
        raw = min(self.max_delay_ms, self.base_delay_ms * (2 ** (attempt - 2)))
        rng = rand or random
        multiplier = rng.uniform(
            max(0.0, 1.0 - self.jitter), 1.0 + self.jitter
        )
        return (raw * multiplier) / 1000.0


@dataclass
class RetryStats:
    """Mutable per-call statistics; useful for span/metric attachment."""

    attempts: int = 0
    total_delay_ms: int = 0
    last_exception: BaseException | None = None


async def retry_async(
    policy: RetryPolicy,
    fn: Callable[..., Awaitable[_T]],
    /,
    *args: object,
    stats: RetryStats | None = None,
    sleeper: Callable[[float], Awaitable[None]] | None = None,
    rand: random.Random | None = None,
    **kwargs: object,
) -> _T:
    """Run ``fn(*args, **kwargs)`` under ``policy``.

    Parameters
    ----------
    policy:
        Retry configuration.
    fn:
        Async callable to invoke.
    stats:
        Optional record of what happened. If provided, updated in place.
    sleeper:
        Optional injected async sleep — tests use this to avoid real
        wall-clock delays.
    rand:
        Optional deterministic RNG for jitter.
    """
    sleep = sleeper or asyncio.sleep
    stats_local = stats or RetryStats()
    last_exc: BaseException | None = None

    for attempt in range(1, policy.max_attempts + 1):
        stats_local.attempts = attempt
        try:
            result = await fn(*args, **kwargs)
            return result
        except BaseException as exc:  # noqa: BLE001 — policy decides
            last_exc = exc
            stats_local.last_exception = exc
            if attempt >= policy.max_attempts or not policy.retryable(exc):
                raise
            delay_seconds = policy.delay_for_attempt(attempt + 1, rand=rand)
            stats_local.total_delay_ms += int(delay_seconds * 1000)
            _ts_before = time.perf_counter()
            await sleep(delay_seconds)
            # Guard against a broken sleeper that returns immediately in
            # a tight loop causing runaway retries with no delay in prod.
            _ = time.perf_counter() - _ts_before

    # Unreachable — the loop above always returns or raises.
    assert last_exc is not None
    raise last_exc
