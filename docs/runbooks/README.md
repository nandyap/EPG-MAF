# Runbooks — index

> Delivered by **W11 (Cutover, Release & Runbooks)** — F13.4.
> Every Sev 1 / Sev 2 alert has a linked runbook. Runbooks follow the
> Design §22.5 template: symptom → diagnosis → mitigation → escalation
> → post-mortem.

## Sev 1 (page)

| Alert | Runbook | Symptom |
|---|---|---|
| `egp-turn-error-rate-high` | [turn-errors.md](turn-errors.md) | Turn error rate > 5% over 5 minutes. |
| `egp-db-unavailable` | [db-unavailable.md](db-unavailable.md) | `database_unavailable` count > 5/min. |
| `egp-cosmos-unavailable` | [cosmos-unavailable.md](cosmos-unavailable.md) | `cosmos_unavailable` count > 3/min. |

## Sev 2 (Teams warning; wake-up if unresolved 30 min)

| Alert | Runbook | Symptom |
|---|---|---|
| `egp-turn-p95-latency-high` | [turn-latency.md](turn-latency.md) | Turn p95 > 15 s. |
| `egp-specialist-failure-spike` | [specialist-failures.md](specialist-failures.md) | `egp.specialist.failed` > 10/min. |
| `egp-rate-limit-storm` | [rate-limit.md](rate-limit.md) | `egp.rate_limit.hit` > 20/min. |
| `egp-recursion-budget-exceeded` | [routing-budget.md](routing-budget.md) | `routing_budget_exceeded` > 3/hour. |
| `egp-db-pool-saturation` | [db-pool.md](db-pool.md) | Pool utilisation > 90% for 10 minutes. |

## Sev 3 (email, no page)

| Alert | Runbook | Symptom |
|---|---|---|
| `egp-prompt-fallback-nonzero` | [foundry-outage.md](foundry-outage.md) | `egp.prompt.fallback` > 0 in the last hour. |

## Operational runbooks (non-alert)

| Runbook | Purpose |
|---|---|
| [cutover.md](cutover.md) | Prod cutover + rollback playbook (F13.6). |
| [enable-parallel-dispatch.md](enable-parallel-dispatch.md) | Enable Phase-3 parallel dispatch (W06). |

## Runbook template

Copy `_template.md` when adding a new runbook. Sections:

1. **Alert / trigger** — machine-parseable alert name.
2. **Symptom** — what the on-call sees + dashboard link.
3. **Diagnosis** — KQL queries that classify the failure.
4. **Mitigation** — ordered decision tree with binary decisions.
5. **Escalation** — when and to whom.
6. **Post-mortem** — capture template.

## Quarterly review

Runbooks are reviewed on the first Monday of every quarter by SA + PE
+ QA. A stale runbook (unchanged for 6 months with no matching
incident) is a review candidate.
