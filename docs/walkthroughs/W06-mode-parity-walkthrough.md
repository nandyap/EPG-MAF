# W06 Parallel Execution & Mode-Parity — Walkthrough

**Purpose:** onboarding-friendly reference for W06. Deliberately concise.
For prior workstreams, see the earlier walkthroughs.

**Companion documents:** [architecture-discovery-report.md](../architecture-discovery-report.md) · [solution-design-package.md](../solution-design-package.md) · [engineering-implementation-plan.md](../engineering-implementation-plan.md) · [workstreams/workstream-log.md](../workstreams/workstream-log.md) · [orchestration config](../config/orchestration.md) · [enablement runbook](../runbooks/enable-parallel-dispatch.md).

---

## 1. What W06 shipped

W04 built the fan-out topology; W05 wired the specialists in. W06 is
the harness that proves flipping the dispatch mode from `sequential` to
`parallel` doesn't change the clinician-facing output, plus the
operational contract for enabling parallel in production.

```
epg-maf/
├── src/egp_maf/config/settings.py                     (+ dispatch_mode_summary() helper)
├── src/egp_maf/workflow/orchestration/orch_router.py  (+ orch.mode / orch.width log fields)
├── src/egp_maf/workflow/runtime.py                    (+ dispatch_mode_summary on startup log)
├── pyproject.toml                                     (+ mode_parity marker)
│
└── tests/
    ├── support/parity_diff.py                          ← NEW (deep-diff helper)
    ├── support/deterministic_specialists.py            ← NEW (canned SpecialistRegistry)
    ├── unit/test_parity_diff.py                        ← NEW (13 tests)
    ├── unit/test_settings.py                           (+ 2 tests: invalid mode + summary shape)
    └── mode_parity/                                    ← NEW
        ├── __init__.py
        ├── conftest.py                                 (auto-marks tests with `mode_parity`)
        └── test_mode_parity.py                         (4 harness classes / 4 tests)

docs/
├── config/orchestration.md                             ← NEW  (three orchestration knobs)
└── runbooks/enable-parallel-dispatch.md                ← NEW  (Design §16.8 checklist)
```

**Explicitly NOT shipped:** real OTEL span attributes (W08 owns OTEL —
W06 only emits log fields with the same key names so the port is
mechanical), load testing of the parallel path (W10), live-LLM shadow
test vs the prototype (later).

---

## 2. The harness in one picture

```mermaid
sequenceDiagram
    autonumber
    participant Test as test_mode_parity.py
    participant Seq as WorkflowRuntime (SEQUENTIAL, width=1)
    participant Par as WorkflowRuntime (PARALLEL, width=5)
    participant Fixture as build_deterministic_registry()
    participant Diff as parity_diff.deep_diff

    Test->>Fixture: fresh registry (all 5 specialists,<br/>StubSpecialistLlm each)
    Test->>Seq: run_turn(same ChatWorkflowState)
    Seq-->>Test: seq_final: ChatWorkflowState
    Test->>Fixture: fresh registry (independent state)
    Test->>Par: run_turn(same ChatWorkflowState)
    Par-->>Test: par_final: ChatWorkflowState
    Test->>Diff: deep_diff(_dump(seq_final), _dump(par_final))
    Diff-->>Test: [] iff structurally equal (modulo ignore keys)
    Test->>Test: assert diffs == []
```

**Contract:** the two final `ChatWorkflowState`s must be byte-identical
after dropping five well-known volatile fields — `updated_at`,
`produced_at`, `timestamp`, `router_iterations`, `retrieved_at`.
**Every** other field must match: provenance rows, derived fields
(`pathogenic_count`, `genes_assessed`, …), message content, `patient_id`.

---

## 3. Three notable design decisions

### 3.1 The harness runs the real workflow — only the LLM adapter is stubbed

The [deterministic fixture](../../epg-maf/tests/support/deterministic_specialists.py)
constructs a `SpecialistRegistry` with the **real** `PRSSpecialist`,
`GenomicVariantsSpecialist`, `FamilyHistorySpecialist`, `PGXSpecialist`,
`PhenotypeSpecialist`. Only the `SpecialistLlm` seam is stubbed. That
means the harness exercises:

- The full `SpecialistBase` 10-step recipe from W05
- Every tool-shim boundary from W05
- Provenance construction and `attach_provenance_to_results` matching
  (W05) for every domain
- The family-history privacy strip at both boundaries (tool shim + state
  output)
- All 5 programmatic derived-field computations
- The whole W04 workflow: `chat_router`, sub-workflow invocation,
  `orch_router`, `specialist_dispatcher`, fan-out to 5, fan-in via
  `specialist_joiner`, `synthesize_response`

If any of the above behaves differently under `parallel` vs
`sequential`, the diff list is non-empty.

### 3.2 Sanitisation lives in production code; the harness only proves it

