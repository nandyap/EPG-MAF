"""Integration tests — data-quality invariants on the seeded Postgres.

Requires the baseline schema applied AND the DuckDB CSVs loaded (see
``db/seed/README.md``). Skipped when ``EGP_TEST_POSTGRES=1`` is not set.

Invariants asserted (Discovery §22 M7 / Design §11.8):

1. Every table has at least one row.
2. For every ``patient_prs`` row, ``disease_name`` matches the
   ``prs_annotations`` row for the same ``prs_name`` — the intentional
   denormalisation must not have drifted.
3. Every ``patient_variants.variant_id`` has a matching
   ``variant_annotations`` row (FK check surfaced as an invariant).
4. Every ``patient_pgx_status.gene`` appears in at least one
   ``pgx_annotations`` row (matching the specialist's LEFT-JOIN
   expectation is optional — the invariant is only that gene names
   overlap).
"""

from __future__ import annotations

import pytest

from tests.integration.conftest import require_postgres


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


def _connect_ro() -> "psycopg.Connection":  # noqa: F821
    import psycopg

    from tests.integration.conftest import _build_agent_ro_conninfo

    return psycopg.connect(_build_agent_ro_conninfo())


@require_postgres
class TestSeedInvariants:
    def test_every_table_non_empty(self) -> None:
        with _connect_ro() as conn:
            with conn.cursor() as cur:
                for table in TABLES:
                    cur.execute(f"SELECT COUNT(*) FROM {table}")
                    (count,) = cur.fetchone()  # type: ignore[misc]
                    assert count > 0, f"Table {table} is empty — seed data missing"

    def test_patient_prs_disease_matches_annotations(self) -> None:
        """Discovery §22 M7 — denormalisation of ``disease_name`` must not drift."""
        with _connect_ro() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT p.prs_name, p.disease_name, a.disease_name
                    FROM patient_prs p
                    JOIN prs_annotations a ON p.prs_name = a.prs_name
                    WHERE p.disease_name IS DISTINCT FROM a.disease_name
                    """
                )
                mismatches = cur.fetchall()
                assert not mismatches, (
                    f"patient_prs.disease_name drift detected: {mismatches[:5]}"
                )

    def test_every_patient_variant_has_annotation(self) -> None:
        with _connect_ro() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT COUNT(*)
                    FROM patient_variants pv
                    LEFT JOIN variant_annotations va
                        ON pv.variant_id = va.variant_id
                    WHERE va.variant_id IS NULL
                    """
                )
                (orphan_count,) = cur.fetchone()  # type: ignore[misc]
                assert orphan_count == 0, "patient_variants rows without annotation"

    def test_every_pgx_gene_appears_in_annotations(self) -> None:
        with _connect_ro() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT DISTINCT pps.gene
                    FROM patient_pgx_status pps
                    LEFT JOIN pgx_annotations pa ON pps.gene = pa.gene
                    WHERE pa.gene IS NULL
                    """
                )
                orphans = [row[0] for row in cur.fetchall()]
                assert not orphans, (
                    f"patient_pgx_status genes with no annotation: {orphans}"
                )
