# Resilience — retry policy, error taxonomy, isolation

> Delivered by **W09 (Resilience & Error Handling)**.
> Applies to code under `epg-maf/src/egp_maf/resilience/`.
> Baseline: Solution Design §25–26 + ADR-022, Engineering Plan §E11.

## 1. Layered defence

We defend against transient failures in **three concentric layers**:

```
Client ──> Front Door ──> APIM ──> ACA (egp-maf app) ──> upstream
                          │                │
                          │                └─ W09 (this doc): typed
                          │                   errors, in-process retry,
                          │                   isolation, budget
                          │
                          └─ F11.2 infra: APIM retry / circuit-breaker
                             policy XML (W11 delivers)
```

- **APIM (F11.2 infra, W11)** — the outer retry layer for LLM calls
  (up to 3× with jitter, per-request 30s timeout, circuit-breaker).
- **App-side (W09, this doc)** — `RetryingSpecialistLlm` around every
  LLM call, DB pool connect retries, Cosmos ETag retry, specialist-
  failure isolation, recursion-budget cap. Runs even when APIM isn't
  in the path (dev mode) or when APIM has exhausted its own retries.
- **Client — no retry expected** from clinicians. Failures surface as
  typed error codes; the UI decides how to render.

## 2. Error taxonomy (F11.1)

Every runtime error is a subclass of :class:`egp_maf.errors.EgpError`
with a stable `error_code` and `http_status`. Response formatter maps
each to the client-visible envelope::

    { "error_code": "<code>", "message": "<safe>", "trace_id": "<hex|null>" }

| Class | `error_code` | HTTP | When |
|---|---|---|---|
| `ConfigurationError` | `configuration_error` | 500 | Missing / invalid config at startup. |
| `PromptNotFound` | `prompt_not_found` | 500 | Prompt name not in bundle. |
| `DatabaseUnavailable` | `database_unavailable` | 503 | Postgres pool cannot service the request. |
| `CosmosUnavailable` | `cosmos_unavailable` | 503 | Cosmos DB call failed non-transiently. |
| `AccessDenied` | `access_denied` | 403 | Allowlist rejected the clinician. |
| `ConcurrencyConflict` | `concurrency_conflict` | 409 | ETag conflict after retry. |
| `SchemaEvolutionError` | `schema_evolution_error` | 500 | Session doc version unsupported. |
| `RoutingBudgetExceeded` | `routing_budget_exceeded` | 500 | Orch loop exceeded 12 iterations. |
| `SpecialistFailed` | `specialist_failed` | 500 | Reserved for a future terminal-fail path. |
| `UpstreamTimeout` | `upstream_timeout` | 504 | LLM / Compass / JWKS timeout. |
| `RateLimitExceeded` | `rate_limit_exceeded` | 429 | LLM / Compass returned 429 after retry exhaustion. |
| `LlmUnavailable` | `llm_unavailable` | 503 | LLM 5xx or connection failure after retries. |
| `LlmError` | `llm_error` | 502 | Non-retryable LLM error (4xx other than 429). |
| `ForbiddenAttributeError` | `phi_attribute_forbidden` | 500 | W08 — attempt to set a forbidden span attribute. |
| Anything else | `internal_error` | 500 | Untyped exception coerced by the formatter. |

The response formatter (:func:`format_error_response`) is transport-
agnostic — the FastAPI middleware in W11 will call it and wrap the
result in an HTTP response. CLI and evaluation harnesses call it too.

**PHI-safety.** Exception messages MUST NOT contain PHI. The formatter
uses the first-`args` string when present, otherwise a per-class
fallback. Stack traces are never surfaced.

## 3. Retry policy (F11.2 app-side)

:class:`RetryPolicy` (in `resilience.retry`) is a frozen dataclass::

    RetryPolicy(
        max_attempts=3,        # includes the first try
        base_delay_ms=250,
        max_delay_ms=4_000,
        jitter=0.5,            # full-jitter multiplier in [1-j, 1+j]
        retryable=lambda exc: <predicate>,
    )

:func:`retry_async(policy, fn, *args, **kwargs)` runs the callable
under the policy. Only exceptions the `retryable` predicate accepts
trigger a retry; every other exception is re-raised immediately.

Backoff formula (per attempt `n`, 1-based, first retry is `n=2`)::

    raw    = min(max_delay_ms, base_delay_ms * 2**(n-2))
    delay  = raw * uniform(1-jitter, 1+jitter) / 1000  # seconds

Callers can pass a :class:`RetryStats` sink to capture attempt count,
total slept ms, and the last exception — useful for span attribute
attachment.

## 4. LLM retry (F11.2 app-side)

:class:`RetryingSpecialistLlm` composes around any
:class:`SpecialistLlm` and adds:

- **Classification.** SDK-native exceptions flow through
  :func:`classify_llm_exception` which probes `status_code` /
  `.response.status_code` / `.status` and maps to typed EgpError:
  429 → `RateLimitExceeded`, 5xx / conn → `LlmUnavailable`, timeout →
  `UpstreamTimeout`, everything else → `LlmError` (terminal).
