# EGP Window — Friday Demo Brief

**Audience:** M42 (customer) — technical + architectural
**Duration:** 30–45 min
**Presenter:** Vijay
**Date:** Friday 2026-07-17
**Repo:** https://github.com/nandyap/EPG-MAF
**Tag under demo:** `w11-cutover` (commit `ee6204d`)

---

## 0. Elevator pitch (30 sec)

We have ported the customer's LangGraph clinical-genomics prototype to **Microsoft Agent
Framework (MAF)** on Azure. **All 11 workstreams are complete** (421 unit tests
passing), the HTTP surface is browsable locally via Swagger UI today, and the
system is ready for a Compass key + Azure subscription to move from stub to
live. Six open questions await customer answers — captured in
[`epg-maf/docs/blockers.md`](../../epg-maf/docs/blockers.md).

---

## 1. Agenda

| # | Time | Section | Slide artefact / repo reference |
|---|------|---------|---------------------------------|
| 1 | 5 min | The problem & why MAF | [`docs/solution-design-package.md`](../solution-design-package.md) §1 |
| 2 | 5 min | Architecture overview | Diagram §3 below |
| 3 | 10 min | Live demo (Swagger UI) | [`epg-maf/scripts/serve_smoke.py`](../../epg-maf/scripts/serve_smoke.py) |
| 4 | 10 min | MAF components we use & why | §4 below + ADR pointers |
| 5 | 5 min | Parallel vs. sequential dispatch toggle | §5 below + [`orch_router.py`](../../epg-maf/src/egp_maf/workflow/orchestration/orch_router.py) |
| 6 | 5 min | What's shipped vs. what's blocked | [`docs/releases/v1.0.0.md`](../releases/v1.0.0.md) + `blockers.md` |
| 7 | 5 min | What we need from M42 (Q&A) | `blockers.md` |

---

## 2. The problem (5 min)

**Clinical genomics decision-support agent.** A clinician (or patient) asks a
natural-language question about a single patient's genomic + clinical data. The
agent must:

1. Route the question to the right **specialist(s)**: PRS, Genomic Variants,
   Family History, Pharmacogenomics (PGx), Phenotype.
2. Call the relevant **tools** against a curated clinical database
   (Postgres in prod, DuckDB seed for tests).
3. Synthesise a **clinically defensible answer** with structured provenance.
4. Enforce **strict single-patient scope + PHI redaction + auditable trail**.

**Prototype today:** LangGraph, single-process, no auth, no observability
budget, no resilience/retry, no clinical audit sink, no production topology.

**What we built:** the same workflow reimplemented on **Microsoft Agent
Framework** with Azure-native infrastructure, defence-in-depth, and full
enterprise observability — ready to drop into the customer's landing zone.

---

## 3. Architecture overview (5 min)

### 3.1 Runtime topology (production)

```
                ┌─────────────────────────────────┐
    Client ──►  │  Azure Front Door (WAF)         │
                └───────────────┬─────────────────┘
                                │
                ┌───────────────▼─────────────────┐
                │  APIM  (retry + circuit-breaker)│  ← infra/apim/policies/*.xml
                └───────────────┬─────────────────┘
                                │  (Entra JWT)
                ┌───────────────▼─────────────────┐
                │  Container Apps  (FastAPI app)  │  ← create_app(container)
                │  ─────────────────────────────  │
                │  auth → workflow_runtime.run    │
                │        ├─ ChatWorkflow           │
                │        │   ├─ chat_router        │
                │        │   └─ orchestration ──┐  │
                │        └─ (optional) synth    │  │
                │                              │   │
                │  ┌───────────────────────────▼─┐ │
                │  │ OrchestrationWorkflow       │ │
                │  │  orch_router → dispatcher   │ │
                │  │        ↓                    │ │
                │  │  ┌──────┴──────┐            │ │
                │  │  │ PRS  │Var  │FH│PGx│Phe│  │ │
                │  │  │spec  │spec │  │   │   │  │ │
                │  │  └──┬──────────────┘        │ │
                │  │     ▼  Postgres repos       │ │
                │  └─────────────────────────────┘ │
                └───────────────┬─────────────────┘
                                │
        ┌───────────┬───────────┼───────────┬──────────────┐
        ▼           ▼           ▼           ▼              ▼
   PG Flexible   Cosmos DB   Key Vault  Compass /       Application
   (patient +    (session +  (secrets)  Foundry LLM     Insights /
    annotations) turn state)                            Log Analytics
```

