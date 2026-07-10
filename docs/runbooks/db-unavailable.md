# Runbook — `egp-db-unavailable`

## 1. Alert / trigger

`egp-db-unavailable` — **Sev 1** (page).

## 2. Symptom

`database_unavailable` count > 5/min sustained for 5 minutes.
Clinicians see HTTP 503 responses with
`{"error_code": "database_unavailable"}`.

Dashboard: **Ops → Typed error codes over time**.

## 3. Diagnosis

```kql
traces
| where timestamp > ago(15m)
| where customDimensions["error.code"] == "database_unavailable"
| project timestamp, message, customDimensions
| order by timestamp desc
```

Then classify:

| Cause | Signal |
|---|---|
| Postgres restart / failover | `db.pool.open_failed` in app logs; Azure activity log shows a maintenance event. |
| Pool exhaustion | `egp.db.pool.utilisation` = 1.0 on the Ops dashboard. |
| Network partition | `ConnectionError` in the retry logs; ACA replicas cannot reach Postgres subnet. |
| Managed-identity token failure | `azure.identity` errors in the pool `_acquire_token` path. |

## 4. Mitigation

1. **Is Postgres up?** Azure Portal → Postgres flexible server → status.
   - If DOWN → step 2.
   - If UP → step 3.
2. Restart the server (`az postgres flexible-server restart`). Wait 2 min. Verify the app's pool re-opens on next request (no app restart required — W09 retries connect).
3. **Is the pool saturated?** `egp.db.pool.utilisation` panel.
   - If YES → scale `postgres_pool_max_size` via ACA env var; restart ACA revision. Consider raising Postgres tier.
   - If NO → step 4.
4. **Network?** Check ACA subnet → Postgres private endpoint route. If broken → escalate to platform team.

## 5. Escalation

If mitigation step 4 fails → page platform on-call (Azure networking).
If unresolved > 30 min → declare P1 incident.

## 6. Post-mortem

Standard template. Capture: RTO, RPO, whether the app's retry policy
absorbed the transient (it should have for connect-retry-window
failures).
