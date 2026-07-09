# W02 Design Review Report

**Reviewer:** Delivery Lead (self-review as Principal Architect)
**Scope reviewed:** everything landed in Workstream W02 — `epg-maf/db/*`,
`epg-maf/src/egp_maf/state/provenance.py`, `epg-maf/src/egp_maf/services/{provenance,authz}.py`,
`epg-maf/src/egp_maf/services/repositories/*`.
**Review criteria (from user directive):**

1. Repository Pattern applied correctly.
2. Repository returns typed domain models — not raw SQL rows.
3. Provenance generation lives inside the Repository layer.
4. Read-only DB access is enforced.
5. Repository layer stays simple; no unnecessary abstractions.
6. Recommend any class/interface that can be removed without loss of
   maintainability.

**Baseline documents:**

- Design §11 (PostgreSQL), §11.7 (Provenance at construction time),
  §12 (Repository & Service Layer), ADR-005, ADR-017.
- Discovery §1.4 (five design principles), §24.1 (Preserve list),
  §24.5 (DB seam is the load-bearing decision).

---

## 1. Executive summary

W02 shipped the base + services correctly. Two clear over-engineering issues
and one gap to acknowledge.

- ✅ **Read-only DB access** — enforced at three layers (role, session,
  application). No change recommended.
- ✅ **Provenance generation inside Repository** — `BaseRepository._build_provenance`
  is set up correctly. Domain repos in W03 will use it as designed.
- ⚠️ **Typed domain models** — the base returns `list[dict[str, Any]]`. The
  design promise (typed models bundled with provenance) is deferred to W03.
  This is expected but should be visible.
- ❌ **`IRepository` protocol is dead code.** No concrete class will ever
  conform to it as written. Recommend deletion.
- ❌ **`OpenAuthzPolicy` / `ClosedAuthzPolicy` in production code.** They
  are test doubles by their own docstrings. Recommend moving to `tests/`.
- ⚠️ **Package `services/repositories/` currently holds one file.** Not
  a blocker; will fill up in W03.

**Overall verdict:** aligned with the Solution Design. Two focused
simplifications recommended before W03 starts, both non-behavioural.

---

## 2. Direct answer to the user's question

> "Have we created the repo layer in this workstream?"

**No — only the base.**

W02 delivers:

- `BaseRepository` (abstract, no SQL).
- `IRepository` (protocol, no conformer).
- `ProvenanceService`, `AuthzPolicy` (supporting services).

W02 does NOT deliver any of the 5 concrete domain repositories. Those
(`PRSRepository`, `GenomicVariantsRepository`, `FamilyHistoryRepository`,
`PGXRepository`, `PhenotypeRepository`) are the W03 deliverable. Until
they exist, the "typed domain models with construction-time provenance"
design property (Design §11.7) is preserved as an unrealised contract.

---

## 3. Criterion-by-criterion review

### 3.1 Repository Pattern conformance

**Verdict:** ⚠️ Partial. Base is correct; concrete repos are absent.

**Evidence:**

- `BaseRepository` (`services/repositories/base.py:56–120`) exposes three
  helpers: `_authorize`, `_fetch_all`, `_build_provenance`. All three are
  correct primitives for a Repository:
  - `_authorize` enforces the RBAC gate on every read.
  - `_fetch_all` centralises pool acquisition and error wrapping.
  - `_build_provenance` centralises audit-record construction.
- Domain-specific behaviour (SQL, JOINs, projection, filtering) is
  correctly *not* present — that's the W03 subclass responsibility per
  Design §12.4.

**Gap:** the design's "one Repository per domain" is a promise for W03. The
review should re-check W03 for correct pattern conformance in the concrete
subclasses.

### 3.2 Typed domain models vs raw SQL rows

**Verdict:** ⚠️ Deferred by design. Currently the base returns `dict`.

**Evidence:** `BaseRepository._fetch_all` returns `list[dict[str, Any]]`
(`base.py:80–102`). The docstring calls this out — it "matches the
prototype's tool return shape (Discovery §5.1)".

**Assessment:** appropriate for a base class. The domain repositories in
W03 will translate dicts into typed Pydantic models (e.g. `PRSResult`)
before returning to callers. The base cannot make that decision because
the model type differs per domain.

**Recommendation:** none for W02. Track this in the W03 acceptance
checklist: "Every public method returns typed domain models, never
`dict[str, Any]`."

### 3.3 Provenance inside the Repository

**Verdict:** ✅ Correct.

**Evidence:** `BaseRepository._build_provenance` (`base.py:104–120`)
delegates to `ProvenanceService.build(...)` which is a thin factory around
`DBProvenance(...)`. The domain repositories in W03 will call this helper
per row at the moment the SQL is executed. Provenance is data-adjacent,
not LLM-adjacent — exactly the shift required by Design §11.7.

**No change recommended.** The prototype's post-hoc `_attach_provenance`
matching logic will not be reproduced; it becomes obsolete.

