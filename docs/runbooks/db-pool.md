# Runbook — `egp-db-pool-saturation`

**Sev 2**. `egp.db.pool.utilisation` > 0.9 for 10 minutes.

## Diagnosis
- Concurrent turns overwhelming the pool.
- A single slow query holding a connection.

Query:
```kql
customMetrics
| where name == "egp.db.duration_ms"
| summarize p95=percentile(value, 95), n=count() by table=tostring(customDimensions.table), bin(timestamp, 5m)
| order by p95 desc
```

## Mitigation
1. Identify the slow table + fix the query (add index, tighten filter).
2. Short-term: raise `POSTGRES_POOL_MAX_SIZE` and restart the ACA revision.
3. Verify statement timeout (30 s) is still terminating runaway queries.
