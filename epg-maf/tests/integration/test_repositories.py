"""Integration tests for the 5 domain repositories against a real Postgres.

Requires the seeded Postgres described in ``epg-maf/db/README.md``. Set
``EGP_TEST_POSTGRES=1`` to enable.

One test class per repository. Each class:

- Picks a patient known to have data via a discovery query.
- Runs ``explore``, ``search`` (if applicable), and ``get`` methods.
- Asserts non-empty typed results.
- Asserts provenance is attached to ``get_*`` results only.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path
from typing import cast

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


def _ctx() -> ClinicianContext:
    return ClinicianContext.system()


@pytest.fixture
async def pool_factory(settings: Settings) -> AsyncIterator[DbPoolFactory]:
    factory = DbPoolFactory(settings)
    await factory.open()
    try:
        yield factory
    finally:
        await factory.close()


async def _first_patient(pool_factory: DbPoolFactory, table: str) -> str:
    """Return a patient_id known to have rows in ``table``."""
    async with pool_factory.pool.connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute(f"SELECT patient_id FROM {table} LIMIT 1")
            row = await cur.fetchone()
    if row is None:
        pytest.skip(f"No rows in {table} — seed the DB first (db/seed/README.md).")
    return cast(str, row[0])


@require_postgres
class TestPRSRepositoryIntegration:
    async def test_explore_and_get(self, pool_factory: DbPoolFactory) -> None:
        patient_id = await _first_patient(pool_factory, "patient_prs")
        repo = PRSRepository(
            pool_factory=pool_factory,
            authz=OpenAuthzPolicy(),
            provenance=ProvenanceService(),
        )

        keys = await repo.explore_patient_prs(_ctx(), patient_id)
        assert keys, "explore_patient_prs returned no keys"

        results = await repo.get_patient_prs(_ctx(), patient_id)
        assert results, "get_patient_prs returned no results"
        for r in results:
            assert r.prs_score is not None
            assert len(r.provenance) == 1
            assert r.provenance[0].tool_name == "get_patient_prs"

    async def test_search_returns_annotations(self, pool_factory: DbPoolFactory) -> None:
        repo = PRSRepository(
            pool_factory=pool_factory,
            authz=OpenAuthzPolicy(),
            provenance=ProvenanceService(),
        )
        anns = await repo.search_prs_annotations(_ctx())
        assert anns, "expected non-empty prs_annotations"


@require_postgres
class TestPGXRepositoryIntegration:
    async def test_explore_and_get(self, pool_factory: DbPoolFactory) -> None:
        patient_id = await _first_patient(pool_factory, "patient_pgx_status")
        repo = PGXRepository(
            pool_factory=pool_factory,
            authz=OpenAuthzPolicy(),
            provenance=ProvenanceService(),
        )
        keys = await repo.explore_patient_pgx(_ctx(), patient_id)
        assert keys
        results = await repo.get_patient_pgx(_ctx(), patient_id)
        assert results
        for r in results:
            assert r.gene is not None
            assert len(r.provenance) == 1


@require_postgres
class TestPhenotypeRepositoryIntegration:
    async def test_explore_and_get(self, pool_factory: DbPoolFactory) -> None:
        patient_id = await _first_patient(pool_factory, "diagnoses")
        repo = PhenotypeRepository(
            pool_factory=pool_factory,
            authz=OpenAuthzPolicy(),
            provenance=ProvenanceService(),
        )
        keys = await repo.explore_patient_phenotype(_ctx(), patient_id)
        assert keys
        results = await repo.get_patient_diagnoses(_ctx(), patient_id)
        assert results
        for r in results:
            assert r.encounter_count >= 1
            assert isinstance(r.codes, list)
            assert isinstance(r.terms, list)
            assert len(r.provenance) == 1


@require_postgres
class TestFamilyHistoryRepositoryIntegration:
    async def test_explore_get_and_public_projection(
        self, pool_factory: DbPoolFactory
    ) -> None:
        patient_id = await _first_patient(pool_factory, "patient_kinship_history")
        repo = FamilyHistoryRepository(
            pool_factory=pool_factory,
            authz=OpenAuthzPolicy(),
            provenance=ProvenanceService(),
        )
        keys = await repo.explore_patient_family_history(_ctx(), patient_id)
        assert keys

        internal = await repo.get_patient_family_history(_ctx(), patient_id)
        assert internal
        # Public projection must strip privacy fields — spot check the first.
        public = internal[0].to_public()
        assert "affected_relative_count" not in public.model_fields
        assert "search_context_notes" not in public.model_fields
        for prov in public.provenance:
            assert "affected_relative_count" not in prov.source_row
            assert "search_context_notes" not in prov.source_row


@require_postgres
class TestGenomicVariantsRepositoryIntegration:
    async def test_explore_and_get_with_json_parse(
        self, pool_factory: DbPoolFactory
    ) -> None:
        patient_id = await _first_patient(pool_factory, "patient_variants")
        repo = GenomicVariantsRepository(
            pool_factory=pool_factory,
            authz=OpenAuthzPolicy(),
            provenance=ProvenanceService(),
        )
        keys = await repo.explore_patient_genomic_variants(_ctx(), patient_id)
        assert keys

        results = await repo.get_patient_genomic_variants(_ctx(), patient_id)
        assert results
        # Deterministic JSON parse never returns None for extended_annotations
        # (it returns an empty model at worst).
        for r in results:
            assert r.extended_annotations is not None
            assert r.core_annotations is not None
            assert r.sample_data is not None
            assert len(r.provenance) == 1