### 3.2 Chat vs. orchestration sub-workflow

- **ChatWorkflow** — decides whether the question needs clinical data at all.
  If not (small talk, help), it synthesises a reply directly. Otherwise it
  invokes the orchestration sub-workflow.
- **OrchestrationWorkflow** — a bounded loop
  (`orch_router → dispatcher → specialists → joiner → orch_router`) that
  dispatches specialists, merges their results into the shared state, and
  terminates when the router decides no further specialist is needed
  (or when the iteration budget of 12 is hit — see ADR-009).

### 3.3 What each specialist does

| Specialist | Domain | Example tool | Result schema |
|---|---|---|---|
| **PRS** | Polygenic risk scores | `get_patient_prs`, `search_prs_annotations` | `PRSResultList` |
| **Genomic Variants** | Variant calls + annotations | `get_patient_variants`, `search_variant_annotations` | `VariantResultList` |
| **Family History** | Pedigree criteria (NCCN, Amsterdam II, ...) | `get_patient_family_history` (privacy-redacted) | `FamilyHistoryResultList` |
| **PGx** | Drug–gene interactions (CPIC) | `get_patient_pgx`, `search_pgx_annotations` | `PGXResultList` |
| **Phenotype** | HPO/MONDO phenotype match | `get_patient_phenotype` | `PhenotypeResultList` |

---

## 4. MAF components we use, and why (10 min)

### 4.1 `Executor` + `WorkflowContext` (the core MAF primitive)

Every node in our workflow is a `class ... (Executor)` with a single
`@handler` method. The handler receives a typed message and either
sends the next message (`ctx.send_message(...)`) or yields the terminal
output (`ctx.yield_output(...)`).

**Why:** deterministic, testable, replayable. The whole workflow topology
is wired at container-build time — no hidden global state, no runtime
route mutation.

**Where in code:** every executor in
[`epg-maf/src/egp_maf/workflow/`](../../epg-maf/src/egp_maf/workflow/).

### 4.2 Structured decision types (Pydantic, `extra="forbid"`)

- `ChatRouterDecision` — needs_clinical_data / reset_agents
- `SpecialistDispatchSet` — which specialists to dispatch this iteration
- `ChatRequestBody` / `ChatResponseBody` — the HTTP contract

**Why:** every hand-off is validated at the boundary. Adding a field the
schema does not allow is a startup-time failure, not a runtime one.

### 4.3 DI Container ([`di/container.py`](../../epg-maf/src/egp_maf/di/container.py))

One `build_container(settings)` factory wires **every** singleton (DB pool,
Cosmos client, LLM clients, repositories, authenticator, workflow runtime).
All test suites, the smoke script, and the FastAPI app share the same shape.

**Why:** swap a real repo for a stub, a real LLM for a canned one, a real
Cosmos for an in-memory dict — without touching any workflow code.
Enables the "no LLM key" smoke server we are demoing today.

### 4.4 Observability (OpenTelemetry — W08)

- **7 span kinds**: `workflow_request`, `workflow_executor`, `specialist`,
  `tool`, `llm`, `repository`, `db`.
- **10 KPI metrics**: turn count / latency, specialist duration / failed,
  rate-limit hits, pool utilisation, prompt fallbacks, ...
- **PHI-safe attribute allowlist** — a static `FORBIDDEN_ATTRIBUTES` set is
  enforced on every `set_attribute()` call. A CI grep test also blocks
  regressions.

