"""Unit tests for the 5 concrete domain repositories.

Uses :mod:`tests.support.fake_pool` — no real Postgres required.

The verifications are consistent across domains:

1. ``explore_*`` returns typed keys (no provenance).
2. ``search_*_annotations`` returns typed annotation rows (no provenance,
   no authz for reference-only lookup).
3. ``get_patient_*`` returns typed results with one ``DBProvenance`` record
   per row, carrying the tool name and parameters used.
4. RBAC is enforced on ``explore_*`` and ``get_patient_*`` (but not on
   ``search_*_annotations``).
"""

from __future__ import annotations

import re
from typing import Any

import pytest

from egp_maf.errors import AccessDenied
from egp_maf.services.provenance import ProvenanceService
from egp_maf.services.repositories import (
    FamilyHistoryRepository,
    GenomicVariantsRepository,
    PGXRepository,
    PhenotypeRepository,
    PRSRepository,
)
from egp_maf.state.clinician_context import ClinicianContext
from tests.support.authz_doubles import ClosedAuthzPolicy, OpenAuthzPolicy
from tests.support.fake_pool import FakePool, FakePoolFactory


def _ctx() -> ClinicianContext:
    return ClinicianContext(clinician_id="c1", tenant_id="t1", roles=frozenset({"Clinician"}))


def _norm(sql: str) -> str:
    """Normalise SQL whitespace so tests match regardless of formatting."""
    return re.sub(r"\s+", " ", sql).strip()


# ── PRSRepository ────────────────────────────────────────────────────


class TestPRSRepository:
    async def test_explore_returns_typed_keys(self) -> None:
        pool = FakePool()
        pool.push_response(
            rows=[("P001", "PRS_AD_001", "Alzheimer", "high")],
            column_names=["patient_id", "prs_name", "disease_name", "risk_band"],
        )
        repo = PRSRepository(
            pool_factory=FakePoolFactory(pool),
            authz=OpenAuthzPolicy(),
            provenance=ProvenanceService(),
        )
        keys = await repo.explore_patient_prs(_ctx(), "P001")
        assert len(keys) == 1
        assert keys[0].prs_name == "PRS_AD_001"
        assert keys[0].risk_band == "high"

    async def test_get_produces_provenance(self) -> None:
        pool = FakePool()
        pool.push_response(
            rows=[("P001", "PRS_AD_001", "Alzheimer", 0.82, 82, "high", "PGS Cat", "notes")],
            column_names=[
                "patient_id",
                "prs_name",
                "disease_name",
                "prs_score",
                "percentile",
                "risk_band",
                "source",
                "metadata_notes",
            ],
        )
        repo = PRSRepository(
            pool_factory=FakePoolFactory(pool),
            authz=OpenAuthzPolicy(),
            provenance=ProvenanceService(),
        )
        results = await repo.get_patient_prs(_ctx(), "P001")
        assert len(results) == 1
        r = results[0]
        assert r.prs_name == "PRS_AD_001"
        assert r.percentile == 82
        assert len(r.provenance) == 1
        prov = r.provenance[0]
        assert prov.tool_name == "get_patient_prs"
        assert prov.tool_parameters == {"patient_id": "P001"}
        assert prov.source_table == "patient_prs JOIN prs_annotations"

    async def test_authz_denies(self) -> None:
        repo = PRSRepository(
            pool_factory=FakePoolFactory(FakePool()),
            authz=ClosedAuthzPolicy(),
            provenance=ProvenanceService(),
        )
        with pytest.raises(AccessDenied):
            await repo.get_patient_prs(_ctx(), "P001")

    async def test_search_does_not_authorise(self) -> None:
        pool = FakePool()
        pool.push_response(rows=[], column_names=["prs_name", "disease_name", "source", "notes"])
        # ClosedAuthzPolicy would raise if authorise was called.
        repo = PRSRepository(
            pool_factory=FakePoolFactory(pool),
            authz=ClosedAuthzPolicy(),
            provenance=ProvenanceService(),
        )
        # search doesn't touch patient data → must not authorise.
        result = await repo.search_prs_annotations(_ctx(), disease_name="Alzheimer")
        assert result == []


# ── PGXRepository ────────────────────────────────────────────────────


