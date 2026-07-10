"""LLM-call retry decorator.

Composes around any :class:`SpecialistLlm` (Protocol) to add:

- Backoff + jitter on 429 (:class:`RateLimitExceeded`) and 5xx
  (:class:`LlmUnavailable`) and timeouts (:class:`UpstreamTimeout`).
- Structured error classification: SDK exceptions from OpenAI / Compass
  / MAF flow through :func:`classify_llm_exception` so callers always
  see the typed :mod:`egp_maf.errors` variants.
- Metric emission: every observed 429 emits ``egp.rate_limit.hit`` via
  the injected :class:`MetricEmitter`.

Design notes
------------

The decorator is a *composition*, not a subclass — that keeps
:class:`MafSpecialistLlm` a pure MAF adapter (Design ADR-018 keeps the
seams narrow). Tests inject a :class:`StubSpecialistLlm` that raises
whatever the scenario needs; the decorator classifies + retries.

Only :class:`MafSpecialistLlm.run_react` and ``run_extraction`` are
wrapped. Tool calls run inside the underlying agent loop and are the
agent framework's concern — we do not retry individual tool calls
here (F10.2 owns tool spans; retry is not appropriate for our
DB-read tool shims which either succeed or fail terminally).
"""

from __future__ import annotations

import asyncio
from typing import Any

from egp_maf.agents.base import (
    SpecialistExtractionRequest,
    SpecialistLlm,
    SpecialistReactRequest,
    SpecialistReactResult,
)
from egp_maf.errors import (
    EgpError,
    LlmError,
    LlmUnavailable,
    RateLimitExceeded,
    UpstreamTimeout,
)
from egp_maf.resilience.retry import RetryPolicy, retry_async
from egp_maf.telemetry.metrics import MetricEmitter, NullMetricEmitter


# ── Exception classification ────────────────────────────────────────


_TRANSIENT_STATUS_CODES = frozenset({408, 425, 429, 500, 502, 503, 504})


def _status_code_of(exc: BaseException) -> int | None:
    """Best-effort probe for an HTTP status code on an SDK exception.

    OpenAI Python SDK exposes ``status_code``; other stacks use
    ``response.status_code`` or ``.status``. We try each politely.
    """
    for attr in ("status_code", "status"):
        value = getattr(exc, attr, None)
        if isinstance(value, int):
            return value
    response = getattr(exc, "response", None)
    if response is not None:
        value = getattr(response, "status_code", None)
        if isinstance(value, int):
            return value
    return None


def classify_llm_exception(exc: BaseException) -> EgpError:
    """Return the typed :class:`EgpError` variant for ``exc``.

    - Already-typed :class:`EgpError` → returned unchanged.
    - ``asyncio.TimeoutError`` / ``TimeoutError`` → :class:`UpstreamTimeout`.
    - HTTP 429 (from status_code probe) → :class:`RateLimitExceeded`.
    - HTTP 5xx or connection errors → :class:`LlmUnavailable`.
    - Anything else → :class:`LlmError` (terminal).

    We deliberately never touch the SDK's typed exception classes by
    name — probing attributes keeps the module free of a hard SDK
    dependency and lets us support OpenAI + Compass + Foundry-relay
    behind the same shim.
    """
    if isinstance(exc, EgpError):
        return exc
    if isinstance(exc, (asyncio.TimeoutError, TimeoutError)):
        return UpstreamTimeout("LLM upstream timeout", cause=exc)

    status = _status_code_of(exc)
    if status == 429:
        return RateLimitExceeded("LLM upstream rate-limited", cause=exc)
    if status is not None and 500 <= status < 600:
        return LlmUnavailable(f"LLM upstream error (HTTP {status})", cause=exc)

    # Connection-family errors surface as ConnectionError / OSError.
    if isinstance(exc, (ConnectionError, OSError)):
        return LlmUnavailable("LLM upstream connection failed", cause=exc)

    return LlmError(f"LLM upstream error: {type(exc).__name__}", cause=exc)


def _is_retryable(exc: BaseException) -> bool:
    """Retryable when classification yields a transient EgpError."""
    typed = classify_llm_exception(exc)
    return isinstance(typed, (RateLimitExceeded, UpstreamTimeout, LlmUnavailable))


def default_llm_retry_policy(
    *,
    max_attempts: int = 3,
    base_delay_ms: int = 250,
    max_delay_ms: int = 4_000,
    jitter: float = 0.5,
) -> RetryPolicy:
    """Return the retry policy applied around every LLM call by default.

    Aligned with Design §26 / ADR-022: retry up to 3 attempts with
    jittered exponential backoff. The APIM policy XML (F11.2 infra) is
    the outer layer; this is the in-process layer for callers that hit
    the LLM directly (dev mode) or when APIM has already exhausted.
    """
    return RetryPolicy(
        max_attempts=max_attempts,
        base_delay_ms=base_delay_ms,
        max_delay_ms=max_delay_ms,
        jitter=jitter,
        retryable=_is_retryable,
    )


# ── The composition ────────────────────────────────────────────────


class RetryingSpecialistLlm:
    """Wraps a :class:`SpecialistLlm` with retry + metric emission."""

    def __init__(
        self,
        inner: SpecialistLlm,
        *,
        policy: RetryPolicy | None = None,
        metric_emitter: MetricEmitter | None = None,
        upstream_label: str = "llm",
    ) -> None:
        self._inner = inner
        self._policy = policy or default_llm_retry_policy()
        self._metrics: MetricEmitter = metric_emitter or NullMetricEmitter()
        self._upstream = upstream_label

    async def run_react(
        self, request: SpecialistReactRequest
    ) -> SpecialistReactResult:
        return await self._retry(self._inner.run_react, request)

    async def run_extraction(
        self, request: SpecialistExtractionRequest[Any]
    ) -> Any:
        return await self._retry(self._inner.run_extraction, request)

    async def _retry(self, fn: Any, request: Any) -> Any:
        try:
            return await retry_async(self._policy, self._observed(fn), request)
        except BaseException as exc:
            typed = classify_llm_exception(exc)
            if isinstance(typed, EgpError) and typed is not exc:
                raise typed from exc
            raise

    def _observed(self, fn: Any) -> Any:
        """Wrap ``fn`` so every observed 429 emits a rate-limit metric.

        We increment BEFORE re-raising so retry accounting captures the
        pre-retry hit (F11.2 acceptance: 429 count matches actual
        rate-limited attempts, not just terminal failures).
        """

        async def _observe(request: Any) -> Any:
            try:
                return await fn(request)
            except BaseException as exc:
                typed = classify_llm_exception(exc)
                if isinstance(typed, RateLimitExceeded):
                    self._metrics.emit_rate_limit_hit(upstream=self._upstream)
                raise

        return _observe
