# Runbook — `egp-recursion-budget-exceeded`

**Sev 2**. `routing_budget_exceeded` > 3/hour.

Design ADR-009 caps orchestration at 12 iterations. Breach means the
router looped without producing an `end` decision. W04 returns
partial state.

## Diagnosis
Capture a trace from the breach:
```kql
traces
| where customDimensions["error.code"] == "routing_budget_exceeded"
| project timestamp, customDimensions
| take 20
```

Common causes:
- Router LLM hallucinating; check the `llm.call` spans in the trace.
- Prompt drift after a Foundry prompt update — verify
  `egp.prompt.fallback` isn't spiking too.

## Mitigation
- If prompt drift → roll back the offending prompt via Foundry.
- If model regression → route to previous model version (Foundry
  deployment slot).
- Otherwise → capture 5+ trace examples and file a P2.
