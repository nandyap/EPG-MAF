-- =============================================================================
-- EGP Window — Seed load script
--
-- Loads the CSVs produced by db/seed/export_from_duckdb.py into Postgres.
-- Runs FK-parents first, children second.
--
-- Prerequisites:
--   - Baseline schema applied (Alembic upgrade head).
--   - CSVs present in db/seed/data/.
--
-- Usage:
--   psql -h localhost -U egp_migrator -d egp -f db/seed/load.sql
--
-- Idempotence:
--   This script does NOT truncate. To re-seed, run first:
--     TRUNCATE
--       patient_kinship_history, patient_pgx_status, patient_variants,
--       patient_prs, diagnoses, pgx_annotations,
--       kinship_history_annotations, variant_annotations, prs_annotations,
--       patients
--     RESTART IDENTITY CASCADE;
--
-- CSV format:
--   - Header row present.
--   - Empty fields → SQL NULL (`NULL AS ''`).
--   - annotations_json is a compact JSON string, loaded as jsonb.
-- =============================================================================

\set ON_ERROR_STOP on

BEGIN;

\echo Loading patients ...
\copy patients FROM 'db/seed/data/patients.csv'
    WITH (FORMAT csv, HEADER true, NULL '');

\echo Loading prs_annotations ...
\copy prs_annotations FROM 'db/seed/data/prs_annotations.csv'
    WITH (FORMAT csv, HEADER true, NULL '');

\echo Loading variant_annotations ...
\copy variant_annotations FROM 'db/seed/data/variant_annotations.csv'
    WITH (FORMAT csv, HEADER true, NULL '');

\echo Loading kinship_history_annotations ...
\copy kinship_history_annotations FROM 'db/seed/data/kinship_history_annotations.csv'
    WITH (FORMAT csv, HEADER true, NULL '');

\echo Loading diagnoses ...
\copy diagnoses FROM 'db/seed/data/diagnoses.csv'
    WITH (FORMAT csv, HEADER true, NULL '');

\echo Loading patient_prs ...
\copy patient_prs FROM 'db/seed/data/patient_prs.csv'
    WITH (FORMAT csv, HEADER true, NULL '');

\echo Loading patient_variants ...
\copy patient_variants FROM 'db/seed/data/patient_variants.csv'
    WITH (FORMAT csv, HEADER true, NULL '');

\echo Loading patient_pgx_status ...
\copy patient_pgx_status FROM 'db/seed/data/patient_pgx_status.csv'
    WITH (FORMAT csv, HEADER true, NULL '');

\echo Loading pgx_annotations ...
\copy pgx_annotations FROM 'db/seed/data/pgx_annotations.csv'
    WITH (FORMAT csv, HEADER true, NULL '');

\echo Loading patient_kinship_history ...
\copy patient_kinship_history FROM 'db/seed/data/patient_kinship_history.csv'
    WITH (FORMAT csv, HEADER true, NULL '');

-- Reset identity sequences so future INSERTs get fresh IDs.
SELECT setval(
    pg_get_serial_sequence('diagnoses', 'id'),
    COALESCE((SELECT MAX(id) FROM diagnoses), 1)
);
SELECT setval(
    pg_get_serial_sequence('pgx_annotations', 'id'),
    COALESCE((SELECT MAX(id) FROM pgx_annotations), 1)
);

COMMIT;

\echo Seed complete.
