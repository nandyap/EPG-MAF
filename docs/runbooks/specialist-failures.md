# Runbook — `egp-specialist-failure-spike`

## 1. Alert / trigger

`egp-specialist-failure-spike` — **Sev 2**.

## 2. Symptom

`egp.specialist.failed` > 10/min sustained. Isolation (W09 F11.5)
means clinicians still get partial answers, but the affected domain
is missing from every turn.

Dashboard: **Ops → Specialist failures by domain + error class**.

## 3. Diagnosis

```kql
customMetrics
| where name == "egp.specialist.failed"
| summarize failures=sum(value) by
    domain=tostring(customDimensions.domain),
    error_class=tostring(customDimensions.error_class),
    bin(timestamp, 5m)
| order by timestamp desc
```

By `error_class`:

- `LlmError` / `LlmUnavailable` → LLM upstream; see
  [rate-limit.md](rate-limit.md).
- `DatabaseUnavailable` → see [db-unavailable.md](db-unavailable.md).
- `AccessDenied` → allowlist mismatch; likely deploy race — check
  `docs/security/allowlist.md`.
- Any other typed error → new failure mode; capture a trace and file
  a P2.

## 4. Mitigation

Follow the classified runbook. If the error class isn't in the table
above, capture:

```kql
traces
| where timestamp > ago(15m)
| where customDimensions["specialist.status"] == "failed"
| project timestamp, customDimensions["specialist.name"],
          customDimensions["error.class"], customDimensions["error.code"]
| take 20
```

## 5. Escalation

If the failed specialist is `family_history` and the error class is
anything unusual → **immediately** engage security (PHI-adjacent
domain). Otherwise standard escalation.

## 6. Post-mortem

Standard template.
