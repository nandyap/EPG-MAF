# Spans — taxonomy, attributes, and query cookbook

> Delivered by **W08 (Observability)**.
> Applies to code under `epg-maf/src/egp_maf/telemetry/`.
> Baseline: Solution Design §20 (Observability), Engineering Plan §E10.

## 1. Why we care

Every clinician-visible answer is the product of a workflow request →
one or more specialist runs → one or more tool calls → zero-or-more LLM
calls → many DB queries. When a suggestion looks wrong, we need to jump
from **the suggestion → the exact rows and prompts that produced it**
in one App-Insights query. That's what W08 makes possible.

W08 makes two guarantees:

1. **Deterministic span names + attribute names.** Every span opened by
   `egp_maf` code carries a name from :class:`SpanKind` and attributes
   from `ALLOWED_ATTRIBUTES`. No free-form strings. KQL queries are
   exact-match, not regex-match.
2. **No PHI in span attributes.** `FORBIDDEN_ATTRIBUTES` explicitly
   enumerates the family-history trio, LLM prompt/completion content,
   row bodies and tool results. `safe_set_attribute` refuses those
   keys at runtime.

## 2. The seven span kinds

| Kind | Name | Opened by | Purpose |
|---|---|---|---|
| `WORKFLOW_REQUEST` | `workflow.request` | (owns HTTP entry — W11 wires from FastAPI) | One per clinician turn. Root of the trace tree. |
| `WORKFLOW_EXECUTOR` | `workflow.executor` | (per MAF executor — chat / orchestration) | Child of `workflow.request`. |
| `SPECIALIST` | `specialist.<name>` | :class:`SpecialistExecutor.handle_dispatch` | One per specialist run. Adds `specialist.status` (`completed` / `failed`) and `specialist.duration_ms`. |
| `TOOL_CALL` | `tool.call` | (repository tool shims — W03) | One per `@tool`-decorated function call. Adds `tool.name`, `tool.duration_ms`. |
| `LLM_CALL` | `llm.call` | :class:`MafSpecialistLlm.run_react` / `run_extraction` | One per model round-trip. Adds `llm.model`, `llm.phase` (`react` / `extract`), `llm.duration_ms`. |
| `REPOSITORY` | `repository.<repo>.<method>` | (each repository method — W03) | Optional wrapper around a repository call. Adds `repository.name`, `repository.method`. |
| `DB_QUERY` | `db.query` | :class:`BaseRepository._fetch_all` | One per Postgres query. Adds `db.table`, `db.operation`, `db.row_count`. |

Every kind's context manager:

- Runs the body in a `try/finally` that records `*.duration_ms` via
  `time.perf_counter()` — callers never do arithmetic.
- Records exceptions with `error.class`, `error.message` (truncated to
  200 chars), `error.code` (if the exception is an `EgpError`).
- Sets `Status(ERROR)` on the OTEL span on any raised exception.
- Filters user-supplied kwargs through `filter_safe_attributes` before
  calling `set_attribute` — forbidden attributes never reach the SDK.

## 3. The attribute allowlist

Full list in
[`attributes.py`](../../epg-maf/src/egp_maf/telemetry/attributes.py).
Grouped:

- **Resource:** `service.name`, `service.namespace`, `service.version`,
  `deployment.environment`.
- **Workflow:** `thread_id`, `clinician_id`, `patient_id`, `turn.id`,
  `executor.name`.
- **Specialist:** `specialist.name`, `specialist.status`,
  `specialist.duration_ms`.
- **LLM:** `llm.model`, `llm.phase`, `llm.duration_ms`,
  `llm.structured_output`, `llm.prompt_tokens`, `llm.completion_tokens`.
- **Tool:** `tool.name`, `tool.duration_ms`, `tool.row_count`.
- **Repository:** `repository.name`, `repository.method`.
- **DB:** `db.table`, `db.operation`, `db.row_count`.
- **Error:** `error.class`, `error.message`, `error.code`.

Anything else is either **forbidden** (raises on emit) or **unknown**
(silently dropped so dashboards surface missing columns, not crashes).

## 4. The forbidden set

