"""001 baseline schema

Revision ID: 001_baseline_schema
Revises:
Create Date: 2026-07-09

Applies ``db/schema/V001__baseline.sql`` verbatim on upgrade, and drops all
ten tables in reverse-dependency order on downgrade.

Design references:
  - Solution Design §11.6 (Migrations).
  - Discovery Report §6.1 (Schema).
"""

from __future__ import annotations

from pathlib import Path
from typing import Sequence, Union

from alembic import op

# ── Alembic identifiers ─────────────────────────────────────────────
revision: str = "001_baseline_schema"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Reverse-dependency order for the DROP. Children first, then parents.
_DROP_ORDER: tuple[str, ...] = (
    "patient_kinship_history",
    "kinship_history_annotations",
    "pgx_annotations",
    "patient_pgx_status",
    "patient_variants",
    "variant_annotations",
    "patient_prs",
    "prs_annotations",
    "diagnoses",
    "patients",
)


def _load_schema_sql() -> str:
    """Return the baseline SQL as a single string.

    The schema file lives at ``db/schema/V001__baseline.sql`` — one directory
    up from this file's parent (``db/alembic/versions/`` → ``db/schema/``).
    """
    here = Path(__file__).resolve()
    schema_path = here.parents[2] / "schema" / "V001__baseline.sql"
    if not schema_path.is_file():
        raise RuntimeError(f"Baseline schema not found at {schema_path}")
    return schema_path.read_text(encoding="utf-8")


def upgrade() -> None:
    """Apply the baseline schema.

    The SQL file is executed as a single script. Postgres allows multiple
    statements per ``op.execute`` when we pass a raw string; we go through
    ``exec_driver_sql`` to avoid SQLAlchemy statement-parsing.
    """
    sql = _load_schema_sql()
    connection = op.get_bind()
    connection.exec_driver_sql(sql)


def downgrade() -> None:
    """Drop all baseline tables in reverse-dependency order.

    ``CASCADE`` is not used — we prefer explicit ordering so we notice if a
    dependency creeps in unexpectedly.
    """
    for table in _DROP_ORDER:
        op.execute(f"DROP TABLE IF EXISTS {table}")
