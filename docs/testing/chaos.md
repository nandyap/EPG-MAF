# Chaos scenarios — F12.6

> Delivered by **W10 (Testing, Evaluation & Load)**.
> Runbook + acceptance-criteria table. Scripts land alongside the W11
> preprod deploy so we can inject faults against a real environment.

## 1. Scenarios

Each scenario is a single-page runbook: **trigger**, **expected
behaviour**, **alert / metric fingerprint**, **recovery**.

### 1.1 Kill-replica

- **Trigger:** `az containerapp revision restart -n egp-maf --revision-name <current>`.
- **Expected:** Front Door detects the failed replica within 30 s;
  new requests routed to healthy replicas. In-flight requests fail
  with `LlmUnavailable` / `DatabaseUnavailable` (typed 5xx) — no state
  corruption.
- **Alert fingerprint:** ACA replica-restart Action Group fires.
- **Recovery:** revision auto-restarts; no operator action.

### 1.2 DB pause

- **Trigger:** `az postgres flexible-server stop -g <rg> -n <pg>`.
- **Expected:** Pool connect fails after
  `POSTGRES_CONNECT_MAX_ATTEMPTS` (default 3) with jittered backoff;
  raises :class:`DatabaseUnavailable`. Response formatter maps to
  HTTP 503. Cosmos-side session writes still succeed.
- **Alert:** `database_unavailable` count > 5/min → Action Group.
- **Recovery:** restart the Postgres server; the app's pool re-opens
  on the next request without a restart.

### 1.3 APIM 429 storm

- **Trigger:** Test client fires 100 rps for 60 s past the APIM
  policy cap.
- **Expected:** APIM returns 429 with `Retry-After`; the in-process
  `RetryingSpecialistLlm` retries up to 3× with jittered backoff.
  Sustained 429s surface as `RateLimitExceeded` (HTTP 429) to the
  clinician; `egp.rate_limit.hit` metric climbs.
- **Alert:** `egp.rate_limit.hit` p1 rate > 20/min → PagerDuty.
- **Recovery:** back off or increase APIM quota.

### 1.4 Foundry outage

- **Trigger:** Set `PROMPTS_FOUNDRY_ENDPOINT` to an unreachable host.
- **Expected:** Prompt loader falls back to the bundled prompt on the
  next fetch; `egp.prompt.fallback` counter increments (W11 wires the
  metric emit). Clinician answers unchanged.
- **Alert:** `egp.prompt.fallback` > 0 → warning email (not paging).
- **Recovery:** restore Foundry; the loader picks up the live prompt
  on the next fetch (default TTL 10 min).

### 1.5 Cosmos throttle (429)

- **Trigger:** Force RU shortage on the sessions container.
- **Expected:** Cosmos SDK retries per its own policy; ETag-conflict
  path still functions (F11.4). Final failure raises
  :class:`CosmosUnavailable` (503).
- **Alert:** `cosmos_unavailable` count > 3/min.
- **Recovery:** raise RU/s or restore autoscale.

## 2. Runbook conventions

- Scenarios run **only against preprod**, never production.
- Each run must have a `chaos_run_manifest.json` committed to
  `docs/testing/chaos-history/` with `commit_sha`, `scenario`,
  `duration`, `observed_behaviour`, `alerts_fired`, `deviations`.
- A scenario that fails to match its expected fingerprint opens a
  P1 issue.

## 3. Pytest marker

`@pytest.mark.chaos` — scripts default to skipped; enable with the
`EGP_TEST_CHAOS=1` env var. This runs the scripted trigger *only* —
the observation step reads Azure Monitor and requires a human runbook
holder.

## 4. See also

- Engineering Plan §E12 (F12.6)
- Solution Design §26 (retry/backoff) + §22.5 (runbooks)
- W09 resilience: [`docs/resilience/resilience.md`](../resilience/resilience.md)
