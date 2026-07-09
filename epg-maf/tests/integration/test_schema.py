"""Integration tests — verifies the baseline schema applies cleanly to Postgres.

Requires:
- A running Postgres 16 with the ``egp`` database and the ``egp_migrator``
  role created via ``db/bootstrap/roles.sql``.
- ``ALEMBIC_URL`` OR ``POSTGRES_MIGRATOR_*`` env vars pointing at it.
- ``EGP_TEST_POSTGRES=1``.

Skipped otherwise.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from tests.integration.conftest import require_postgres

_EPG_MAF_ROOT = Path(__file__).resolve().parents[2]
_ALEMBIC_INI = _EPG_MAF_ROOT / "db" / "alembic" / "alembic.ini"


EXPECTED_TABLES: frozenset[str] = frozenset(
    {
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
    }
)


def _run_alembic(*args: str) -> subprocess.CompletedProcess[str]:
    """Run ``alembic -c <alembic.ini> <args...>`` and return the result."""
    cmd = ["alembic", "-c", str(_ALEMBIC_INI), *args]
    return subprocess.run(
        cmd,
        cwd=str(_EPG_MAF_ROOT),
        check=False,
        text=True,
        capture_output=True,
    )


@require_postgres
class TestBaselineSchemaLifecycle:
    """Applies and reverts the baseline schema, checking every table."""

    def test_upgrade_creates_all_ten_tables(self) -> None:
        # First downgrade to base (idempotent — if nothing applied, no-op).
        _run_alembic("downgrade", "base")
        result = _run_alembic("upgrade", "head")
        assert result.returncode == 0, f"alembic upgrade failed:\n{result.stderr}"

        # Query information_schema to verify every expected table exists.
        import psycopg  # local import — only needed under integration marker

        from tests.integration.conftest import _build_migrator_conninfo  # helper below

        conninfo = _build_migrator_conninfo()
        with psycopg.connect(conninfo) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT table_name
                    FROM information_schema.tables
                    WHERE table_schema = 'public'
                    """
                )
                found = {row[0] for row in cur.fetchall()}

        missing = EXPECTED_TABLES - found
        assert not missing, f"Missing tables after upgrade: {sorted(missing)}"

    def test_downgrade_drops_all_ten_tables(self) -> None:
        # Ensure schema is up first.
        _run_alembic("upgrade", "head")
        result = _run_alembic("downgrade", "base")
        assert result.returncode == 0, f"alembic downgrade failed:\n{result.stderr}"

        import psycopg
        from tests.integration.conftest import _build_migrator_conninfo

        conninfo = _build_migrator_conninfo()
        with psycopg.connect(conninfo) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT COUNT(*) FROM information_schema.tables
                    WHERE table_schema = 'public'
                      AND table_name = ANY(%s)
                    """,
                    (list(EXPECTED_TABLES),),
                )
                (remaining,) = cur.fetchone()  # type: ignore[misc]
                assert remaining == 0, "Some tables remain after downgrade"
