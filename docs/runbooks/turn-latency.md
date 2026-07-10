# Runbook — `egp-turn-p95-latency-high`

**Sev 2**. Turn p95 > 15 s.

## Diagnosis
Break down by span kind:
```kql
customMetrics
| where name in ("egp.turn.duration_ms", "egp.specialist.duration_ms", "egp.llm.duration_ms", "egp.db.duration_ms")
| summarize p95=percentile(value, 95) by name, bin(timestamp, 5m)
```

## Mitigation
- LLM slow → check upstream latency; consider parallel-dispatch enable ([runbook](enable-parallel-dispatch.md)).
- DB slow → check `egp.db.pool.utilisation`; investigate slow query.
- Specialist slow → break down by domain, capture a trace.