### 3.4 Read-only DB access

**Verdict:** ✅ Enforced at three layers.

**Evidence:**

1. **Role level** — `db/bootstrap/roles.sql:36–42` grants `egp_agent_ro`
   only `USAGE` on the schema. `db/schema/V001__baseline.sql:230–232`
   explicitly grants `SELECT ON ALL TABLES`. No write privileges anywhere.
2. **Session level** — `DbPoolFactory._configure_connection`
   (W01 code at `infrastructure/db_pool.py:159–164`) issues
   `SET SESSION CHARACTERISTICS AS TRANSACTION READ ONLY` per new pool
   connection.
3. **Application level** — `BaseRepository` only exposes `_fetch_all`. No
   INSERT/UPDATE/DELETE helper exists.

Any two of these can fail and the third still blocks a write. **No change
recommended.**

### 3.5 Repository layer simplicity — hunt for unnecessary abstractions

Below, each abstraction with a verdict.

| Abstraction | Verdict | Note |
|---|---|---|
| `BaseRepository` class | ✅ Keep | Three narrow helpers, each removes duplication that would appear 5× in W03. |
| `_authorize` helper | ✅ Keep | Trivial (one-liner) but names the security-critical step; makes W03 code readable and enforces the RBAC-first ordering by convention. |
| `_fetch_all` helper | ✅ Keep | Centralises pool acquisition + typed error wrapping. Domain repos would otherwise repeat this 3× each. |
| `_build_provenance` helper | ✅ Keep | Adds no logic over `ProvenanceService.build`, but hides the service from domain repos — a real information-hiding win. |
| `IRepository` protocol | ❌ **Remove** | See §4.1 below. |
| `services/repositories/` package (one file) | ⚠️ Acceptable | Will fill in W03. If W03 ends up with a single `repositories.py` module, collapse the package. |
| `ProvenanceService` | ✅ Keep | Provides the OTEL provider hook for W08. Without it, we'd have to modify `DBProvenance` construction sites in W08. |
| `AllowlistAuthzPolicy` | ✅ Keep | Load, parse, hot-reload, fail-closed. Directly implements ADR-017. |
| `OpenAuthzPolicy`, `ClosedAuthzPolicy` in `src/` | ❌ **Move to tests** | See §4.2 below. |
| `_Allowlist` inner class | ✅ Keep | Encapsulates parsing + admin-vs-clinician distinction. |

---

## 4. Simplification recommendations (ranked)

### 4.1 Remove `IRepository` protocol (high priority)

**File:** `epg-maf/src/egp_maf/services/repositories/base.py:37–54`
**Also touched:** `epg-maf/src/egp_maf/services/repositories/__init__.py` (export removal),
`epg-maf/src/egp_maf/services/__init__.py` (export removal),
`epg-maf/tests/unit/test_repository_base.py` (delete `TestIRepositoryProtocol`).

**Problem.** As currently written, `IRepository[TQuery, TResult]` declares a
single method:

```python
async def execute(self, ctx: ClinicianContext, query: TQuery) -> list[TResult]
```

The 5 domain repositories in W03 will NOT conform to this. They will have
domain-specific method names (`explore_patient_prs`, `search_prs_annotations`,
`get_patient_prs`, and three siblings per domain) that mirror the prototype's
tool signatures. There is no `execute(query)` method.

The base's own test (`test_base_is_not_a_repository_protocol`) explicitly
asserts that `BaseRepository` does NOT satisfy `IRepository` — and expresses
hope that W03 subclasses will. They will not.

**Impact if kept:** dead protocol. Every reader has to trace it, understand
it does not apply, and move on. Adds a `Protocol[TQuery, TResult]` +
`runtime_checkable` cognitive tax for zero runtime value.

**Impact if removed:** none. No production code path depends on it.

**Recommendation:** **Remove.** If we later want a common protocol for
Repositories, we'll derive it from the actual W03 signatures — bottom-up,
not top-down.

### 4.2 Move `OpenAuthzPolicy` and `ClosedAuthzPolicy` out of `src/`

**File:** `epg-maf/src/egp_maf/services/authz.py:139–158`

**Problem.** Both classes carry the docstring "Test-only policy … Never
used in production." They are in the same module as the production
`AllowlistAuthzPolicy`. Any developer might import them from
`egp_maf.services` and use them accidentally.

**Recommendation:** move both into `epg-maf/tests/support/authz_doubles.py`
(new file) and import from there in tests. `AuthzPolicy` (the protocol) stays
in `src/` because tests and production both need it.

**Effort:** trivial file move + 4 test-file imports updated. No behavioural
change.

**Alternative:** if the team prefers keeping them in `src/`, rename to
`_OpenAuthzPolicyForTests` / `_ClosedAuthzPolicyForTests` (underscore
prefix) and remove them from the `services/__init__.py` exports. Marginally
less clean but zero test churn.