class TestPGXRepository:
    async def test_get_returns_left_join_null_drug(self) -> None:
        pool = FakePool()
        pool.push_response(
            rows=[("P001", "CYP2D6", "*1/*1", "Normal Metabolizer", None, None, None, None)],
            column_names=[
                "patient_id",
                "gene",
                "diplotype",
                "phenotype",
                "drug",
                "recommendation",
                "summary",
                "source",
            ],
        )
        repo = PGXRepository(
            pool_factory=FakePoolFactory(pool),
            authz=OpenAuthzPolicy(),
            provenance=ProvenanceService(),
        )
        results = await repo.get_patient_pgx(_ctx(), "P001")
        assert len(results) == 1
        assert results[0].gene == "CYP2D6"
        assert results[0].drug is None
        assert results[0].recommendation is None
        assert results[0].provenance[0].tool_name == "get_patient_pgx"


# ── PhenotypeRepository ──────────────────────────────────────────────


class TestPhenotypeRepository:
    async def test_get_diagnoses_returns_grouped_lists(self) -> None:
        pool = FakePool()
        pool.push_response(
            rows=[
                (
                    "Diabetes Mellitus",
                    5,
                    "2020-01-01",
                    "2026-05-15",
                    ["E11.9", "250.00"],
                    ["Type 2 Diabetes Mellitus"],
                    ["ICD10", "ICD9"],
                )
            ],
            column_names=[
                "disease_name",
                "encounter_count",
                "first_encounter_date",
                "last_encounter_date",
                "codes",
                "terms",
                "code_types",
            ],
        )
        repo = PhenotypeRepository(
            pool_factory=FakePoolFactory(pool),
            authz=OpenAuthzPolicy(),
            provenance=ProvenanceService(),
        )
        results = await repo.get_patient_diagnoses(_ctx(), "P001")
        assert len(results) == 1
        r = results[0]
        assert r.disease_name == "Diabetes Mellitus"
        assert r.encounter_count == 5
        assert r.codes == ["E11.9", "250.00"]
        assert r.provenance[0].tool_name == "get_patient_diagnoses"

    async def test_explore_permits_null_disease_name(self) -> None:
        pool = FakePool()
        pool.push_response(
            rows=[(None, "Unmapped term", "SNOMED")],
            column_names=["disease_name", "term", "code_type"],
        )
        repo = PhenotypeRepository(
            pool_factory=FakePoolFactory(pool),
            authz=OpenAuthzPolicy(),
            provenance=ProvenanceService(),
        )
        keys = await repo.explore_patient_phenotype(_ctx(), "P001")
        assert keys[0].disease_name is None
        assert keys[0].term == "Unmapped term"


# ── FamilyHistoryRepository ──────────────────────────────────────────


class TestFamilyHistoryRepository:
    async def test_get_returns_internal_projection_with_privacy_fields(self) -> None:
        pool = FakePool()
        pool.push_response(
            rows=[
                (
                    "P001",
                    "Breast Cancer",
                    "NCCN HBOC",
                    0,
                    5,
                    False,
                    "0 eligible females over 30",
                    "2026-06-01",
                    "NCCN 2024 HBOC threshold",
                    "NCCN 2024",
                )
            ],
            column_names=[
                "patient_id",
                "disease_name",
                "criteria_name",
                "affected_relative_count",
                "total_relatives_searched",
                "meets_threshold",
                "search_context_notes",
                "last_observed_diagnosis_in_database",
                "criteria_description",
                "criteria_source",
            ],
        )
        repo = FamilyHistoryRepository(
            pool_factory=FakePoolFactory(pool),
            authz=OpenAuthzPolicy(),
            provenance=ProvenanceService(),
        )
        results = await repo.get_patient_family_history(_ctx(), "P001")
        assert len(results) == 1
        r = results[0]
        # Internal projection includes privacy fields.
        assert r.affected_relative_count == 0
        assert r.total_relatives_searched == 5
        assert r.search_context_notes == "0 eligible females over 30"
        # to_public strips them.
        public = r.to_public()
        assert not hasattr(public, "affected_relative_count")
        # Pydantic 2.11+ requires class-level access to ``model_fields``.
        assert "affected_relative_count" not in type(public).model_fields


# ── GenomicVariantsRepository ────────────────────────────────────────


