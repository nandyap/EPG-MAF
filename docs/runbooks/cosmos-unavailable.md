# Runbook — `egp-cosmos-unavailable`

**Sev 1**. `cosmos_unavailable` > 3/min.

## Diagnosis
- Cosmos account status in Azure Portal.
- RU shortage: `az cosmosdb sql container throughput show`.
- ETag conflict storm: `session.save.etag_conflict` in logs.

## Mitigation
1. If RU shortage → increase RU/s or enable autoscale.
2. If conflict storm → session-append contention; investigate whether
   a client is issuing overlapping turns for the same thread.
3. If account down → wait for Azure recovery; app retries once
   (F11.4) — persistent failures surface as 503.

## Escalation
> 15 min unresolved → P1.
