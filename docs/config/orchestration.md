# Orchestration configuration

W04 shipped the orchestration workflow; W06 turned on the parallel-dispatch
capability behind a runtime flag. This page documents the three
orchestration knobs, their acceptable values, and where each is enforced.

## Runtime flags

| Env var / setting | Default | Range | Enforced at |
|---|---|---|---|
| `ORCH_DISPATCH_MODE` (`settings.orch_dispatch_mode`) | `sequential` | `sequential` \| `parallel` | Pydantic `DispatchMode` enum; invalid values raise `ValidationError` at process start |
| `ORCH_MAX_FANOUT_WIDTH` (`settings.orch_max_fanout_width`) | `1` | `1..5` | Pydantic `ge=1, le=5`; out-of-range raises at start |
| `ORCH_ITERATION_BUDGET` (`settings.orch_iteration_budget`) | `12` | `1..100` | Same; enforced per-iteration by `OrchRouterExecutor` (typed [`RoutingBudgetExceeded`](../../epg-maf/src/egp_maf/errors.py) on breach) |

## Semantics

- **`sequential` mode.** `OrchRouterExecutor` **silently downgrades** any
  multi-element `SpecialistDispatchSet` to a single element (the first
  in the LLM's response). Purpose: safety net. Prompt drift or LLM
  hallucination can't sneak parallel dispatch through under
  `sequential`. Downgrade emits a structured log event
  `orch_router.parallel_decision_downgraded` naming what was
  requested vs. what ran.
- **`parallel` mode.** `SpecialistDispatchSet` may contain any subset
  of the 5 specialists; the router caps at `ORCH_MAX_FANOUT_WIDTH` if
  the LLM asks for more. Cap emits `orch_router.fanout_width_capped`.
- **Fan-out topology is identical in both modes.** The workflow has one
  `specialist_dispatcher` executor with 5 fan-out edges to the 5
  `SpecialistExecutor` positions and 5 fan-in edges into
  `specialist_joiner`. The **only** thing the mode controls is how
  many of those branches actually do work per iteration — the wiring
  is unchanged. See [W04 walkthrough §2](../walkthroughs/W04-workflow-skeleton-walkthrough.md#2-the-topology-in-one-picture).

## Business-behaviour parity

`sequential` and `parallel` must produce **identical** clinician-facing
outputs for the same inputs, modulo timing and iteration count. This is
enforced by the [mode-parity harness](../../epg-maf/tests/mode_parity/test_mode_parity.py)
(F08.2), which:

- Runs both modes with a deterministic `SpecialistRegistry`.
- Deep-diffs the two final `ChatWorkflowState`s (`tests/support/parity_diff.py`).
- Ignores well-known volatile keys: `updated_at`, `produced_at`,
  `timestamp`, `router_iterations`, `retrieved_at`.

Every other field must match byte-for-byte. Any diff blocks CI.

## Where the mode/width/budget appear in logs

| Log event | Source | Fields |
|---|---|---|
| `workflow_runtime.built` | `WorkflowRuntime.__init__` | `dispatch_mode`, `max_fanout_width`, `iteration_budget`, `orch.mode`, `orch.max_fanout_width`, `orch.iteration_budget` |
| `orch_router.dispatched` | `OrchRouterExecutor` per dispatch | `dispatch`, `reason`, `iterations`, `orch.mode`, `orch.width` |
| `orch_router.parallel_decision_downgraded` | Only under `sequential` when LLM asked for >1 | `requested`, `reason` |
| `orch_router.fanout_width_capped` | Only under `parallel` when LLM asked for > `ORCH_MAX_FANOUT_WIDTH` | `requested_width`, `capped_to` |
| `orch_router.budget_exceeded` | Only when the router loop hits `ORCH_ITERATION_BUDGET` | `iterations`, `budget`, `agents_completed` |

W08 lifts the `orch.*` fields to OpenTelemetry span attributes so the
dashboards described in Design §22 can partition latency and cost by
mode.

## Enabling parallel in production

**Do not flip `ORCH_DISPATCH_MODE=parallel` in prod without completing
the enablement gate.** See
[docs/runbooks/enable-parallel-dispatch.md](../runbooks/enable-parallel-dispatch.md).

*Last updated: 2026-07-10.*