**Why:** clinical PHI must never end up in Log Analytics / traces.
Approach documented in ADR-011.

### 4.5 Resilience (W09)

- Typed error hierarchy → mapped to HTTP codes at the API boundary
  (`AccessDenied → 403`, `RoutingBudgetExceeded → 409`, `LLMError → 502`, ...).
- `RetryingSpecialistLlm` decorator implements exponential + jitter
  backoff **inside the process**, independent of APIM's retry policy.
- **Specialist isolation**: one specialist's failure marks its slot as
  `failed` — the other specialists and the synthesised reply still return.

**Why:** the customer's LangGraph prototype propagates a single error
into a whole-turn failure. That's clinically unacceptable.

### 4.6 Auth + audit (W07)

- Prod: **Entra JWT** verification against a JWKS endpoint, role check
  for `Clinician`.
- Dev: `StubAuthenticator` that accepts a JSON payload as a token — this
  is what makes today's demo possible without an Entra tenant.
- **Every request** emits an `AuditEvent` (route, clinician_id,
  patient_id, decision, outcome) suitable for a security SIEM.

---

## 5. Parallel vs. sequential dispatch (5 min)

### 5.1 The toggle

- **Setting:** `ORCH_DISPATCH_MODE` = `sequential` | `parallel`
  ([`config/settings.py`](../../epg-maf/src/egp_maf/config/settings.py))
- **Companion:** `ORCH_MAX_FANOUT_WIDTH` — caps concurrent specialists
  (default 1 in sequential, ≥2 in parallel).
- **Read by:** `OrchRouterExecutor` — see the `handle_state` method in
  the current file [`orch_router.py`](../../epg-maf/src/egp_maf/workflow/orchestration/orch_router.py).

### 5.2 What the router does

- **Sequential (default today):** router picks *one* specialist per
  iteration; runs to completion; router decides the next one. Safe,
  deterministic, cost-linear, easier to audit.
- **Parallel:** router picks a **set** of specialists that can run
  independently; the joiner waits for the whole set before the next
  routing decision. Faster wall-clock, higher peak cost, slightly more
  complex logs.

If the router in parallel mode ever returns >1 specialist while the mode
is sequential, the executor **downgrades** to the first one and logs
`orch_router.parallel_decision_downgraded` (see lines 77-92 in the
active file). Cap violations similarly downgrade with a warning.

### 5.3 How to toggle after deploy

| Environment | Mechanism |
|---|---|
| **Local dev** | Set `ORCH_DISPATCH_MODE=parallel` in `.env`, restart process |
| **Preprod / prod** | Edit [`infra/env/prod.bicepparam`](../../infra/env/prod.bicepparam) → redeploy Bicep; **or** change the Container App env var in the Azure Portal → restart the revision |
| **Runtime toggle (no restart)** | Not built — would require Azure App Configuration + feature flags |

### 5.4 Analytics partitioning

Every `orch_router.dispatched` log record carries `orch.mode` and
`orch.width`. W08 lifts them to OTEL span attributes so all dashboards
can partition latency / cost / error-rate by mode without a config join.

---

## 6. What's shipped vs. what's blocked (5 min)

### 6.1 Shipped (11/11 workstreams, tagged `w11-cutover`)

