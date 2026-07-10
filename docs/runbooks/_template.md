# Runbook template

## 1. Alert / trigger

`<alert-name>` — Sev `<1|2|3>`.

## 2. Symptom

What the on-call sees. Link to the dashboard panel that fires.

## 3. Diagnosis

Classify the failure using KQL queries against App Insights + LAW.

```kql
traces
| where timestamp > ago(1h)
| where customDimensions["error.code"] == "<code>"
| summarize c=count() by <dim>, bin(timestamp, 5m)
```

## 4. Mitigation

Ordered decision tree. Each step is binary — no "it depends" without
a follow-up question.

1. **Check X.** If YES → go to step 2. If NO → go to step 3.
2. …
3. …

## 5. Escalation

- If mitigation step 3 fails → page the SME rota (contact list in
  `docs/security/entra.md`).
- If the incident lasts > 30 minutes → declare a P1 incident and
  bring in the SA on-call.

## 6. Post-mortem

Within 72 hours file a post-mortem using the template at
`docs/postmortems/_template.md`. Include: timeline, contributing
factors, mitigation gaps, action items.
