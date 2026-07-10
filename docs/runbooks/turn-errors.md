# Runbook — `egp-turn-error-rate-high`

**Sev 1** (page).

## Symptom
Turn error rate > 5% over 5 minutes. Dashboard: **Ops → Typed error codes over time**.

## Diagnosis
Break down by `error.code`:
```kql
customMetrics
| where name == "egp.turn.count"
| summarize errors=sumif(value, tostring(customDimensions.outcome) == "error"), total=sum(value) by bin(timestamp, 5m)
| extend rate=100.0 * errors / total
```
Then jump to the specific runbook for the dominant error code:
`database_unavailable` → [db-unavailable.md](db-unavailable.md),
`cosmos_unavailable` → [cosmos-unavailable.md](cosmos-unavailable.md),
`llm_unavailable` / `rate_limit_exceeded` → [rate-limit.md](rate-limit.md),
`specialist_failed` → [specialist-failures.md](specialist-failures.md).

## Mitigation
Route to the linked runbook.

## Escalation
> 15 min unresolved → P1 incident.