### 4.3 Consider collapsing `services/repositories/` if W03 stays small

**File:** `epg-maf/src/egp_maf/services/repositories/*`

**Status.** Currently a package with two files (`__init__.py`, `base.py`).
W03 will add 5 concrete repositories — either as 5 separate files (giving
6 files total in the package) or as a single `repositories.py` (giving
2 files: base + all-domains).

**Recommendation.** Decide during W03 kickoff. If the domain repositories
end up small (< 100 lines each), one flat `repositories.py` module is
easier to navigate than a 5-file package. If they grow past that, split.

No action for W02.

---

## 5. Cross-cutting observations

### 5.1 Alignment with Discovery §24.1 (Preserve list)

Discovery §24.1 lists ten things Phase 1 must preserve. W02 preserves the
data-plane subset:

| Discovery preserve item | W02 status |
|---|---|
| Three-tool contract per domain | Deferred to W03 (domain repositories) |
| Provenance-first output | ✅ Base ready; W03 domain repos will emit |
| Reference/annotation split | ✅ Schema preserves the pattern for all 4 domains that have it |
| Two-schema privacy split for family history | Deferred to W03 |
| Controlled-vocabulary ownership boundary | ✅ All CHECK constraints preserved verbatim |
| DB seam intact | ✅ `BaseRepository._fetch_all` is the seam |
| Read-only DB access at connection level | ✅ Enforced (§3.4 above) |
| Centralised config | ✅ New settings + one migrator role — no scattered secrets |

### 5.2 Alignment with Design §11.7 (Provenance at construction time)

Design §11.7 says provenance should be built inside the Repository at the
moment the row is read. W02 supplies the mechanism (`_build_provenance`);
W03 will exercise it. **The design promise is set up correctly but not
yet realised.** The W03 review must verify each concrete Repository
actually attaches provenance per row, not post-hoc.

### 5.3 Fail-closed on RBAC config errors

`AllowlistAuthzPolicy` raises `ConfigurationError` at startup if the
allowlist file is missing or invalid, and denies all patient reads if no
path is configured. This matches the design intent (Design §19.3: last-mile
RBAC at the Repository entry) and avoids a "silently accept everything on
misconfig" failure mode.

### 5.4 No unit test for `DbPoolFactory._configure_connection`

Small gap: the per-connection `SET SESSION CHARACTERISTICS AS TRANSACTION
READ ONLY` is applied via a callback in W01's `DbPoolFactory`, but no test
proves it fires. The integration test `test_db_pool.py::test_read_only_session`
inspects the setting after the fact, which is sufficient but not exhaustive.

**Recommendation:** in W03, add a unit test that constructs a mock connection
and asserts the SET statement is issued. Not a W02 blocker.

---

## 6. What NOT to change

For clarity, these are things I would NOT touch:

- **CSV-based seed pipeline.** Direct DuckDB-to-Postgres bridges exist,
  but CSV is auditable and works over private endpoints. Keep as-is.
- **Alembic hand-written revisions (no autogenerate).** The design (§11.6)
  explicitly rejects autogenerate. W02 follows that. Keep.
- **`ProvenanceService` as a wrapper around `DBProvenance(...)`.** Feels
  thin, but it exists to give W08 a single place to attach OTEL context
  and give tests a deterministic clock. Removing would push those hooks
  into every domain Repository. Keep.
- **`_Allowlist` inner class inside `authz.py`.** Could be exported, but
  it's an implementation detail of `AllowlistAuthzPolicy`. Keep private.

---

## 7. Summary of recommended actions

Two concrete changes before starting W03:

1. **Delete** `IRepository` protocol and its solo unit test (`TestIRepositoryProtocol`
   in `test_repository_base.py`).
2. **Move** `OpenAuthzPolicy` and `ClosedAuthzPolicy` from `src/egp_maf/services/authz.py`
   to a new `tests/support/authz_doubles.py`.

One thing to watch:

3. When starting W03, decide whether to keep `services/repositories/` as a
   package or collapse to a single `repositories.py` — depends on total
   domain-repository LOC.

No behavioural changes are required. No architectural revisit. All
recommendations reduce cognitive surface area without touching the design.

---

## 8. Sign-off

Recommend addressing items 1 and 2 above as a small pre-W03 cleanup PR
(no new functionality, no new tests, no design change). If accepted, the
cleanup can be included in the W02 commit tag `w02-data-layer` or shipped
as a follow-up commit `w02-data-layer-cleanup`.

*Reviewer: Delivery Lead. Date: 2026-07-09.*

**Status update (2026-07-09):** Recommendations §4.1 and §4.2 applied in a
small post-W02 cleanup commit. `IRepository` protocol removed;
`OpenAuthzPolicy` and `ClosedAuthzPolicy` moved to
`epg-maf/tests/support/authz_doubles.py`. No behavioural change.
