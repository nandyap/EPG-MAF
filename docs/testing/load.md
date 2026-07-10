# Load tests — F12.5

> Delivered by **W10 (Testing, Evaluation & Load)**.
> Applies to code under `epg-maf/tests/load/` (scaffolded here, wired
> to preprod in W11).

## 1. Baseline + stress scenarios

Per Design §23.7:

| Scenario | Concurrent clinicians | Duration | Pass criteria |
|---|---|---|---|
| **Baseline** | 20 | 15 min sustained | p95 < 8 s, error rate < 1% |
| **Stress** | 100 | 30 min ramp | System degrades gracefully (429s honoured, no state corruption) |
| **Dispatch-mode compare** | 20 | 15 min each mode | `ORCH_DISPATCH_MODE=sequential` vs `parallel` — p95 latency delta captured |

## 2. Tool choice

**Locust** (Python) is the primary. Reasons:

- Test scripts share the same Python codebase; we can import our
  `SessionMessage` types, our auth token minter, and our
  request-builder without a JS bridge.
- Distributed runs from a single test controller.
- Locust exports metrics that align with our OTEL histogram buckets.

`k6` (JS) is the fallback for the APIM-only smoke path (no session
state) — a thin script covers a burn-in check pre-launch.

## 3. Locust scaffold

`tests/load/locustfile.py` (lands in W11 with the cutover PR)
looks like this in outline:

```python
from locust import HttpUser, task, between

class ClinicianUser(HttpUser):
    wait_time = between(1, 3)  # seconds between requests

    def on_start(self) -> None:
        self.token = _mint_test_token(self.environment)

    @task(3)
    def multi_domain_turn(self) -> None:
        self.client.post(
            "/chat",
            headers={"Authorization": f"Bearer {self.token}"},
            json={
                "thread_id": _fresh_thread(),
                "patient_id": "P001",
                "message": "Summarise everything we know about P001.",
            },
        )

    @task(1)
    def single_domain_turn(self) -> None:
        self.client.post(
            "/chat",
            headers={"Authorization": f"Bearer {self.token}"},
            json={
                "thread_id": _fresh_thread(),
                "patient_id": "P001",
                "message": "What PRS does P001 have?",
            },
        )
```

## 4. Result capture

- **Metrics** — Locust exports its own histograms; the OTEL metrics
  from W08 (`egp.turn.duration_ms`, `egp.specialist.duration_ms`) are
  the primary source of truth. Dashboards visualise both.
- **Artefacts** — Every run writes a `run_manifest.json` with
  `commit_sha`, `dispatch_mode`, `concurrent_users`, `duration`,
  `error_rate`, `p95_latency_ms`. Committed to
  `docs/testing/load-history/`.
- **Trigger** — GHA nightly at 02:00 UTC against preprod. Failing
  criteria opens a `perf-regression` issue.

## 5. Constraints

- **APIM sandbox rate limits** — coordinate with PE for a dedicated
  test product (Design §30 R-08).
- **Cost** — LLM tokens dominate. Stress-scenario burn is bounded to
  a monthly cap in the Bicep budget.
- **PHI** — load tests use seeded patients only (`P001…P020`); no
  production data.

## 6. See also

- Solution Design §23.7 (load targets)
- Engineering Plan §E12 (F12.5)
- W08 metrics: [`docs/observability/metrics.md`](../observability/metrics.md)
- [Chaos scenarios](chaos.md)
