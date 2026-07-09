# Runbook: enable parallel specialist dispatch (Design §16.8)

The parallel-dispatch capability is **built into every environment** as
of W04–W06 but held behind two runtime flags
([`orchestration.md`](../config/orchestration.md)) that default to
`sequential`. This runbook is the checklist that must pass before those
flags are flipped to `parallel` in **production**. Preprod may enable
parallel at any time for evaluation.

**Owners:** SA (approves), BE1 (executes), BIX (aware).

## When to enable parallel

Enable when **all** of these are true:

- The customer / product decides the p95 latency budget for broad
  5-specialist queries has been reached under `sequential` (~45 s today,
  Design §4.7).
- Every item on the checklist below passes.
- SA has signed off in the PR that changes the ACA env-var.

## Checklist

Every unchecked item is a hard block on enabling parallel in prod.

### 1. Compass / APIM capacity

- [ ] **RPM budget verified.** Today's peak concurrent clinicians × the
      per-turn LLM-call count under `parallel` fits inside the APIM
      subscription RPM. Under parallel a broad turn spawns 6 LLM calls
      (1 chat router + 1 orch router + 5 specialist ReAct + 5
      specialist extraction = 12) versus 8 under sequential, but they
      arrive within a 1–2 s window instead of 30–40 s.
- [ ] **Rate-limit response tested.** APIM's `rate-limit-by-key`
      policy triggers 429 gracefully; the specialist's failure path
      populates `errors=[...]` on the slot without aborting the
      workflow (Design ADR-007 graceful degradation).

### 2. Postgres capacity

- [ ] **Pool sizing.** `POSTGRES_POOL_MAX_SIZE` × ACA replica count ≤
      Postgres Flex Server `max_connections − 20` (headroom for
      Alembic + admin sessions).
- [ ] **Concurrent read latency.** p95 read latency measured under a
      concurrent load equal to `ORCH_MAX_FANOUT_WIDTH` × peak
      concurrent clinicians. No regression vs sequential mode.

### 3. Provenance & audit

- [ ] **Provenance concurrent-write test passes.** The mode-parity
      harness (`tests/mode_parity/test_mode_parity.py`) is green on
      main — proves the same set of `DBProvenance` records is produced
      under both modes, in an order-independent shape.
- [ ] **Session store concurrent-write.** The Cosmos ETag conditional
      write path (W07) correctly rejects concurrent writes to the
      same `thread_id`; the specialist's failure path retries once.
      (This one lives in W07; do not enable parallel before W07 ships
      the ETag concurrency handling.)

### 4. Chaos test

- [ ] **Kill-one-specialist-mid-fan-out.** Preprod scenario: pause the
      Postgres connection for one specialist while the other four are
      running. Assert:
  - The paused specialist eventually surfaces as `status='failed'`
    with a populated `errors` list.
  - The other four complete and their slots are written.
  - The synthesis pass runs (does not block on the failed slot).
  - The workflow returns a valid final assistant message that
    acknowledges the missing domain.

### 5. Observability

- [ ] **Per-mode dashboards populated.** Latency histograms and cost
      metrics tagged with `orch.mode=parallel` are visible in the W08
      dashboards. (Log events `workflow_runtime.built` and
      `orch_router.dispatched` already carry `orch.mode` — W08 lifts
      them to OTEL span attributes.)
- [ ] **Alert rules active.** An alert fires if
      `RoutingBudgetExceeded` errors exceed 0.5 % of turns over a
      15-minute window.

## The flip itself

1. PR against the prod ACA container definition (`infra/aca/main.bicep`
   or equivalent):

   ```diff
   -   { name: 'ORCH_DISPATCH_MODE', value: 'sequential' }
   -   { name: 'ORCH_MAX_FANOUT_WIDTH', value: '1' }
   +   { name: 'ORCH_DISPATCH_MODE', value: 'parallel' }
   +   { name: 'ORCH_MAX_FANOUT_WIDTH', value: '5' }
   ```

2. PR title must include `[parallel-enable]` and reference this
   runbook. **SA is a required reviewer.**
3. Merge to main triggers CI + preprod deploy; verify preprod mode
   flipped and dashboards populate.
4. Manual approval to prod (already required for the prod deploy
   stage — Design §17.2).
5. Watch alerts + dashboards for 24 h. Rollback = revert the diff
   and redeploy (< 5 min).

## Rollback

Revert the two env vars, redeploy. No code change required; no data
migration required; no session-state migration required (sessions are
opaque JSON in Cosmos).

## Documenting the change

After a successful flip:

- Append a row to the change history in
  [`docs/workstreams/workstream-log.md`](../workstreams/workstream-log.md)
  noting the date, environment, and effective flag values.
- Bump the p95-latency SLO row in [Design §4.7](../solution-design-package.md)
  to the new sequential-vs-parallel reality if measured performance
  differs from the estimates.

*Last updated: 2026-07-10.*