The invariants F08.1 requires — "sequential enforces `|dispatch_set|=1`;
parallel caps at `ORCH_MAX_FANOUT_WIDTH`" — are implemented in
[`OrchRouterExecutor`](../../epg-maf/src/egp_maf/workflow/orchestration/orch_router.py)
as part of W04. W06 doesn't add sanitisation logic; it adds two harness
classes (`TestModeParityWidthSanitisation`, `TestModeParityWidthCap`)
that exercise those branches end-to-end and confirm they behave
consistently.

The parity property is thus:

- Enforced by construction (production code).
- Continuously validated (harness runs in CI on every change to any
  workflow / specialist / repository file).

### 3.3 Fresh registry per run — a real bug the harness caught

The stubbed `SpecialistLlm` returns the same `ResultList` instance
from every `run_extraction` call, and the specialist pipeline mutates
it in place (`result.provenance.append(...)`). The first draft of the
harness constructed one registry and used it for both the sequential
and parallel runs — result: the parallel run's PRS result had 2
provenance rows (one from sequential's mutation, one from parallel's),
and the harness caught it with a diff `list length 1 != 2`.

The fix: `build_deterministic_registry()` is called separately per
run so each `WorkflowRuntime` gets its own independent state. This is
now documented in the fixture's docstring as the intended usage
pattern.

**This is exactly the kind of cross-mode state contamination the
harness exists to find.**

---

## 4. Class quick reference

| Class / function | Where | One-line role |
|---|---|---|
| `deep_diff` | `tests/support/parity_diff.py` | Dotted-path structural diff; drops ignore keys at any depth; supports order-insensitive lists |
| `DEFAULT_IGNORE_KEYS` | `tests/support/parity_diff.py` | Frozen set: `updated_at`, `produced_at`, `timestamp`, `router_iterations`, `retrieved_at` |
| `build_deterministic_registry()` | `tests/support/deterministic_specialists.py` | Fresh `SpecialistRegistry` with 5 real specialists + stubbed LLMs, canned identical outputs |
| `TestModeParityFullFanout` | `tests/mode_parity/test_mode_parity.py` | All 5 specialists dispatched — canonical parallel case |
| `TestModeParityPartialFanout` | same | 2 specialists dispatched — subset case |
| `TestModeParityWidthSanitisation` | same | `sequential` downgrades multi-element decision to singleton (F08.1) |
| `TestModeParityWidthCap` | same | `parallel` caps at `ORCH_MAX_FANOUT_WIDTH` (F08.1) |
| `Settings.dispatch_mode_summary()` | `config/settings.py` | Returns `{'orch.mode', 'orch.max_fanout_width', 'orch.iteration_budget'}` for logs + enablement checklist |

---

## 5. How W06 relates to what came before

| Workstream | Piece W06 leans on |
|---|---|
| W04 | `OrchRouterExecutor` mode + width sanitisation; `SpecialistDispatcherExecutor` + `SpecialistJoinerExecutor` (order-independent merge); `apply_agents_completed` set-append reducer |
| W05 | `SpecialistBase` template; `StubSpecialistLlm`; `SpecialistExecutor`; every domain's provenance matcher and derived-field logic |
| Design ADR-013 | Fan-out plumbing from Phase 1; runtime flag flips |
| Design ADR-009 | Deterministic set-based `agents_completed` reducer — crucial for order-independent joiner |
| Design §16.8 | Verbatim enablement gate checklist ported to the runbook |

---

## 6. Operational notes

- **Running the harness locally:**
  ```powershell
  cd epg-maf
  .\.venv\Scripts\python.exe -m pytest -m mode_parity -q
  ```
- **Flipping to parallel in prod.** See
  [docs/runbooks/enable-parallel-dispatch.md](../runbooks/enable-parallel-dispatch.md).
  Don't merge the flag flip until every checklist item passes.
- **Log fields.** Every `orch_router.dispatched` event now carries
  `orch.mode` and `orch.width`. Every `workflow_runtime.built` event
  carries `orch.mode`, `orch.max_fanout_width`, `orch.iteration_budget`.
  Log parsers can partition latency / cost / error rates by mode
  without joining against config. **W08 will surface these same keys as
  OTEL span attributes — the key names are identical so the port is
  mechanical.**
- **Extending the ignore list.** Adding a field to
  `DEFAULT_IGNORE_KEYS` (in `tests/support/parity_diff.py`) is an
  intentional, reviewable action. If you find yourself wanting to add
  one, first check whether the field should be deterministic across
  modes.

---

## 7. Where to look next

- **Delivery status:** [workstream-log.md § W06](../workstreams/workstream-log.md#workstream-w06--parallel-execution--mode-parity-).
- **Design context:** [solution-design-package.md](../solution-design-package.md) ADR-013 (parallel-in-Phase-3), §16.6 (dispatch modes), §16.8 (enablement gate).
- **Config reference:** [docs/config/orchestration.md](../config/orchestration.md).
- **Enablement runbook:** [docs/runbooks/enable-parallel-dispatch.md](../runbooks/enable-parallel-dispatch.md).
- **Plan reference:** engineering-implementation-plan.md §E08 (F08.1–F08.4).

*Last updated: 2026-07-10.*