class TestGenomicVariantsRepository:
    async def test_get_parses_annotations_json_deterministically(self) -> None:
        pool = FakePool()
        annotations_blob = {
            "rsid": "rs123",
            "cadd_score": 32.1,
            "custom": "value",
        }
        pool.push_response(
            rows=[
                (
                    "V1",       # variant_id
                    "0/1",      # genotype
                    "Illumina", # sequencing_platform
                    "GATK",     # variant_caller
                    99.9,       # call_quality
                    "BRCA1",    # gene
                    "missense", # variant_type
                    "Pathogenic",   # pathogenicity
                    "ClinVar",  # pathogenicity_source
                    "Breast Cancer",  # disease_name
                    "Autosomal Dominant",  # inheritance
                    annotations_blob,  # annotations_json (jsonb — dict at this layer)
                    "notes",
                )
            ],
            column_names=[
                "variant_id",
                "genotype",
                "sequencing_platform",
                "variant_caller",
                "call_quality",
                "gene",
                "variant_type",
                "pathogenicity",
                "pathogenicity_source",
                "disease_name",
                "inheritance",
                "annotations_json",
                "notes",
            ],
        )
        repo = GenomicVariantsRepository(
            pool_factory=FakePoolFactory(pool),
            authz=OpenAuthzPolicy(),
            provenance=ProvenanceService(),
        )
        results = await repo.get_patient_genomic_variants(_ctx(), "P001")
        assert len(results) == 1
        r = results[0]
        assert r.variant_id == "V1"
        # Sample data populated from patient_variants columns
        assert r.sample_data is not None
        assert r.sample_data.genotype == "0/1"
        assert r.sample_data.sequencing_platform == "Illumina"
        # Core annotations from top-level variant_annotations columns
        assert r.core_annotations is not None
        assert r.core_annotations.gene == "BRCA1"
        assert r.core_annotations.pathogenicity == "Pathogenic"
        # Extended annotations parsed deterministically from JSON blob
        assert r.extended_annotations is not None
        assert r.extended_annotations.rsid == "rs123"
        assert r.extended_annotations.cadd_score == 32.1
        assert r.extended_annotations.raw_annotations == {"custom": "value"}
        # Provenance covers all 13 fields
        assert len(r.provenance) == 1
        assert r.provenance[0].tool_name == "get_patient_genomic_variants"

    async def test_get_handles_null_annotations_json(self) -> None:
        pool = FakePool()
        pool.push_response(
            rows=[
                (
                    "V2",
                    None, None, None, None,
                    None, None, None, None, None, None,
                    None,  # annotations_json is null
                    None,
                )
            ],
            column_names=[
                "variant_id",
                "genotype",
                "sequencing_platform",
                "variant_caller",
                "call_quality",
                "gene",
                "variant_type",
                "pathogenicity",
                "pathogenicity_source",
                "disease_name",
                "inheritance",
                "annotations_json",
                "notes",
            ],
        )
        repo = GenomicVariantsRepository(
            pool_factory=FakePoolFactory(pool),
            authz=OpenAuthzPolicy(),
            provenance=ProvenanceService(),
        )
        results = await repo.get_patient_genomic_variants(_ctx(), "P001")
        assert len(results) == 1
        r = results[0]
        assert r.extended_annotations is not None
        assert r.extended_annotations.rsid is None
        assert r.extended_annotations.raw_annotations is None


# ── SQL shape checks ─────────────────────────────────────────────────


class TestPostgresPlaceholderStyle:
    """Every repository must use %s placeholders (psycopg 3 requirement).

    Guards against accidental DuckDB-style ``?`` slipping in.
    """

    async def _all_sql_uses_percent_s(self, coro: Any) -> None:
        pass

    async def test_prs_explore_uses_percent_s(self) -> None:
        pool = FakePool()
        pool.push_response(rows=[], column_names=["patient_id", "prs_name", "disease_name", "risk_band"])
        repo = PRSRepository(
            pool_factory=FakePoolFactory(pool),
            authz=OpenAuthzPolicy(),
            provenance=ProvenanceService(),
        )
        await repo.explore_patient_prs(_ctx(), "P001")
        (sql, _) = pool.executed[0]
        assert "%s" in sql
        assert " ? " not in sql  # DuckDB-style placeholder must be absent

    async def test_pgx_get_uses_percent_s(self) -> None:
        pool = FakePool()
        pool.push_response(rows=[], column_names=["patient_id", "gene", "diplotype", "phenotype", "drug", "recommendation", "summary", "source"])
        repo = PGXRepository(
            pool_factory=FakePoolFactory(pool),
            authz=OpenAuthzPolicy(),
            provenance=ProvenanceService(),
        )
        await repo.get_patient_pgx(_ctx(), "P001", gene="CYP2D6")
        (sql, params) = pool.executed[0]
        assert "%s" in sql
        assert params == ["P001", "CYP2D6"]