- **Retry** on `RateLimitExceeded`, `UpstreamTimeout`, and
  `LlmUnavailable` (up to `max_attempts` with jittered backoff).
- **Metric emission.** Every observed 429 emits
  `egp.rate_limit.hit` with `upstream=llm.<name>` label so dashboards
  can distinguish the specialist per-domain.

Wired in `agents/registry.py::build_specialist_registry` — real
`MafSpecialistLlm` instances are wrapped; test-supplied `llm_overrides`
are not (tests want deterministic behaviour).

## 5. DB pool connect retries (F11.3)

`DbPoolFactory.open()` now retries the initial connect
`postgres_connect_max_attempts` (default 3) times with jittered
exponential backoff (`postgres_connect_base_delay_ms`,
`postgres_connect_max_delay_ms`). Final failure raises
:class:`DatabaseUnavailable`.

Every connect attempt is retryable (`retryable=lambda _: True`) —
`AsyncConnectionPool.open` is either "works" or "reject to try again".

**Statement timeouts** are unchanged from W02: server-side
`options=-c statement_timeout=<ms>` is applied per connection at
`_configure_connection` time.

## 6. Cosmos ETag retry (F11.4)

Already delivered in W01 — `ThreadStateProvider.save()` retries the
`replace_item(if_match=<etag>)` call once on
`CosmosAccessConditionFailedError`, reloading the fresh ETag first.
A second conflict raises :class:`ConcurrencyConflict` (HTTP 409).

W09 verifies the contract via `test_error_response.py` (`concurrency_conflict`
maps to 409) and via the existing `tests/integration/test_cosmos.py`.

## 7. Specialist-failure isolation (F11.5)

Design §7.5: one specialist failing must not stop the workflow.

`SpecialistExecutor.handle_dispatch` now catches every exception raised
inside :meth:`SpecialistBase.run` and materialises a failed
:class:`SpecialistSlot`::

    SpecialistSlot(
        status="failed",
        output=None,
        errors=[f"{ErrorClass}: {message}"],
    )

Then it:

1. Emits `MetricEmitter.emit_specialist_failed(domain=..., error_class=...)`.
2. Still emits `MetricEmitter.emit_specialist(domain, status="failed", duration_ms=...)`
   so latency dashboards remain accurate.
3. Marks `agents_completed += [name]` so the orchestration loop moves on.
4. Forwards the state to the fan-in barrier — the other specialists in
   the same dispatch set still run.

Synthesis in W11 will read the failed slot and reflect the gap in the
clinician-visible answer.

## 8. Recursion budget (F11.6)

Already delivered in W04 — `OrchRouterExecutor` guards
`router_iterations` against `settings.orch_iteration_budget` (default
12 = `2 × n_specialists + 2` per ADR-009). Breach raises
:class:`RoutingBudgetExceeded`, which the chat workflow's
`RunOrchestrationExecutor` catches to return partial results rather
than aborting the whole turn.

W09 documents the behaviour here and adds `routing_budget_exceeded` to
the response-formatter table above.

## 9. Configuration surface (all `Settings` fields)

| Field | Default | Env var |
|---|---|---|
| `postgres_connect_max_attempts` | 3 | `POSTGRES_CONNECT_MAX_ATTEMPTS` |
| `postgres_connect_base_delay_ms` | 250 | `POSTGRES_CONNECT_BASE_DELAY_MS` |
| `postgres_connect_max_delay_ms` | 4000 | `POSTGRES_CONNECT_MAX_DELAY_MS` |
| `postgres_statement_timeout_seconds` | 30 | `POSTGRES_STATEMENT_TIMEOUT_SECONDS` (W02) |
| `llm_retry_max_attempts` | 3 | `LLM_RETRY_MAX_ATTEMPTS` |
| `llm_retry_base_delay_ms` | 250 | `LLM_RETRY_BASE_DELAY_MS` |
| `llm_retry_max_delay_ms` | 4000 | `LLM_RETRY_MAX_DELAY_MS` |
| `llm_retry_jitter` | 0.5 | `LLM_RETRY_JITTER` |
| `orch_iteration_budget` | 12 | `ORCH_ITERATION_BUDGET` (W04) |

## 10. See also

- Solution Design §25 (error taxonomy) + §26 (retry / circuit-breaker) + ADR-022
- Engineering Plan §E11 (F11.1 – F11.6)
- [`resilience/retry.py`](../../epg-maf/src/egp_maf/resilience/retry.py)
- [`resilience/llm_retry.py`](../../epg-maf/src/egp_maf/resilience/llm_retry.py)
- [`resilience/error_response.py`](../../epg-maf/src/egp_maf/resilience/error_response.py)
- [W08 metrics](../observability/metrics.md) — the `egp.rate_limit.hit` +
  `egp.specialist.failed` counters that this workstream emits.
