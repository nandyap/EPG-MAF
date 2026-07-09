"""Deterministic :class:`SpecialistRegistry` used by the mode-parity
harness (:mod:`tests.mode_parity.test_mode_parity`).

The rule: every specialist stub returns the **same** typed result
regardless of which iteration or dispatch mode invoked it. That's how
we prove the harness — if the two modes produce differing outputs it
must be a workflow-topology / reducer / merge bug, not an LLM
non-determinism artefact.

We reuse the real :class:`SpecialistBase` template + concrete
:class:`PRSSpecialist` etc. from :mod:`egp_maf.agents`; only the
:class:`SpecialistLlm` bridge is stubbed. That means the derived-field
logic, provenance attachment, family-history privacy strip — every
domain-specific detail — is exercised by the harness.
"""

from __future__ import annotations

from unittest.mock import MagicMock

from egp_maf.agents.base import SpecialistReactResult, ToolCall
from egp_maf.agents.family_history import FamilyHistorySpecialist
from egp_maf.agents.genomic_variants import GenomicVariantsSpecialist
from egp_maf.agents.llm_bridge import StubSpecialistLlm
from egp_maf.agents.pgx import PGXSpecialist
from egp_maf.agents.phenotype import PhenotypeSpecialist
from egp_maf.agents.prs import PRSSpecialist
from egp_maf.agents.registry import SpecialistRegistry
from egp_maf.services.provenance import ProvenanceService
from egp_maf.state.results.family_history import (
    FamilyHistoryCriteriaResult,
    FamilyHistoryResultList,
)
from egp_maf.state.results.genomic_variants import (
    GenomicVariantResult,
    GenomicVariantsResultList,
    VariantCoreAnnotations,
    VariantExtendedAnnotations,
    VariantSampleData,
)
from egp_maf.state.results.pgx import PGXDrugResult, PGXResultList
from egp_maf.state.results.phenotype import (
    PhenotypeDiseaseResult,
    PhenotypeResultList,
)
from egp_maf.state.results.prs import PRSResult, PRSResultList

# ── Canned typed results per specialist ──────────────────────────────

_PRS = PRSResultList(
    results=[
        PRSResult(
            prs_name="PRS_CAD_001",
            disease_name="Coronary Artery Disease",
            prs_score=1.4,
            percentile=82,
            risk_band="high",
            interpretation="82nd percentile CAD PRS — elevated.",
        )
    ],
    summary="Overall polygenic risk is elevated for CAD.",
)

_GENOMIC = GenomicVariantsResultList(
    patient_id="",  # specialist overrides
    results=[
        GenomicVariantResult(
            variant_id="rs123",
            sample_data=VariantSampleData(genotype="0/1"),
            core_annotations=VariantCoreAnnotations(
                gene="BRCA1", pathogenicity="Pathogenic"
            ),
            extended_annotations=VariantExtendedAnnotations(),
            interpretation="BRCA1 pathogenic variant.",
        )
    ],
    pathogenic_count=0,  # specialist recomputes
)

_FH = FamilyHistoryResultList(
    patient_id="",
    results=[
        FamilyHistoryCriteriaResult(
            disease_name="Breast Cancer",
            criteria_name="NCCN HBOC",
            affected_relative_count=2,
            total_relatives_searched=6,
            search_context_notes="0 eligible females over 30 in search",
            meets_threshold=True,
            interpretation="Meets NCCN HBOC threshold.",
        )
    ],
)

_PGX = PGXResultList(
    patient_id="",
    results=[
        PGXDrugResult(
            gene="CYP2D6",
            drug="codeine",
            diplotype="*4/*4",
            phenotype="Poor Metabolizer",
            recommendation="Avoid codeine.",
            interpretation="Poor metaboliser — avoid codeine.",
        )
    ],
)

_PHENO = PhenotypeResultList(
    patient_id="",
    results=[
        PhenotypeDiseaseResult(
            disease_name="Type 2 diabetes",
            encounter_count=5,
            relevant_to_query=True,
            interpretation="Chronic T2D — relevant to query.",
        )
    ],
)

# ── Canned tool traces (so provenance matcher has something to match) ─

