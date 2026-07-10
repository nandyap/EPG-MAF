# Cutover playbook

> **W11 F13.6.** Prod cutover + rollback. Rehearsed in preprod. Every
> decision point is binary.

## 1. Pre-flight (T–24 h)

- [ ] All CI green on `main` — `integration`, `phi-safety`, `unit`.
- [ ] Foundry Evaluations pass rate ≥ 95% (F12.4).
- [ ] Load-test baseline on preprod (F12.5): p95 < 8 s @ 20 concurrent.
- [ ] Chaos scenarios rehearsed on preprod (F12.6): all five graceful.
- [ ] Change ticket approved (landing-zone policy).
- [ ] Runbooks reviewed for the deployed version (F13.4).

## 2. Deploy (T–0)

1. Trigger `.github/workflows/deploy-prod.yml` from a signed tag (`vX.Y.Z`).
2. Approve the `prod` environment gate.
3. Watch the Bicep deployment log until every resource reports
   **Succeeded**.

## 3. Canary (T+5 min)

Traffic split: 5% canary → new revision. Rest of traffic → old
revision. Front Door weighted routing.

- **PASS criteria** (measured over 15 min):
  - Turn error rate ≤ 1%.
  - Turn p95 latency ≤ 8 s.
  - Zero `database_unavailable` / `cosmos_unavailable`.
- If PASS → step 4.
- If FAIL → step 6 (rollback).

## 4. Promote (T+20 min)

1. Shift Front Door weight to 50% canary → 100% canary over 10 min.
2. Confirm all 9 alerts remain silent.
3. Confirm the new revision has picked up the deployed dashboards
   + alert rules.

## 5. Monitor (T+30 min ⇒ T+24 h)

- Ops dashboard panel `Typed error codes over time` — no new codes.
- Security dashboard panel `auth.token_invalid by reason` — no spikes.
- Business dashboard `Turns per 5-minute bin` — matches historical
  baseline.

## 6. Rollback

Every rollback step is idempotent. Run in order.

1. Set Front Door weight to 100% old revision (canary drained).
2. `az containerapp revision deactivate --name egp-maf --revision-name <new>`.
3. If DB migrations were applied and the new revision is deactivated,
   check `alembic history` — Phase-1 migrations are **always
   backwards-compatible with N-1** (Design §11.3), so no schema
   rollback is needed. If a hotfix migration violated this rule (it
   shouldn't have), page the SA on-call.
4. File a P2 incident; post-mortem within 72 h.

## 7. Sign-off

Cutover is considered successful when:

- No Sev 1/2 alert has fired in T+24 h.
- The Foundry Evaluations post-deploy run maintains the pre-deploy
  pass rate ± 1%.
- SA + PE + QA + BIX + PM sign the release notes.