Named explicitly in
[`attributes.py::FORBIDDEN_ATTRIBUTES`](../../epg-maf/src/egp_maf/telemetry/attributes.py).

- **Family-history trio** (per Design §10.4):
  - `search_context_notes`
  - `affected_relative_count`
  - `total_relatives_searched`
- **LLM content** (per Design §10.4):
  - `prompt_text`
  - `completion_text`
  - `message.content`
  - `messages.content`
- **Row body** (Design §10.4, §20.6):
  - `row.body`
  - `row.content`
  - `source_row`
- **Tool result body:**
  - `tool.result`
  - `tool.output`

Adding a new PHI-leak concern is a two-line change in `attributes.py`
plus a test in `test_attributes.py::TestForbiddenSet`.

## 5. Provenance ↔ trace correlation

`DBProvenance` (Design §20.6) carries two optional fields:

- `trace_id` — 32-hex string of the active OTEL trace, or `None`.
- `span_id` — 16-hex string of the active OTEL span, or `None`.

`ProvenanceService.__init__` takes an
`otel_context_provider: Callable[[], tuple[str|None, str|None]]`. In
production this is `get_current_trace_and_span_ids` (from
`telemetry.otel`); in unit tests that don't wire it we pass a lambda
returning `(None, None)`. The provider is called inside a `try/except`
in `ProvenanceService.build` — a broken OTEL setup can never break
provenance construction.

## 6. KQL cookbook (App Insights)

> Once the OTLP exporter is wired in W11, these queries work directly
> against the App Insights `traces` table.

### 6.1. All spans for one clinician turn

```kql
traces
| where customDimensions.thread_id == "T-1234"
| project timestamp, name, duration, customDimensions
| order by timestamp asc
```

### 6.2. Failed specialists in the last hour

```kql
traces
| where timestamp > ago(1h)
| where name startswith "specialist."
| where customDimensions["specialist.status"] == "failed"
| project timestamp, name,
          specialist_name = customDimensions["specialist.name"],
          error_class     = customDimensions["error.class"],
          error_code      = customDimensions["error.code"]
```

### 6.3. Slow DB queries by table

```kql
traces
| where name == "db.query"
| extend duration_ms = todouble(customDimensions["db.duration_ms"])
| summarize p50 = percentile(duration_ms, 50),
            p95 = percentile(duration_ms, 95),
            n   = count()
  by table = tostring(customDimensions["db.table"])
| order by p95 desc
```

### 6.4. LLM calls by phase and model

```kql
traces
| where name == "llm.call"
| summarize count() by
    model = tostring(customDimensions["llm.model"]),
    phase = tostring(customDimensions["llm.phase"])
```

### 6.5. Jump from a suggestion to the exact rows

The `DBProvenance` on any specialist answer carries `trace_id` and
`span_id`. Given `trace_id = "<hex>"` from the clinician's report:

```kql
traces
| where operation_Id == "<hex>"
| where name in ("db.query", "tool.call")
| project timestamp, name, duration,
          table = customDimensions["db.table"],
          rows  = customDimensions["db.row_count"],
          tool  = customDimensions["tool.name"]
| order by timestamp asc
```

This is the F10.5 acceptance test: the trace tree preserves both the
prompts (via `llm.call` spans) and the rows (via `db.query` spans) that
led to the answer, without the prompt or row content ever leaving the
allowed attribute set.

## 7. Adding a new span

1. Add a new value to `SpanKind` in `spans.py`.
2. Add a context manager next to it that mirrors the existing ones
   (`_apply_attrs` + `_record_exception` + `time.perf_counter` around
   the `yield`).
3. Add each new attribute name to the appropriate group in
   `attributes.py::_*_ATTRIBUTES`.
4. Add a test in `test_spans.py` proving the span name + attributes.
5. Update this document.

## 8. See also

- [Metrics reference](metrics.md)
- Solution Design §20 (Observability)
- Engineering Plan §E10 (F10.1 – F10.5)
- [`telemetry/attributes.py`](../../epg-maf/src/egp_maf/telemetry/attributes.py)
- [`telemetry/spans.py`](../../epg-maf/src/egp_maf/telemetry/spans.py)