_PRS_TOOL_CALLS = [
    ToolCall(
        tool_name="get_patient_prs",
        tool_parameters={"patient_id": "P1"},
        tool_output=[
            {
                "prs_name": "PRS_CAD_001",
                "disease_name": "Coronary Artery Disease",
                "prs_score": 1.4,
                "percentile": 82,
                "risk_band": "high",
                "source": "PGS-1234",
                "metadata_notes": "n/a",
            }
        ],
    )
]

_GENOMIC_TOOL_CALLS = [
    ToolCall(
        tool_name="get_patient_genomic_variants",
        tool_parameters={"patient_id": "P1"},
        tool_output=[{"variant_id": "rs123", "gene": "BRCA1"}],
    )
]

_FH_TOOL_CALLS = [
    ToolCall(
        tool_name="get_patient_family_history",
        tool_parameters={"patient_id": "P1"},
        tool_output=[
            {"disease_name": "Breast Cancer", "criteria_name": "NCCN HBOC"}
        ],
    )
]

_PGX_TOOL_CALLS = [
    ToolCall(
        tool_name="get_patient_pgx",
        tool_parameters={"patient_id": "P1"},
        tool_output=[{"gene": "CYP2D6", "drug": "codeine"}],
    )
]

_PHENO_TOOL_CALLS = [
    ToolCall(
        tool_name="get_patient_diagnoses",
        tool_parameters={"patient_id": "P1"},
        tool_output=[{"disease_name": "Type 2 diabetes"}],
    )
]


def build_deterministic_registry() -> SpecialistRegistry:
    """Return a :class:`SpecialistRegistry` where every specialist stubs
    the same typed output regardless of dispatch order or mode.

    The registry uses the **real** :class:`SpecialistBase` subclasses,
    so provenance construction, derived-field computation and the
    family-history privacy strip all execute as they would in
    production. Only the LLM adapter is stubbed.
    """
    provenance = ProvenanceService()
    registry = SpecialistRegistry()

    registry.specialists["prs"] = PRSSpecialist(
        system_prompt="", interpretation_model_name="stub-model",
        repository=MagicMock(), provenance_service=provenance,
    )
    registry.specialists["genomic_variants"] = GenomicVariantsSpecialist(
        system_prompt="", interpretation_model_name="stub-model",
        repository=MagicMock(), provenance_service=provenance,
    )
    registry.specialists["family_history"] = FamilyHistorySpecialist(
        system_prompt="", interpretation_model_name="stub-model",
        repository=MagicMock(), provenance_service=provenance,
    )
    registry.specialists["pgx"] = PGXSpecialist(
        system_prompt="", interpretation_model_name="stub-model",
        repository=MagicMock(), provenance_service=provenance,
    )
    registry.specialists["phenotype"] = PhenotypeSpecialist(
        system_prompt="", interpretation_model_name="stub-model",
        repository=MagicMock(), provenance_service=provenance,
    )

    def _stub(react: SpecialistReactResult, extraction: object) -> StubSpecialistLlm:
        return StubSpecialistLlm(react_result=react, extraction_result=extraction)

    registry.llms["prs"] = _stub(
        SpecialistReactResult(transcript=[], tool_calls=_PRS_TOOL_CALLS),
        _PRS.model_copy(deep=True),
    )
    registry.llms["genomic_variants"] = _stub(
        SpecialistReactResult(transcript=[], tool_calls=_GENOMIC_TOOL_CALLS),
        _GENOMIC.model_copy(deep=True),
    )
    registry.llms["family_history"] = _stub(
        SpecialistReactResult(transcript=[], tool_calls=_FH_TOOL_CALLS),
        _FH.model_copy(deep=True),
    )
    registry.llms["pgx"] = _stub(
        SpecialistReactResult(transcript=[], tool_calls=_PGX_TOOL_CALLS),
        _PGX.model_copy(deep=True),
    )
    registry.llms["phenotype"] = _stub(
        SpecialistReactResult(transcript=[], tool_calls=_PHENO_TOOL_CALLS),
        _PHENO.model_copy(deep=True),
    )

    return registry
