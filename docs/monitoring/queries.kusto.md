-- W11 F13.2 — Reusable KQL queries.
-- Copy/paste into App Insights or Log Analytics.

-- ─────────────────────────────────────────────────────────────
-- Turn throughput (last hour, 1-minute bins)
customMetrics
| where name == "egp.turn.count"
| summarize turns=sum(value) by bin(timestamp, 1m)
| render timechart

-- ─────────────────────────────────────────────────────────────
-- Turn latency p50/p95/p99 (last hour)
customMetrics
| where name == "egp.turn.duration_ms"
| summarize p50=percentile(value, 50), p95=percentile(value, 95), p99=percentile(value, 99) by bin(timestamp, 5m)
| render timechart

-- ─────────────────────────────────────────────────────────────
-- Specialist p95 latency by domain
customMetrics
| where name == "egp.specialist.duration_ms"
| summarize p95=percentile(value, 95) by domain=tostring(customDimensions.domain), bin(timestamp, 5m)
| render timechart

-- ─────────────────────────────────────────────────────────────
-- Failed specialists (F11.5 + F10.3)
customMetrics
| where name == "egp.specialist.failed"
| summarize c=sum(value) by
    domain=tostring(customDimensions.domain),
    error_class=tostring(customDimensions.error_class),
    bin(timestamp, 5m)

-- ─────────────────────────────────────────────────────────────
-- LLM prompt-token spend (last 24h, per model)
customMetrics
| where timestamp > ago(24h)
| where name == "egp.llm.tokens.prompt"
| summarize tokens=sum(value) by model=tostring(customDimensions.model), bin(timestamp, 1h)
| order by timestamp desc

-- ─────────────────────────────────────────────────────────────
-- Typed error codes over time (W09 error_code labels)
traces
| where isnotempty(customDimensions["error.code"])
| summarize c=count() by error_code=tostring(customDimensions["error.code"]), bin(timestamp, 15m)
| render timechart

-- ─────────────────────────────────────────────────────────────
-- Trace lookup by trace_id (from a clinician-visible error report)
traces
| where operation_Id == "<HEX_TRACE_ID>"
| order by timestamp asc
| project timestamp, name, duration, customDimensions

-- ─────────────────────────────────────────────────────────────
-- Postgres pool utilisation
customMetrics
| where name == "egp.db.pool.utilisation"
| summarize avg_util=avg(value), max_util=max(value) by bin(timestamp, 5m)
| render timechart

-- ─────────────────────────────────────────────────────────────
-- Audit events (W07)
AppEvents
| where Name in ("authz.granted", "authz.denied", "auth.token_invalid", "auth.role_denied")
| project TimeGenerated, Name, Properties.clinician_id, Properties.route, Properties.reason
| order by TimeGenerated desc

-- ─────────────────────────────────────────────────────────────
-- Top-N clinicians by turn volume (rate-anomaly candidate)
customMetrics
| where name == "egp.turn.count"
| summarize turns=sum(value) by clinician=tostring(customDimensions.clinician_id)
| top 20 by turns
