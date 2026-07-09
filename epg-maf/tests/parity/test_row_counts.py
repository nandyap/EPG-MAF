"""Parity — row counts between the prototype DuckDB blob and the seeded Postgres.

For every table, asserts the row count matches. This is the strongest
byte-parity check available at the data-layer stage; column-level value
parity is verified per Repository in W03.

Requires:
- The prototype DuckDB at ``../test_data/clinical_genetics.duckdb``.
- A Postgres seeded from the DuckDB via ``db/seed/load.sql``.
- ``EGP_TEST_POSTGRES=1``.

Skipped otherwise.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.integration.conftest import require_postgres

_HERE = Path(__file__).resolve()
_WORKSPACE = _HERE.parents[3]
_DUCKDB_PATH = _WORKSPACE / "test_data" / "clinical_genetics.duckdb"


TABLES: tuple[str, ...] = (
    "patients",
    "diagnoses",
    "prs_annotations",
    "patient_prs",
    "variant_annotations",
    "patient_variants",
    "patient_pgx_status",
    "pgx_annotations",
    "kinship_history_annotations",
    "patient_kinship_history",
)


def _requires_duckdb() -> pytest.MarkDecorator:
    if not _DUCKDB_PATH.is_file():
        return pytest.mark.skip(reason=f"Prototype DuckDB not found at {_DUCKDB_PATH}")
    try:
        import duckdb  # noqa: F401 — import-only check
    except ImportError:
        return pytest.mark.skip(reason="duckdb package not installed")
    return pytest.mark.parity


@_requires_duckdb()
@require_postgres
class TestRowCountParity:
    def test_row_counts_match_prototype(self) -> None:
        import duckdb
        import psycopg
        from tests.integration.conftest import _build_agent_ro_conninfo

        duck_counts: dict[str, int] = {}
        con = duckdb.connect(str(_DUCKDB_PATH), read_only=True)
        try:
            for table in TABLES:
                (count,) = con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()
                duck_counts[table] = count
        finally:
            con.close()

        pg_counts: dict[str, int] = {}
        with psycopg.connect(_build_agent_ro_conninfo()) as conn:
            with conn.cursor() as cur:
                for table in TABLES:
                    cur.execute(f"SELECT COUNT(*) FROM {table}")
                    (count,) = cur.fetchone()  # type: ignore[misc]
                    pg_counts[table] = count

        mismatches = {
            t: (duck_counts[t], pg_counts[t])
            for t in TABLES
            if duck_counts[t] != pg_counts[t]
        }
        assert not mismatches, (
            f"Row count mismatch (duckdb vs postgres): {mismatches}"
        )
