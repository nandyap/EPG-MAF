# W02 Clinical Data Layer — Walkthrough

**Purpose:** onboarding-friendly reference for W02. Deliberately concise. If a
topic is not mentioned here, it means W02 did not touch it — see the
[W01 walkthrough](W01-foundation-walkthrough.md) for foundation concerns.

**Companion documents:** [architecture-discovery-report.md](../architecture-discovery-report.md) · [solution-design-package.md](../solution-design-package.md) · [engineering-implementation-plan.md](../engineering-implementation-plan.md) · [workstreams/workstream-log.md](../workstreams/workstream-log.md).

---

## 1. What W02 shipped

**Data layer** — everything that lets Postgres replace DuckDB and everything
that a future domain repository needs to inherit.

```
epg-maf/
├── db/                              ← NEW (11 files)
│   ├── schema/V001__baseline.sql    ← 10-table baseline (byte-parity port)
│   ├── bootstrap/roles.sql          ← egp_migrator + egp_agent_ro
│   ├── seed/export_from_duckdb.py   ← one-shot DuckDB → CSV exporter
│   ├── seed/load.sql                ← psql \copy load script
│   └── alembic/…                    ← migration mechanism
│
└── src/egp_maf/
    ├── state/provenance.py          ← NEW: DBProvenance (ported)
    ├── services/provenance.py       ← NEW: ProvenanceService
    ├── services/authz.py            ← NEW: AuthzPolicy + Allowlist v1
    └── services/repositories/       ← NEW: BaseRepository
```

Plus test files (7 new). See `workstream-log.md::W02` for the enumerated list.

**Explicitly NOT shipped:** the 5 concrete domain repositories, the
deterministic JSON parser, the 14 `ai_function` tool shims. Those are W03.

---

## 2. Prototype → target — the four things that changed

| Prototype | Target | Why |
|---|---|---|
| `test_data/schema.sql` (DuckDB) | `db/schema/V001__baseline.sql` (Postgres 16) | Runtime store change; mechanical port (Design §11.2) |
| `test_data/clinical_genetics.duckdb` (blob) | `db/seed/export_from_duckdb.py` + CSVs + `load.sql` | One-shot developer step; CSVs gitignored |
| `agents/shared/state/provenance.py::DBProvenance` | `src/egp_maf/state/provenance.py::DBProvenance` | Port with two additions: optional `trace_id`/`span_id` (for W08), `datetime.now(timezone.utc)` (deprecation-safe) |
| Provenance built by per-tool `_attach_provenance` in the specialist | Provenance built by `ProvenanceService.build(...)` inside the Repository | Construction-time truth (Design §11.7) |

Everything else in the prototype's data path is preserved unchanged: same
column names, same CHECK vocabularies, same indexes, same FK topology.

---

## 3. Key design decisions

### 3.1 Two Postgres roles, not one

- `egp_migrator` — DDL rights, used only by Alembic and CI. Never by the app.
- `egp_agent_ro` — SELECT-only, used by the runtime. Cannot mutate clinical
  data even if a bug tried.

This is the belt-and-braces defence for read-only guarantees. The Postgres
side of the seat-belt; the application side is `SET SESSION CHARACTERISTICS
AS TRANSACTION READ ONLY` in `DbPoolFactory` (from W01).

### 3.2 Seed by CSV, not by direct DB-to-DB copy

Postgres does not read DuckDB. We could have used a bridge library, but CSV
via `psql \copy` is:

- Simpler (one file per table).
- Auditable (a human can inspect the CSV).
- Compatible with private-endpoint Postgres (client-side `\copy` doesn't
  need server file access).

The exporter is a one-shot developer step, not a runtime concern.

### 3.3 `AllowlistAuthzPolicy` fails closed

If no allowlist path is configured, or the file goes missing, or the JSON
is invalid — the policy denies everyone (except the built-in system context
used by background jobs and tests). Design ADR-017 requires last-mile RBAC
at the Repository entry; failing open would defeat that.

### 3.4 Provenance moves left (from specialist → Repository)

Prototype: `_attach_provenance` ran in the specialist AFTER the LLM's
extraction, matching result rows to tool outputs by domain key (fragile).

Target: `ProvenanceService.build(...)` runs INSIDE the Repository at the
moment the SQL row is read. The Repository knows the source table and the
JOIN shape — provenance construction is data-adjacent, not LLM-adjacent.

---

## 4. Class quick reference

Every class in W02, one paragraph each.

**`DBProvenance`** (`state/provenance.py`) — immutable audit record linking
one clinical fact to its exact DB source row. Port of the prototype model
with two new optional fields (`trace_id`, `span_id`) for the W08 OTEL
correlation.