| WS | Title | Highlights | Ref |
|----|-------|------------|-----|
| W01 | Foundation | Settings, DI container, PG pool, Cosmos client, structured logging | [walkthrough](../walkthroughs/W01-foundation-walkthrough.md) |
| W02 | Clinical data layer | Schema, seed, repositories, authz | [walkthrough](../walkthroughs/W02-clinical-data-layer-walkthrough.md) |
| W03 | Domain repositories | 5 repos + 14 tool shims + family-history privacy | [walkthrough](../walkthroughs/W03-repositories-walkthrough.md) |
| W04 | MAF workflow skeleton | Chat + orchestration sub-workflows, routing, budget | [walkthrough](../walkthroughs/W04-workflow-skeleton-walkthrough.md) |
| W05 | Specialist agents | 5 specialists with tools + provenance | [walkthrough](../walkthroughs/W05-specialists-walkthrough.md) |
| W06 | Parallel execution & mode-parity | Sequential ↔ parallel harness + parity tests | [walkthrough](../walkthroughs/W06-mode-parity-walkthrough.md) |
| W07 | Authentication + authorization | Entra JWT, stub for dev, `AuditEvent` emitter | [walkthrough](../walkthroughs/W07-auth-walkthrough.md) |
| W08 | Observability | OTEL SDK, 7 spans, 10 metrics, PHI allowlist | [walkthrough](../walkthroughs/W08-observability-walkthrough.md) |
| W09 | Resilience & error handling | Typed errors, retry, isolation, response formatter | [walkthrough](../walkthroughs/W09-resilience-walkthrough.md) |
| W10 | Testing, evaluation & load | Golden-set schema, scorers, PHI CI detector, load runbook | [walkthrough](../walkthroughs/W10-testing-walkthrough.md) |
| W11 | Cutover, release & runbooks | FastAPI, APIM policies, 9 alerts, 3 dashboards, 8 runbooks, cutover playbook, release notes | [walkthrough](../walkthroughs/W11-cutover-walkthrough.md) |

**Testing snapshot:** 421 unit tests passing, 21 integration tests
skipped (require live Postgres — will run once Azure subscription is
available).

### 6.2 Open blockers (need M42 answers)

Complete list with background + questions + interim behaviour:
[`epg-maf/docs/blockers.md`](../../epg-maf/docs/blockers.md).

| ID | Blocker | Owner | Blocks |
|----|---------|-------|--------|
| **B-001** | PRS "EGP-evaluated" metadata model | BIX + M42 | Golden items S4, R5; PRS disclosure logic |
| **B-002** | Identity & session model (patient portal vs. clinician workspace) | M42 + IAM | Session-pinning contract; refusal wording |
| **B-003** | Patient identifier formats for `ScopeGuard` regex | BIX + M42 | Cross-patient detection coverage |
| **B-004** | Approved refusal message wording | M42 UX + Clinical safety | Golden-set assertion strings |
| **B-005** | Session lifecycle + explicit logout contract | M42 + Frontend | TTL sizing; refusal usefulness |
| **B-006** | Audit sink + alert threshold for scope violations | M42 Security + SIEM | Sev-3 alert rule; retention |

### 6.3 Golden-dataset gap analysis

The customer's [`docs/golden_dataset_prompts.pdf`](../golden_dataset_prompts.pdf)
(43 items) surfaced 3 concrete gaps:

1. **Single-patient scope guardrail** (G1–G5): the agent must refuse
   cross-patient questions with "log out and log back in". Design
   proposed (dedicated `ScopeGuard` service); blocked on **B-002 + B-003 +
   B-004**.
2. **Annotation vs. patient-scan distinction** (G6–G9): allow cohort
   questions answerable from annotation tables; refuse cohort questions
   requiring patient-row scans. Prompt-rule + repository-invariant test
   ready to build — no external blocker.
3. **"Not EGP-evaluated" PRS disclosure** (S4, R5): the schema has no
   `evaluated_in_egp` field today. Blocked on **B-001**.

---

## 7. Live demo script (10 min)

**Setup (before demo):** `cd epg-maf && .\.venv\Scripts\python.exe scripts\serve_smoke.py`

### 7.1 Health probe
- Browse `http://127.0.0.1:8000/healthz` → returns `{"status":"ok","service":"egp-window","env":"dev"}`.
- **Point out:** no-key mode; every specialist wired to stub repos + stub LLM factories.

### 7.2 Swagger UI
- Browse `http://127.0.0.1:8000/docs`.
- Click **Authorize** (top-right, unlock icon) → paste stub token:
  ```
  {"oid":"demo","tid":"demo","roles":["Clinician"],"exp":9999999999}
  ```
