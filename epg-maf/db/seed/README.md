# EGP Window — Seed pipeline

Exports the prototype's DuckDB blob (`../test_data/clinical_genetics.duckdb`)
to per-table CSV files, then loads them into Postgres via `psql \copy`.

## Why two steps?

Because Postgres does not read DuckDB files. CSV is the lingua franca. The
export is a one-shot developer step; the load is scripted and repeatable.

## Files

| File | Role |
|---|---|
| `export_from_duckdb.py` | One-shot Python script. Reads DuckDB, writes CSVs into `data/`. |
| `data/*.csv` | Generated files. NOT committed. |
| `load.sql` | `\copy` statements. Run with `psql -f load.sql`. |

## Usage

From `epg-maf/` root, with a Postgres 16 database ready and the baseline
schema applied (see `../README.md`):

```powershell
# 1. Export from the prototype's DuckDB. Requires duckdb Python package
#    (installed via the dev-extras of pyproject.toml).
python db/seed/export_from_duckdb.py `
    --duckdb ..\test_data\clinical_genetics.duckdb `
    --out    db/seed/data

# 2. Load into Postgres. Point psql at the target DB.
$env:PGPASSWORD = "migrator_pw"
psql -h localhost -U egp_migrator -d egp -f db/seed/load.sql
```

## Ordering guarantees

`load.sql` inserts in **FK-safe order**:

1. `patients`
2. `prs_annotations`
3. `variant_annotations`
4. `kinship_history_annotations`
5. `diagnoses`, `patient_prs`, `patient_variants`, `patient_pgx_status`, `pgx_annotations`, `patient_kinship_history`

## Data-quality invariants

After loading, `tests/integration/test_seed_invariants.py` verifies that:

- Every table has ≥ 1 row.
- Every table's row count matches the source DuckDB row count.
- `patient_prs.disease_name` matches `prs_annotations.disease_name` for the
  same `prs_name` (Discovery §22 M7, Design §11.8).
- Every `patient_variants.variant_id` has an annotation row.
- Every `patient_pgx_status.gene` appears in at least one `pgx_annotations` row.

## Idempotence

The exporter overwrites the CSVs each run. `load.sql` does NOT truncate
before loading — if you want to re-seed, run `TRUNCATE ... RESTART IDENTITY
CASCADE` first, or run Alembic downgrade + upgrade.
