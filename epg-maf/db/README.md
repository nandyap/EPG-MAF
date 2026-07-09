# EGP Window — Database

Everything needed to bring up the target Postgres 16 schema. Sibling to the
LangGraph prototype's DuckDB blob (`../test_data/clinical_genetics.duckdb`),
which we do NOT modify.

## Layout

```
db/
├── README.md              ← this file
├── schema/
│   └── V001__baseline.sql  ← the canonical baseline DDL (10 tables)
├── bootstrap/
│   └── roles.sql           ← creates egp_migrator + egp_agent_ro roles
├── seed/
│   ├── README.md
│   ├── export_from_duckdb.py  ← one-shot exporter DuckDB → CSV
│   ├── load.sql               ← \copy statements for psql
│   └── data/                  ← generated CSVs (not committed)
└── alembic/
    ├── alembic.ini
    ├── env.py
    ├── script.py.mako
    └── versions/
        └── 001_baseline_schema.py
```

## First-time setup (local dev)

Run these once, in this order, as a Postgres superuser (or the
`postgres` user in a local Docker container).

```powershell
# 1. Bring up Postgres 16.
docker run --rm -d --name egp-pg -e POSTGRES_PASSWORD=postgres `
    -p 5432:5432 postgres:16

# 2. Create the database and roles.
docker exec -i egp-pg psql -U postgres -c "CREATE DATABASE egp;"
docker exec -i egp-pg psql -U postgres -d egp -f - < db/bootstrap/roles.sql

# 3. Apply the schema via Alembic (from epg-maf/).
$env:ALEMBIC_URL = "postgresql+psycopg://egp_migrator:migrator_pw@localhost:5432/egp"
alembic -c db/alembic/alembic.ini upgrade head

# 4. Seed from the prototype's DuckDB (one-shot; requires ../test_data/).
python db/seed/export_from_duckdb.py --duckdb ../test_data/clinical_genetics.duckdb --out db/seed/data
docker exec -i egp-pg psql -U egp_migrator -d egp -f - < db/seed/load.sql
```

After this the `egp` database is ready. Repositories in W03 will connect as
`egp_agent_ro`.

## Design references

- Baseline schema: prototype `test_data/schema.sql` — ported byte-for-byte
  with mechanical Postgres adjustments per Design §11.2.
- Roles: `egp_agent_ro` (SELECT-only, application) and `egp_migrator`
  (DDL, CI-driven migrations only) — Design ADR-005 and §11.5.
- Migrations: Alembic with hand-written revisions — Design §11.6.

## Rules

- The prototype's `test_data/` is READ-ONLY reference data. Never modify it.
- Every SQL statement lives in one of three places: `schema/`, `bootstrap/`
  or Alembic `versions/`. Never inline DDL in application code.
- `egp_migrator` credentials must never appear in application config —
  they are used only by CI and by the local `alembic upgrade` command.