**`ProvenanceService`** (`services/provenance.py`) — thin factory that
constructs `DBProvenance` records with a pluggable clock and an optional
OTEL context provider. One place to attach tracing metadata later.

**`AuthzPolicy` (Protocol)** (`services/authz.py`) — abstract contract:
`can_read(ctx, patient_id)` and `enforce_read(ctx, patient_id)`.

**`AllowlistAuthzPolicy`** (`services/authz.py`) — production policy. Reads a
JSON file (Key Vault mounted in prod), supports admin bypass, mtime hot
reload. Fails closed on missing/invalid config.

**`OpenAuthzPolicy` / `ClosedAuthzPolicy`** (`tests/support/authz_doubles.py`)
— test doubles. Never used in production. Kept out of `src/` so production
code cannot import them accidentally.

**`BaseRepository`** (`services/repositories/base.py`) — shared plumbing for
the 5 domain repositories that arrive in W03. Owns three helpers:
`_authorize`, `_fetch_all`, `_build_provenance`. Domain repositories inherit
this and only write SQL.

**`AccessDenied`** (`errors.py`) — 403 typed exception raised by policy on
authorisation failure.

---

## 5. How W03 will use W02

A domain repository (W03) will look roughly like this — the SQL is the only
thing that changes per domain:

```python
class PRSRepository(BaseRepository):
    async def explore_patient_prs(
        self, ctx: ClinicianContext, patient_id: str,
    ) -> list[tuple[PRSResult, DBProvenance]]:
        self._authorize(ctx, patient_id)
        rows = await self._fetch_all(
            "SELECT patient_id, prs_name, disease_name, risk_band "
            "FROM patient_prs WHERE patient_id = %s",
            [patient_id],
        )
        return [
            (
                PRSResult.model_validate(row),
                self._build_provenance(
                    tool_name="explore_patient_prs",
                    tool_parameters={"patient_id": patient_id},
                    source_table="patient_prs",
                    source_row=row,
                    fields_derived=list(row.keys()),
                ),
            )
            for row in rows
        ]
```

Key contract points enforced by the base:

- `_authorize` is called before any SQL runs.
- `_fetch_all` wraps driver errors as `DatabaseUnavailable`.
- `_build_provenance` produces the audit trail row-by-row.

Base methods are `_authorize`, `_fetch_all`, `_build_provenance`. Each
domain repository supplies its own public methods (e.g. `explore_patient_prs`)
mirroring the prototype's tool signatures — no shared `execute` abstraction.

---

## 6. Operational notes

### 6.1 First-time local setup

See [`epg-maf/db/README.md`](../../epg-maf/db/README.md) for the exact commands. Summary:

1. Bring up Postgres 16 in Docker.
2. `psql -f db/bootstrap/roles.sql` (as superuser).
3. `alembic upgrade head` (as `egp_migrator`).
4. `python db/seed/export_from_duckdb.py --duckdb ../test_data/clinical_genetics.duckdb --out db/seed/data`.
5. `psql -f db/seed/load.sql` (as `egp_migrator`).

### 6.2 Environment variables added in W02

| Variable | Purpose |
|---|---|
| `POSTGRES_MIGRATOR_USER` | Alembic-only user (never used by the app) |
| `POSTGRES_MIGRATOR_PASSWORD` | Alembic-only password |
| `EGP_AUTHZ_ALLOWLIST_PATH` | Path to the RBAC allowlist JSON (Key Vault mount point in prod) |

### 6.3 Metric emitted (not yet wired to OTEL — W08)

- `authz.denied` (structured log event) — RBAC denial. Carries `clinician_id`,
  `patient_id`, `route`. Never carries PHI.

### 6.4 Failure modes

| Situation | Behaviour |
|---|---|
| Allowlist path unset | Deny all except `system` context |
| Allowlist file missing at startup | `ConfigurationError` at container startup |
| Allowlist file invalid JSON | `ConfigurationError` at container startup |
| Postgres reachable but role missing SELECT | `DatabaseUnavailable` on first query |
| `patient_id` not in clinician's allowlist | `AccessDenied` (403) with audit event |

---

## 7. Where to look next

- **Delivery status:** [workstreams/workstream-log.md](../workstreams/workstream-log.md) — Progress dashboard and W02 detail.
- **Design context:** [solution-design-package.md](../solution-design-package.md) §11 (Postgres), §12 (Repository & Service Layer), ADR-005, ADR-017.
- **Prototype reference:** the DuckDB schema at `test_data/schema.sql` and `agents/shared/state/provenance.py`.
- **Simplification recommendations:** the review report at `W02-design-review.md` (sibling to this file).

*Last updated: 2026-07-09.*
