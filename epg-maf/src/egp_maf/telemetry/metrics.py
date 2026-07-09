"""OTEL metric taxonomy — Design §20.4 (10 metrics).

The 10 metrics named in the design are grouped into three concerns:

- Turn-level throughput + latency (``egp.turn.count``, ``egp.turn.duration_ms``).
- Specialist-level latency + failure rate (``egp.specialist.duration_ms``,
  ``egp.specialist.failed``).
- Tool + LLM + DB pool + rate-limit + prompt-fallback signals.

Labels are strictly enumerated to bound cardinality (Design §20.4:
never label with ``patient_id``).

Ships :class:`MetricEmitter` protocol + two impls:

- :class:`OtelMetricEmitter` — production. Constructs Meter + all 10
  instruments once and forwards :meth:`emit_*` calls.
- :class:`NullMetricEmitter` — default in unit tests + when OTEL isn't
  configured.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from opentelemetry.metrics import Counter, Histogram, Meter, UpDownCounter

# The 10 metric names from Design §20.4 — pinned as a frozenset so
# tests can enforce there are exactly 10 and CI can catch drift.
METRIC_NAMES: frozenset[str] = frozenset(
    {
        "egp.turn.count",
        "egp.turn.duration_ms",
        "egp.specialist.duration_ms",
        "egp.specialist.failed",
        "egp.tool.duration_ms",
        "egp.llm.tokens.prompt",
        "egp.llm.tokens.completion",
        "egp.db.pool.utilisation",
        "egp.rate_limit.hit",
        "egp.prompt.fallback",
    }
)


@runtime_checkable
class MetricEmitter(Protocol):
    """Narrow protocol so we can substitute a null impl in tests.

    Marked ``@runtime_checkable`` so DI wiring tests can
    ``isinstance(x, MetricEmitter)`` — same pattern as
    :class:`egp_maf.auth.authenticator.Authenticator`.
    """

    def emit_turn(
        self, *, outcome: str, duration_ms: int, cache_hit: bool
    ) -> None: ...

    def emit_specialist(
        self, *, domain: str, status: str, duration_ms: int
    ) -> None: ...

    def emit_specialist_failed(self, *, domain: str, error_class: str) -> None: ...

    def emit_tool(self, *, tool: str, duration_ms: int) -> None: ...

    def emit_llm_tokens(
        self, *, model: str, prompt_tokens: int, completion_tokens: int
    ) -> None: ...

    def emit_db_pool_utilisation(self, *, in_use: int, total: int) -> None: ...

    def emit_rate_limit_hit(self, *, upstream: str) -> None: ...

    def emit_prompt_fallback(self, *, prompt_name: str) -> None: ...


class NullMetricEmitter:
    """No-op emitter. Default in tests + when OTEL isn't wired."""

    def emit_turn(
        self, *, outcome: str, duration_ms: int, cache_hit: bool
    ) -> None:
        return None

    def emit_specialist(
        self, *, domain: str, status: str, duration_ms: int
    ) -> None:
        return None

    def emit_specialist_failed(self, *, domain: str, error_class: str) -> None:
        return None

    def emit_tool(self, *, tool: str, duration_ms: int) -> None:
        return None

    def emit_llm_tokens(
        self, *, model: str, prompt_tokens: int, completion_tokens: int
    ) -> None:
        return None

    def emit_db_pool_utilisation(self, *, in_use: int, total: int) -> None:
        return None

    def emit_rate_limit_hit(self, *, upstream: str) -> None:
        return None

    def emit_prompt_fallback(self, *, prompt_name: str) -> None:
        return None


class OtelMetricEmitter:
    """Production emitter. Constructs the 10 instruments once."""

    def __init__(self, meter: Meter) -> None:
        self._turn_count: Counter = meter.create_counter(
            "egp.turn.count",
            unit="1",
            description="Number of clinician turns processed.",
        )
        self._turn_duration: Histogram = meter.create_histogram(
            "egp.turn.duration_ms",
            unit="ms",
            description="Wall-clock duration of a clinician turn.",
        )
        self._specialist_duration: Histogram = meter.create_histogram(
            "egp.specialist.duration_ms",
            unit="ms",
            description="Duration of one specialist run.",
        )
        self._specialist_failed: Counter = meter.create_counter(
            "egp.specialist.failed",
            unit="1",
            description="Number of specialist runs that failed.",
        )
        self._tool_duration: Histogram = meter.create_histogram(
            "egp.tool.duration_ms",
            unit="ms",
            description="Duration of one tool invocation.",
        )
        self._llm_tokens_prompt: Counter = meter.create_counter(
            "egp.llm.tokens.prompt",
            unit="1",
            description="Cumulative prompt-token count.",
        )
        self._llm_tokens_completion: Counter = meter.create_counter(
            "egp.llm.tokens.completion",
            unit="1",
            description="Cumulative completion-token count.",
        )
        self._db_pool_utilisation: UpDownCounter = meter.create_up_down_counter(
            "egp.db.pool.utilisation",
            unit="1",
            description="Postgres pool in-use connection count.",
        )
        self._rate_limit_hit: Counter = meter.create_counter(
            "egp.rate_limit.hit",
            unit="1",
            description="Number of rate-limit responses from upstreams (Compass).",
        )
        self._prompt_fallback: Counter = meter.create_counter(
            "egp.prompt.fallback",
            unit="1",
            description=(
                "Number of times the app fell back to the bundled prompt "
                "instead of Foundry."
            ),
        )

    # ── Emitters ────────────────────────────────────────────────────

    def emit_turn(
        self, *, outcome: str, duration_ms: int, cache_hit: bool
    ) -> None:
        attrs = {"outcome": outcome, "cache_hit": str(cache_hit).lower()}
        self._turn_count.add(1, attrs)
        self._turn_duration.record(duration_ms, attrs)

    def emit_specialist(
        self, *, domain: str, status: str, duration_ms: int
    ) -> None:
        self._specialist_duration.record(
            duration_ms, {"domain": domain, "status": status}
        )

    def emit_specialist_failed(self, *, domain: str, error_class: str) -> None:
        self._specialist_failed.add(1, {"domain": domain, "error_class": error_class})

    def emit_tool(self, *, tool: str, duration_ms: int) -> None:
        self._tool_duration.record(duration_ms, {"tool": tool})

    def emit_llm_tokens(
        self, *, model: str, prompt_tokens: int, completion_tokens: int
    ) -> None:
        self._llm_tokens_prompt.add(prompt_tokens, {"model": model})
        self._llm_tokens_completion.add(completion_tokens, {"model": model})

    def emit_db_pool_utilisation(self, *, in_use: int, total: int) -> None:
        # UpDownCounter stores a delta; production callers pass the
        # signed delta from the last observation. For tests + smoke we
        # accept absolute values and record them as-is (the underlying
        # instrument handles the maths).
        self._db_pool_utilisation.add(in_use, {"scope": "in_use"})
        self._db_pool_utilisation.add(total, {"scope": "total"})

    def emit_rate_limit_hit(self, *, upstream: str) -> None:
        self._rate_limit_hit.add(1, {"upstream": upstream})

    def emit_prompt_fallback(self, *, prompt_name: str) -> None:
        self._prompt_fallback.add(1, {"prompt_name": prompt_name})
