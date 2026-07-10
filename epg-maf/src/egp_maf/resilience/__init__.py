"""W09 — Resilience & Error Handling.

Public surface:

- :class:`RetryPolicy` — declarative retry knobs (attempts, base delay,
  cap, jitter, retryable predicate).
- :func:`retry_async` — apply a policy to an async callable.
- :class:`RetryingSpecialistLlm` — decorator around any
  :class:`SpecialistLlm` that classifies exceptions into transient
  (retry) vs. terminal (re-raise) and emits ``egp.rate_limit.hit`` for
  every observed 429.
- :func:`classify_llm_exception` — the exception classifier used by the
  LLM retry decorator; also useful in tests.
- :func:`format_error_response` — map an :class:`EgpError` to the stable
  ``{error_code, message, trace_id}`` response body per Design §25.
"""

from __future__ import annotations

from egp_maf.resilience.error_response import (
    ErrorResponse,
    format_error_response,
)
from egp_maf.resilience.llm_retry import (
    RetryingSpecialistLlm,
    classify_llm_exception,
    default_llm_retry_policy,
)
from egp_maf.resilience.retry import (
    RetryPolicy,
    RetryStats,
    retry_async,
)

__all__ = [
    "ErrorResponse",
    "RetryPolicy",
    "RetryStats",
    "RetryingSpecialistLlm",
    "classify_llm_exception",
    "default_llm_retry_policy",
    "format_error_response",
    "retry_async",
]
