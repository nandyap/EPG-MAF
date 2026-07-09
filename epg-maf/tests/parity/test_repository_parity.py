"""Parity tests — Repository outputs vs. the prototype DuckDB.

For each domain's ``get_patient_*`` we run the equivalent DuckDB query
against the prototype seed and compare row counts + key fields. This is
the strongest field-level parity check available before specialists exist.

Requires:
- The seeded Postgres.
- The prototype DuckDB at ``test_data/clinical_genetics.duckdb``.
- ``EGP_TEST_POSTGRES=1``.

Skipped otherwise.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any, cast

import pytest

from egp_maf.config.settings import Settings
from egp_maf.infrastructure.db_pool import DbPoolFactory
from egp_maf.services.provenance import ProvenanceService
from egp_maf.services.repositories import (
    FamilyHistoryRepository,
    GenomicVariantsRepository,
    PGXRepository,
    PhenotypeRepository,
    PRSRepository,
)
from egp_maf.state.clinician_context import ClinicianContext
from tests.integration.conftest import require_postgres
from tests.support.authz_doubles import OpenAuthzPolicy


_HERE = Path(__file__).resolve()
_WORKSPACE = _HERE.parents[3]
_DUCKDB_PATH = _WORKSPACE / "test_data" / "clinical_genetics.duckdb"


def _requires_duckdb() -> pytest.MarkDecorator:
    if not _DUCKDB_PATH.is_file():
        return pytest.mark.skip(reason=f"Prototype DuckDB not found at {_DUCKDB_PATH}")
    try:
        import duckdb  # noqa: F401
    except ImportError:
        return pytest.mark.skip(reason="duckdb package not installed")
    return pytest.mark.parity


@pytest.fixture
async def pool_factory(settings: Settings) -> AsyncIterator[DbPoolFactory]:
    factory = DbPoolFactory(settings)
    await factory.open()
    try:
        yield factory
    finally:
        await factory.close()


def _ctx() -> ClinicianContext:
    return ClinicianContext.system()


async def _first_patient(pool_factory: DbPoolFactory, table: str) -> str:
    async with pool_factory.pool.connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute(f"SELECT patient_id FROM {table} LIMIT 1")
            row = await cur.fetchone()
    if row is None:
        pytest.skip(f"No rows in {table} — seed the DB.")
    return cast(str, row[0])


def _duck_query(sql: str, params: list[Any]) -> list[tuple[Any, ...]]:
    import duckdb

    con = duckdb.connect(str(_DUCKDB_PATH), read_only=True)
    try:
        return con.execute(sql, params).fetchall()
    finally:
        con.close()


# ── Parity assertions per domain ─────────────────────────────────────


@_requires_duckdb()
@require_postgres
class TestPRSParity:
    async def test_get_patient_prs_row_count_matches(
        self, pool_factory: DbPoolFactory
    ) -> None:
        patient_id = await _first_patient(pool_factory, "patient_prs")
        repo = PRSRepository(
            pool_factory=pool_factory,
            authz=OpenAuthzPolicy(),
            provenance=ProvenanceService(),
        )
        pg_results = await repo.get_patient_prs(_ctx(), patient_id)

        duck_rows = _duck_query(
            "SELECT prs_name FROM patient_prs WHERE patient_id = ?",
            [patient_id],
        )
        assert len(pg_results) == len(duck_rows), (
            f"PRS row count drift for {patient_id!r}: "
            f"pg={len(pg_results)} duck={len(duck_rows)}"
        )
        pg_names = {r.prs_name for r in pg_results}
        duck_names = {row[0] for row in duck_rows}
        assert pg_names == duck_names


@_requires_duckdb()
@require_postgres
class TestPGXParity:
    async def test_get_patient_pgx_row_count_matches(
        self, pool_factory: DbPoolFactory
    ) -> None:
        patient_id = await _first_patient(pool_factory, "patient_pgx_status")
        repo = PGXRepository(
            pool_factory=pool_factory,
            authz=OpenAuthzPolicy(),
            provenance=ProvenanceService(),
        )
        pg_results = await repo.get_patient_pgx(_ctx(), patient_id)

        # LEFT JOIN — one row per (gene, drug) pair including nulls.
        duck_rows = _duck_query(
            """
            SELECT pps.gene, pa.drug
            FROM patient_pgx_status pps
            LEFT JOIN pgx_annotations pa
                ON pps.gene = pa.gene AND pps.phenotype = pa.phenotype
            WHERE pps.patient_id = ?
            """,
            [patient_id],
        )
        assert len(pg_results) == len(duck_rows), (
            f"PGX row count drift: pg={len(pg_results)} duck={len(duck_rows)}"
        )


@_requires_duckdb()
@require_postgres
class TestPhenotypeParity:
    async def test_disease_groups_match(self, pool_factory: DbPoolFactory) -> None:
        patient_id = await _first_patient(pool_factory, "diagnoses")
        repo = PhenotypeRepository(
            pool_factory=pool_factory,
            authz=OpenAuthzPolicy(),
            provenance=ProvenanceService(),
        )
        pg_results = await repo.get_patient_diagnoses(_ctx(), patient_id)

        duck_rows = _duck_query(
            """
            SELECT COALESCE(disease_name, term) AS d, COUNT(*)
            FROM diagnoses
            WHERE patient_id = ?
            GROUP BY COALESCE(disease_name, term)
            """,
            [patient_id],
        )
        pg_map = {r.disease_name: r.encounter_count for r in pg_results}
        duck_map = {row[0]: row[1] for row in duck_rows}
        assert pg_map == duck_map, (
            f"Phenotype grouping drift for {patient_id!r}: "
            f"pg={pg_map} duck={duck_map}"
        )


@_requires_duckdb()
@require_postgres
class TestFamilyHistoryParity:
    async def test_row_count_and_meets_threshold_match(
        self, pool_factory: DbPoolFactory
    ) -> None:
        patient_id = await _first_patient(pool_factory, "patient_kinship_history")
        repo = FamilyHistoryRepository(
            pool_factory=pool_factory,
            authz=OpenAuthzPolicy(),
            provenance=ProvenanceService(),
        )
        pg_results = await repo.get_patient_family_history(_ctx(), patient_id)

        duck_rows = _duck_query(
            """
            SELECT disease_name, criteria_name, meets_threshold
            FROM patient_kinship_history
            WHERE patient_id = ?
            ORDER BY disease_name, criteria_name
            """,
            [patient_id],
        )
        assert len(pg_results) == len(duck_rows)
        pg_triples = [
            (r.disease_name, r.criteria_name, r.meets_threshold) for r in pg_results
        ]
        duck_triples = [(row[0], row[1], bool(row[2])) for row in duck_rows]
        assert sorted(pg_triples) == sorted(duck_triples)


@_requires_duckdb()
@require_postgres
class TestGenomicVariantsParity:
    async def test_variant_ids_match(self, pool_factory: DbPoolFactory) -> None:
        patient_id = await _first_patient(pool_factory, "patient_variants")
        repo = GenomicVariantsRepository(
            pool_factory=pool_factory,
            authz=OpenAuthzPolicy(),
            provenance=ProvenanceService(),
        )
        pg_results = await repo.get_patient_genomic_variants(_ctx(), patient_id)

        duck_rows = _duck_query(
            "SELECT variant_id FROM patient_variants WHERE patient_id = ?",
            [patient_id],
        )
        pg_ids = {r.variant_id for r in pg_results}
        duck_ids = {row[0] for row in duck_rows}
        assert pg_ids == duck_ids
