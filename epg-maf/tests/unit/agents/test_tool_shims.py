"""Tests for :mod:`egp_maf.agents.tool_shims`.

Each tool factory is exercised against a stubbed Repository. The point
of the shim layer is to (a) close over ``ctx`` + ``patient_id`` from the
run and (b) emit JSON-friendly rows to the ReAct pass — both are
asserted here.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from egp_maf.agents.tool_shims import (
    build_family_history_tools,
    build_genomic_variants_tools,
    build_pgx_tools,
    build_phenotype_tools,
    build_prs_tools,
)
from egp_maf.state.clinician_context import ClinicianContext
from egp_maf.state.results.family_history import (
    FamilyHistoryCriteriaResult,
    FamilyHistoryCriteriaResultPublic,
)
from egp_maf.state.results.genomic_variants import (
    GenomicVariantResult,
    VariantAnnotation,
    VariantCoreAnnotations,
    VariantExtendedAnnotations,
    VariantKey,
    VariantSampleData,
)
from egp_maf.state.results.pgx import PGXAnnotation, PGXDrugResult, PGXKey
from egp_maf.state.results.phenotype import PhenotypeDiseaseResult, PhenotypeKey
from egp_maf.state.results.prs import PRSAnnotation, PRSKey, PRSResult

pytestmark = pytest.mark.unit


_CTX = ClinicianContext.system()


async def _call(tool_obj: Any, **arguments: Any) -> list[dict[str, Any]]:
    """Invoke a MAF ``FunctionTool`` and return the raw list-of-dicts.

    MAF ``FunctionTool.invoke`` wraps the raw return in a ``Content``
    envelope by default; ``skip_parsing=True`` gives us the untouched
    Python value that the tool function produced.
    """
    return await tool_obj.invoke(arguments=arguments, skip_parsing=True)


class TestPRSToolShims:
    async def test_explore_maps_to_repo_and_returns_row_dicts(self) -> None:
        repo = MagicMock()
        repo.explore_patient_prs = AsyncMock(
            return_value=[PRSKey(prs_name="PRS_001", disease_name="CAD")]
        )
        tools = build_prs_tools(repo, _CTX, "P1")
        assert [t.name for t in tools] == [
            "explore_patient_prs",
            "search_prs_annotations",
            "get_patient_prs",
        ]
        result = await _call(tools[0])
        repo.explore_patient_prs.assert_awaited_once_with(_CTX, "P1")
        assert result[0]["prs_name"] == "PRS_001"

    async def test_search_forwards_named_filters(self) -> None:
        repo = MagicMock()
        repo.search_prs_annotations = AsyncMock(
            return_value=[
                PRSAnnotation(prs_name="PRS_001", disease_name="CAD", source="Xyz")
            ]
        )
        tools = build_prs_tools(repo, _CTX, "P1")
        await _call(tools[1], prs_name="PRS_001", disease_name="CAD")
        repo.search_prs_annotations.assert_awaited_once_with(
            _CTX, prs_name="PRS_001", disease_name="CAD"
        )

    async def test_get_binds_patient_id_from_shim_construction(self) -> None:
        repo = MagicMock()
        repo.get_patient_prs = AsyncMock(
            return_value=[
                PRSResult(
                    prs_name="PRS_001", disease_name="CAD", prs_score=1.23
                )
            ]
        )
        tools = build_prs_tools(repo, _CTX, "P1")
        rows = await _call(tools[2])
        repo.get_patient_prs.assert_awaited_once_with(
            _CTX, "P1", prs_name=None, disease_name=None
        )
        assert rows[0]["prs_score"] == 1.23


class TestGenomicVariantsToolShims:
    async def test_explore_get_search(self) -> None:
        repo = MagicMock()
        repo.explore_patient_genomic_variants = AsyncMock(
            return_value=[VariantKey(variant_id="V1", genotype="0/1")]
        )
        repo.search_variant_annotations = AsyncMock(
            return_value=[VariantAnnotation(variant_id="V1", gene="BRCA1")]
        )
        repo.get_patient_genomic_variants = AsyncMock(
            return_value=[
                GenomicVariantResult(
                    variant_id="V1",
                    sample_data=VariantSampleData(),
                    core_annotations=VariantCoreAnnotations(gene="BRCA1"),
                    extended_annotations=VariantExtendedAnnotations(),
                )
            ]
        )
        tools = build_genomic_variants_tools(repo, _CTX, "P1")
        assert len(tools) == 3
        await _call(tools[0])
        await _call(tools[1], gene="BRCA1")
        rows = await _call(tools[2], variant_type="missense")
        repo.search_variant_annotations.assert_awaited_once_with(
            _CTX,
            variant_id=None,
            gene="BRCA1",
            pathogenicity=None,
            disease_name=None,
        )
        assert rows[0]["variant_id"] == "V1"


class TestFamilyHistoryToolShims:
    async def test_get_returns_public_projection_via_shim(self) -> None:
        """The shim must call ``.to_public()`` — the ReAct LLM never
        sees the three privacy fields."""
        internal = FamilyHistoryCriteriaResult(
            disease_name="Breast Cancer",
            criteria_name="NCCN HBOC",
            affected_relative_count=2,
            total_relatives_searched=5,
            search_context_notes="0 eligible females over 30 in search",
            meets_threshold=True,
        )
        repo = MagicMock()
        repo.get_patient_family_history = AsyncMock(return_value=[internal])
        tools = build_family_history_tools(repo, _CTX, "P1")
        rows = await _call(tools[2], disease_name="Breast Cancer")
        # Public projection — private fields absent from serialisation.
        assert "affected_relative_count" not in rows[0]
        assert "search_context_notes" not in rows[0]
        assert "total_relatives_searched" not in rows[0]
        # Non-private fields still present.
        assert rows[0]["disease_name"] == "Breast Cancer"
        assert rows[0]["criteria_name"] == "NCCN HBOC"
        assert rows[0]["meets_threshold"] is True


class TestPGXToolShims:
    async def test_explore_search_get(self) -> None:
        repo = MagicMock()
        repo.explore_patient_pgx = AsyncMock(
            return_value=[PGXKey(gene="CYP2D6")]
        )
        repo.search_pgx_annotations = AsyncMock(
            return_value=[
                PGXAnnotation(gene="CYP2D6", phenotype="Normal Metabolizer", drug="codeine")
            ]
        )
        repo.get_patient_pgx = AsyncMock(
            return_value=[PGXDrugResult(gene="CYP2D6", drug="codeine")]
        )
        tools = build_pgx_tools(repo, _CTX, "P1")
        assert len(tools) == 3
        await _call(tools[2], gene="CYP2D6")
        repo.get_patient_pgx.assert_awaited_once_with(_CTX, "P1", gene="CYP2D6")


class TestPhenotypeToolShims:
    async def test_two_tool_contract(self) -> None:
        repo = MagicMock()
        repo.explore_patient_phenotype = AsyncMock(
            return_value=[PhenotypeKey(term="Chest pain", code_type="ICD-10-CM")]
        )
        repo.get_patient_diagnoses = AsyncMock(
            return_value=[
                PhenotypeDiseaseResult(
                    disease_name="Angina",
                    encounter_count=3,
                )
            ]
        )
        tools = build_phenotype_tools(repo, _CTX, "P1")
        assert [t.name for t in tools] == [
            "explore_patient_phenotype",
            "get_patient_diagnoses",
        ]
        await _call(tools[1], disease_name="Angina", search_term="chest")
        repo.get_patient_diagnoses.assert_awaited_once_with(
            _CTX, "P1", disease_name="Angina", search_term="chest"
        )