- **Point out:** the token is a JSON blob that stands in for a real Entra
  JWT (see §4.6). Prod uses a signed JWT verified against JWKS.

### 7.3 POST /chat
- Expand **POST /chat** → **Try it out** → body:
  ```json
  {"thread_id":"T-demo","patient_id":"P001","message":"What PRS does this patient have?"}
  ```
- Execute → 200 with populated `prs` + `pgx` slots and a synthesised `reply`.
- **Explain:** today's stub scenario dispatches PRS + PGX for every question
  as a canned multi-specialist example; with the real router (Compass key)
  a "what PRS" question would dispatch only the PRS specialist.

### 7.4 Response schema tour
- Walk through the `ChatResponseBody` shape: `thread_id`, `trace_id`,
  `reply`, `agents_completed`, per-specialist slots (`status`, `output`,
  `errors`).
- **Point out:** each specialist slot is independent — one specialist
  failing does not break the turn (W09 isolation).

### 7.5 Logs
- Show the terminal logs from the running server: structured log lines
  with `chat_router.decided`, `orch_router.dispatched`, `specialist_joiner.merged`,
  `orch_router.terminal`, `synthesize_response.completed`.
- **Point out:** those are the same log records that map to
  Application Insights `customMetrics` / `customEvents` in prod, and drive
  the 3 Azure Workbook dashboards (business, ops, security).

### 7.6 If time permits — the tests

```
.\.venv\Scripts\python.exe -m pytest -m "not integration and not parity and not chaos" -q
```

421 passed / 21 skipped.

---

## 8. Q&A prep — likely questions

| Q | Short answer | Deep-dive ref |
|---|---|---|
| Why MAF over the LangGraph prototype? | Azure-native, typed decisions, better testability, first-class observability, works with Foundry | [`solution-design-package.md`](../solution-design-package.md) §2 |
| Cost profile? | Bounded by iteration budget (12) + fanout width. Sequential mode = cost-linear; parallel bounded by max width | ADR-009, ADR-013 |
| PHI risk? | Static allowlist on every OTEL attribute + CI grep; family-history results explicitly redacted | W08, W03 privacy layer |
| What if a specialist fails? | Slot is marked `failed`, other specialists still run, synthesised reply still returns | W09 isolation tests |
| How do we roll back? | `cutover.md` playbook — idempotent, targets 30s rollback via revision swap | [`docs/runbooks/cutover.md`](../runbooks/cutover.md) |
| Real LLM demo when? | Immediately after Compass key + Azure subscription arrive; smoke server → `build_container()` = one env var flip | Documented at bottom of `smoke_run.py` |
| What is NOT built? | Real prod deploy (needs subscription), Foundry judge (needs tenant), 30-50 item BIX-approved golden set (draft only), Grafana mirror | [`v1.0.0.md`](../releases/v1.0.0.md) "Deferred" section |

---

## 9. Post-demo close (2 min)

1. Deliver blocker list (`blockers.md`) — ask for a single point-of-contact
   per blocker on M42 side.
2. Ask for Compass subscription key + Azure subscription onboarding target date.
3. Ask when a BIX reviewer can commit to the 43-item golden set for real evaluation.
4. Schedule a follow-up walk-through of the golden-set gaps once B-001 to B-006
   are unblocked.

---

## 10. Suggested reading order for the presenter

1. This file (`docs/demos/friday-demo-brief.md`) — you are here
2. [`README.md`](../../README.md) — 10 min
3. [`solution-design-package.md`](../solution-design-package.md) §1–§5 — 20 min
4. [`W04-workflow-skeleton-walkthrough.md`](../walkthroughs/W04-workflow-skeleton-walkthrough.md) — 15 min
5. [`orch_router.py`](../../epg-maf/src/egp_maf/workflow/orchestration/orch_router.py) — the current active file — 5 min
6. [`v1.0.0.md`](../releases/v1.0.0.md) — 10 min
7. [`epg-maf/docs/blockers.md`](../../epg-maf/docs/blockers.md) — 5 min
