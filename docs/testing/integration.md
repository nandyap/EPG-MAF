# Integration test harness — F12.2

> Delivered by **W10 (Testing, Evaluation & Load)**.
> Applies to code under `epg-maf/tests/integration/` and the CI job
> scaffold under `.github/workflows/integration.yml`.

## 1. Contract

The integration marker (`@pytest.mark.integration`) is used by every
test that requires a real Postgres or Cosmos emulator. Runs are gated
by two environment variables:

- `EGP_TEST_POSTGRES` — set to `1` when a seeded Postgres is available
  at the coordinates in `.env`. Repository tests + seed invariants +
  db-pool tests read this.
- `EGP_TEST_COSMOS` — set to `1` when the Cosmos emulator is running.
  `test_cosmos.py` reads this.

Unset variables → tests are `skip`ped with a clear reason.

**Runtime target:** the whole integration suite completes in under 10
minutes on the GHA runner.

## 2. Local dev

```pwsh
# Postgres (uses the docker-compose profile shipped with the repo)
docker compose --profile db up -d
$env:EGP_TEST_POSTGRES = "1"
python -m pytest -m integration -q

# Cosmos emulator (Windows only; install per Microsoft docs)
$env:EGP_TEST_COSMOS = "1"
python -m pytest tests/integration/test_cosmos.py -q
```

## 3. CI job scaffold

The GHA workflow lives at `.github/workflows/integration.yml` (added
alongside W11's cutover PR). Key steps:

1. Start Postgres via GHA `services:` block; seed via
   `alembic upgrade head` + `python -m tests.support.seed`.
2. Start Cosmos emulator (linux emulator container).
3. Set the two `EGP_TEST_*` env vars.
4. Run `python -m pytest -m integration --junitxml=integration.xml`.
5. Upload `integration.xml` for the flakiness dashboard.

## 4. Coverage today

| Test file | Purpose |
|---|---|
| `test_schema.py` | Alembic head migration matches the design DDL. |
| `test_seed_invariants.py` | Seeded row counts match the DuckDB origin. |
| `test_repositories.py` | Every repository method executes against real Postgres. |
| `test_db_pool.py` | Pool open/close + connect retry against a running Postgres. |
| `test_cosmos.py` | ETag-conditional writes + retry against the emulator. |

## 5. See also

- Engineering Plan §E12 (F12.2)
- Solution Design §27.4 (integration test scope)
- [Chaos scenarios](chaos.md)
- [Load tests](load.md)
