# Runbook — `egp-rate-limit-storm`

## 1. Alert / trigger

`egp-rate-limit-storm` — **Sev 2** (Teams warning; page if unresolved 30 min).

## 2. Symptom

`egp.rate_limit.hit` > 20/min sustained. Clinicians observe elevated
latency and eventually HTTP 429 responses.

Dashboard: **Ops → Rate-limit hits by upstream**.

## 3. Diagnosis

```kql
customMetrics
| where timestamp > ago(30m)
| where name == "egp.rate_limit.hit"
| summarize hits=sum(value) by upstream=tostring(customDimensions.upstream), bin(timestamp, 1m)
| order by timestamp desc
```

Classify by `upstream` label:

- `llm.prs`, `llm.pgx`, etc. → the LLM quota is the bottleneck.
- `llm` (generic) → per-tenant quota; likely APIM circuit-breaker
  bounce.

## 4. Mitigation

1. **Is APIM circuit-breaker open?** APIM portal → Trace →
   `egp-llm-cb` state.
   - If OPEN → wait for the trip window (30 s per `circuit-breaker.xml`).
     Confirm calls resume after the half-open probe.
2. **Is our quota saturated?** Check the OpenAI / Compass tenant
   quota dashboard.
   - If saturated → raise a P2 ticket with the LLM tenant.
   - If not → step 3.
3. **Is a client hammering /chat?** Security dashboard → Top-N
   clinicians by turn count.
   - If a single clinician_id > 10 turns/min → contact directly; if
     unauthorised → revoke via allowlist (Runbook: `docs/security/allowlist.md`).

## 5. Escalation

If steps 1–3 don't resolve within 30 min → page the LLM SME rota.
If suspected abuse → escalate to SecOps.

## 6. Post-mortem

Capture: which upstream, whether the app-side retry absorbed the
transient, whether we should raise the quota vs. shard traffic.
