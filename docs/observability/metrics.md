# Metrics — the 10 KPI instruments

> Delivered by **W08 (Observability)**.
> Applies to code under `epg-maf/src/egp_maf/telemetry/metrics.py`.
> Baseline: Solution Design §20.4, Engineering Plan §E10 (F10.2).

## 1. Contract

Exactly **10 metric instruments**, pinned in
[`METRIC_NAMES`](../../epg-maf/src/egp_maf/telemetry/metrics.py) as a
`frozenset`. A test in `test_metrics.py::TestMetricNames` asserts the
count is 10 and every name is present — CI catches drift.

Labels are strictly enumerated. **`patient_id` is never a metric label**
(Design §20.4 — protects against cardinality explosion and re-identification).

## 2. The ten metrics

| # | Name | Type | Unit | Labels | Purpose |
|---|---|---|---|---|---|
| 1 | `egp.turn.count` | Counter | 1 | `outcome`, `cache_hit` | Every clinician turn. |
| 2 | `egp.turn.duration_ms` | Histogram | ms | `outcome`, `cache_hit` | Wall-clock per turn. |
| 3 | `egp.specialist.duration_ms` | Histogram | ms | `domain`, `status` | Per specialist run. |
| 4 | `egp.specialist.failed` | Counter | 1 | `domain`, `error_class` | Failed specialist runs. |
| 5 | `egp.tool.duration_ms` | Histogram | ms | `tool` | Per tool invocation. |
| 6 | `egp.llm.tokens.prompt` | Counter | 1 | `model` | Cumulative prompt tokens. |
| 7 | `egp.llm.tokens.completion` | Counter | 1 | `model` | Cumulative completion tokens. |
| 8 | `egp.db.pool.utilisation` | UpDownCounter | 1 | (none) | In-use Postgres connections. |
| 9 | `egp.rate_limit.hit` | Counter | 1 | `upstream` | 429s from LLM / Compass. |
| 10 | `egp.prompt.fallback` | Counter | 1 | `prompt_name` | Bundled prompt used because Foundry was unreachable. |

## 3. The `MetricEmitter` protocol

`MetricEmitter` (in
[`metrics.py`](../../epg-maf/src/egp_maf/telemetry/metrics.py)) is a
`@runtime_checkable` Protocol with eight `emit_*` methods:

| Method | Records |
|---|---|
| `emit_turn(outcome, duration_ms, cache_hit)` | 1 + 2 |
| `emit_specialist(domain, status, duration_ms)` | 3 |
| `emit_specialist_failed(domain, error_class)` | 4 |
| `emit_tool(tool, duration_ms)` | 5 |
| `emit_llm_tokens(model, prompt_tokens, completion_tokens)` | 6 + 7 |
| `emit_db_pool_utilisation(in_use, total)` | 8 |
| `emit_rate_limit_hit(upstream)` | 9 |
| `emit_prompt_fallback(prompt_name)` | 10 |

Two implementations:

- :class:`OtelMetricEmitter` — production. Constructor takes an OTEL
  `Meter` and eagerly builds all 10 instruments. Zero I/O on
  construction (the SDK does it lazily).
- :class:`NullMetricEmitter` — default in tests and when OTEL isn't
  configured. Every method is a no-op.

## 4. Wiring

`build_container` (`di/container.py`):

```python
telemetry_provider = build_telemetry_provider(resolved_settings)
metric_emitter = OtelMetricEmitter(
    telemetry_provider.meter_provider.get_meter("egp_maf")
)
container = Container(
    ...,
    telemetry_provider=telemetry_provider,
    metric_emitter=metric_emitter,
)
```

Callers depend on `MetricEmitter` (the protocol), not on
`OtelMetricEmitter` directly. Unit tests inject `NullMetricEmitter`.

## 5. Where each metric is emitted

| Metric | Emitted by (planned wiring) | Status in W08 |
|---|---|---|
| `egp.turn.count` / `egp.turn.duration_ms` | Chat workflow entry / exit | Emitter available; wiring in W11 with FastAPI. |
| `egp.specialist.duration_ms` | :class:`SpecialistExecutor` after span close | Emitter available; span already records duration. |
| `egp.specialist.failed` | :class:`SpecialistExecutor` on caught exception | Emitter available; wired in W09 (isolation). |
| `egp.tool.duration_ms` | `@tool` decorator wrapper | Emitter available; wired in W09 when we thread `metric_emitter` through the shim. |
| `egp.llm.tokens.prompt/completion` | :class:`MafSpecialistLlm` after `AgentRunResponse` returns | Emitter available; wired in W09 (needs token accounting on the response). |
| `egp.db.pool.utilisation` | Postgres pool health check | Emitter available; wired in W11 with the pool health task. |
| `egp.rate_limit.hit` | LLM bridge on `RateLimitError` catch | Emitter available; wired in W09 with the retry policy. |
| `egp.prompt.fallback` | Prompt loader on Foundry-fetch failure | Emitter available; wired in W11. |

The **emitter is complete** in W08. Individual call-sites hook the
emitter into their existing error / success paths in W09 (resilience)
and W11 (cutover / HTTP layer). W08 provides the instrument, not the
call sites.

## 6. KQL cookbook (App Insights)

Once the OTLP exporter is wired in W11, these queries work against the
App Insights `customMetrics` table (Azure Monitor maps OTEL histograms
to the `customMetrics` schema).

### 6.1. Turn throughput per minute

```kql
customMetrics
| where name == "egp.turn.count"
| summarize turns_per_min = sum(value) by bin(timestamp, 1m)
| render timechart
```

### 6.2. Specialist p95 latency by domain

```kql
customMetrics
| where name == "egp.specialist.duration_ms"
| summarize p95 = percentile(value, 95) by
    domain = tostring(customDimensions.domain),
    bin(timestamp, 5m)
| render timechart
```

### 6.3. Specialist failure rate

```kql
customMetrics
| where name == "egp.specialist.failed"
| summarize fails = sum(value) by
    domain = tostring(customDimensions.domain),
    error_class = tostring(customDimensions.error_class),
    bin(timestamp, 5m)
```

### 6.4. Prompt-token spend by model

```kql
customMetrics
| where name == "egp.llm.tokens.prompt"
| summarize tokens = sum(value) by
    model = tostring(customDimensions.model),
    bin(timestamp, 1h)
| order by timestamp desc
```

### 6.5. Rate-limit hits by upstream

```kql
customMetrics
| where name == "egp.rate_limit.hit"
| summarize hits = sum(value) by
    upstream = tostring(customDimensions.upstream),
    bin(timestamp, 5m)
```

### 6.6. Prompt-fallback rate

```kql
customMetrics
| where name == "egp.prompt.fallback"
| summarize fallbacks = sum(value) by bin(timestamp, 1h)
```

## 7. Adding a new metric

Metric names are versioned by intent, not by refactor. Before adding a
new one:

1. Check whether an existing metric can carry a new label.
2. If not, propose the new name + type + labels in an ADR update.
3. Add the name to `METRIC_NAMES` in `metrics.py`.
4. Add the instrument in `OtelMetricEmitter.__init__`.
5. Add the `emit_*` method to both `MetricEmitter` protocol and both
   implementations.
6. Update the test asserting the count is now 11.
7. Update this document.

## 8. See also

- [Spans reference](spans.md)
- Solution Design §20.4 (metric taxonomy)
- Engineering Plan §E10.2 (F10.2 — metric acceptance)
- [`telemetry/metrics.py`](../../epg-maf/src/egp_maf/telemetry/metrics.py)
