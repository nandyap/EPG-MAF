"""Domain-specific specialist behaviour tests.

Each per-specialist test focuses on the domain-specific slice:

- **PRS**: provenance is attached on ``prs_name`` match.
- **PGX**: ``patient_id``, ``genes_assessed``, ``drugs_with_recommendations``
  derived programmatically; provenance matches on ``(gene, drug)``.
- **Phenotype**: ``patient_id`` + ``relevant_disease_names`` derived from
  the LLM's ``relevant_to_query`` flag.
- **Family history**: privacy strip applied on state-output construction;
  provenance matches on ``(disease_name, criteria_name)`` composite key.
- **Genomic variants**: ``pathogenic_count`` derived from
  ``core_annotations.pathogenicity`` (set-based match); provenance
  matches on ``variant_id``.

We share the same stub-LLM approach across all five to keep runs
deterministic and network-free.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from egp_maf.agents.base import (
    SpecialistInputs,
    SpecialistReactResult,
    ToolCall,
)
from egp_maf.agents.family_history import FamilyHistorySpecialist
from egp_maf.agents.genomic_variants import GenomicVariantsSpecialist
from egp_maf.agents.llm_bridge import StubSpecialistLlm
from egp_maf.agents.pgx import PGXSpecialist
from egp_maf.agents.phenotype import PhenotypeSpecialist
from egp_maf.agents.prs import PRSSpecialist
from egp_maf.agents.state_outputs import (
    FamilyHistoryStateOutput,
    GenomicVariantsStateOutput,
    PGXStateOutput,
    PhenotypeStateOutput,
    PRSStateOutput,
)
from egp_maf.services.provenance import ProvenanceService
from egp_maf.state.clinician_context import ClinicianContext
from egp_maf.state.results.family_history import (
    FamilyHistoryCriteriaResult,
    FamilyHistoryResultList,
    FamilyHistoryResultListPublic,
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

pytestmark = pytest.mark.unit


_CTX = ClinicianContext.system()
_INPUTS = SpecialistInputs(
    patient_id="P1", original_query="what does this show?", requested_diseases=None
)


def _stub_llm(result: object, *, tool_calls: list[ToolCall] | None = None) -> StubSpecialistLlm:
    return StubSpecialistLlm(
        react_result=SpecialistReactResult(transcript=[], tool_calls=tool_calls or []),
        extraction_result=result,
    )


# ── PRS ───────────────────────────────────────────────────────────────


class TestPRSSpecialist:
    async def test_provenance_matches_on_prs_name(self) -> None:
        specialist = PRSSpecialist(
            system_prompt="p",
            interpretation_model_name="m",
            repository=MagicMock(),
            provenance_service=ProvenanceService(),
        )
        result_list = PRSResultList(
            results=[
                PRSResult(prs_name="PRS_A", disease_name="X", prs_score=1.0),
                PRSResult(prs_name="PRS_B", disease_name="Y", prs_score=2.0),
            ]
        )
        tool_calls = [
            ToolCall(
                tool_name="get_patient_prs",
                tool_parameters={"patient_id": "P1"},
                tool_output=[
                    {"prs_name": "PRS_A", "prs_score": 1.0},
                    {"prs_name": "PRS_B", "prs_score": 2.0},
                ],
            )
        ]
        slot: PRSStateOutput = await specialist.run(  # type: ignore[assignment]
            inputs=_INPUTS, ctx=_CTX, llm=_stub_llm(result_list, tool_calls=tool_calls)
        )
        assert slot.output is not None
        assert len(slot.output.results[0].provenance) == 1
        assert slot.output.results[0].provenance[0].source_row["prs_name"] == "PRS_A"
        assert slot.output.results[1].provenance[0].source_row["prs_name"] == "PRS_B"

    async def test_no_provenance_from_explore_or_search_tools(self) -> None:
        """Only get_patient_prs is provenance-eligible."""
        specialist = PRSSpecialist(
            system_prompt="p",
            interpretation_model_name="m",
            repository=MagicMock(),
            provenance_service=ProvenanceService(),
        )
        result_list = PRSResultList(
            results=[PRSResult(prs_name="PRS_A", disease_name="X", prs_score=1.0)]
        )
        tool_calls = [
            ToolCall(
                tool_name="explore_patient_prs",
                tool_parameters={},
                tool_output=[{"prs_name": "PRS_A"}],
            ),
            ToolCall(
                tool_name="search_prs_annotations",
                tool_parameters={},
                tool_output=[{"prs_name": "PRS_A"}],
            ),
        ]
        slot: PRSStateOutput = await specialist.run(  # type: ignore[assignment]
            inputs=_INPUTS, ctx=_CTX, llm=_stub_llm(result_list, tool_calls=tool_calls)
        )
        assert slot.output is not None
        assert slot.output.results[0].provenance == []


# ── PGX ───────────────────────────────────────────────────────────────


class TestPGXSpecialist:
    async def test_derived_fields_populated_programmatically(self) -> None:
        specialist = PGXSpecialist(
            system_prompt="p",
            interpretation_model_name="m",
            repository=MagicMock(),
            provenance_service=ProvenanceService(),
        )
        result_list = PGXResultList(
            patient_id="",  # intentionally wrong — specialist overrides
            results=[
                PGXDrugResult(gene="CYP2D6", drug="codeine", recommendation="avoid"),
                PGXDrugResult(gene="CYP2D6", drug="tramadol", recommendation="reduce"),
                PGXDrugResult(gene="CYP2C19", drug="clopidogrel"),  # no rec
                PGXDrugResult(gene="TPMT"),  # no drug, no rec
            ],
        )
        slot: PGXStateOutput = await specialist.run(  # type: ignore[assignment]
            inputs=_INPUTS, ctx=_CTX, llm=_stub_llm(result_list)
        )
        assert slot.output is not None
        assert slot.output.patient_id == "P1"
        assert slot.output.genes_assessed == sorted(["CYP2D6", "CYP2C19", "TPMT"])
        # drugs_with_recommendations excludes null-recommendation rows.
        assert slot.output.drugs_with_recommendations == sorted(["codeine", "tramadol"])

    async def test_provenance_matches_on_gene_drug_composite_key(self) -> None:
        specialist = PGXSpecialist(
            system_prompt="p",
            interpretation_model_name="m",
            repository=MagicMock(),
            provenance_service=ProvenanceService(),
        )
        result_list = PGXResultList(
            patient_id="P1",
            results=[
                PGXDrugResult(gene="CYP2D6", drug="codeine"),
                PGXDrugResult(gene="CYP2D6", drug="tramadol"),
            ],
        )
        tool_calls = [
            ToolCall(
                tool_name="get_patient_pgx",
                tool_parameters={"patient_id": "P1"},
                tool_output=[
                    {"gene": "CYP2D6", "drug": "codeine", "phenotype": "PM"},
                    {"gene": "CYP2D6", "drug": "tramadol", "phenotype": "PM"},
                ],
            )
        ]
        slot: PGXStateOutput = await specialist.run(  # type: ignore[assignment]
            inputs=_INPUTS, ctx=_CTX, llm=_stub_llm(result_list, tool_calls=tool_calls)
        )
        assert slot.output is not None
        assert (
            slot.output.results[0].provenance[0].source_row["drug"] == "codeine"
        )
        assert (
            slot.output.results[1].provenance[0].source_row["drug"] == "tramadol"
        )


# ── Phenotype ────────────────────────────────────────────────────────


class TestPhenotypeSpecialist:
    async def test_relevant_disease_names_derived_from_flag(self) -> None:
        specialist = PhenotypeSpecialist(
            system_prompt="p",
            interpretation_model_name="m",
            repository=MagicMock(),
            provenance_service=ProvenanceService(),
        )
        result_list = PhenotypeResultList(
            patient_id="",
            results=[
                PhenotypeDiseaseResult(
                    disease_name="Type 2 diabetes",
                    encounter_count=5,
                    relevant_to_query=True,
                ),
                PhenotypeDiseaseResult(
                    disease_name="Migraine",
                    encounter_count=2,
                    relevant_to_query=False,
                ),
            ],
        )
        slot: PhenotypeStateOutput = await specialist.run(  # type: ignore[assignment]
            inputs=_INPUTS, ctx=_CTX, llm=_stub_llm(result_list)
        )
        assert slot.output is not None
        assert slot.output.patient_id == "P1"
        assert slot.output.relevant_disease_names == ["Type 2 diabetes"]


# ── Family history ──────────────────────────────────────────────────


class TestFamilyHistorySpecialist:
    async def test_state_output_is_public_projection_no_privacy_fields(self) -> None:
        specialist = FamilyHistorySpecialist(
            system_prompt="p",
            interpretation_model_name="m",
            repository=MagicMock(),
            provenance_service=ProvenanceService(),
        )
        result_list = FamilyHistoryResultList(
            patient_id="",
            results=[
                FamilyHistoryCriteriaResult(
                    disease_name="Breast Cancer",
                    criteria_name="NCCN HBOC",
                    affected_relative_count=2,
                    total_relatives_searched=6,
                    search_context_notes="0 eligible females over 30 in search",
                    meets_threshold=True,
                    interpretation="Meets threshold.",
                )
            ],
        )
        slot: FamilyHistoryStateOutput = await specialist.run(  # type: ignore[assignment]
            inputs=_INPUTS, ctx=_CTX, llm=_stub_llm(result_list)
        )
        assert isinstance(slot.output, FamilyHistoryResultListPublic)
        public_fields = FamilyHistoryResultListPublic.model_fields
        assert "affected_relative_count" not in public_fields
        # And also absent from the actual serialised payload:
        serialised = slot.output.model_dump()
        for r in serialised["results"]:
            assert "affected_relative_count" not in r
            assert "total_relatives_searched" not in r
            assert "search_context_notes" not in r

    async def test_diseases_meeting_threshold_derived_programmatically(self) -> None:
        specialist = FamilyHistorySpecialist(
            system_prompt="p",
            interpretation_model_name="m",
            repository=MagicMock(),
            provenance_service=ProvenanceService(),
        )
        result_list = FamilyHistoryResultList(
            patient_id="",
            results=[
                FamilyHistoryCriteriaResult(
                    disease_name="Breast Cancer",
                    criteria_name="NCCN HBOC",
                    meets_threshold=True,
                ),
                FamilyHistoryCriteriaResult(
                    disease_name="Colorectal Cancer",
                    criteria_name="Amsterdam II",
                    meets_threshold=False,
                ),
            ],
        )
        slot: FamilyHistoryStateOutput = await specialist.run(  # type: ignore[assignment]
            inputs=_INPUTS, ctx=_CTX, llm=_stub_llm(result_list)
        )
        assert slot.output is not None
        assert slot.output.diseases_meeting_threshold == ["Breast Cancer"]


# ── Genomic variants ────────────────────────────────────────────────


class TestGenomicVariantsSpecialist:
    async def test_pathogenic_count_derived_programmatically(self) -> None:
        specialist = GenomicVariantsSpecialist(
            system_prompt="p",
            interpretation_model_name="m",
            repository=MagicMock(),
            provenance_service=ProvenanceService(),
        )
        result_list = GenomicVariantsResultList(
            patient_id="",
            results=[
                GenomicVariantResult(
                    variant_id="V1",
                    sample_data=VariantSampleData(),
                    core_annotations=VariantCoreAnnotations(pathogenicity="Pathogenic"),
                    extended_annotations=VariantExtendedAnnotations(),
                ),
                GenomicVariantResult(
                    variant_id="V2",
                    sample_data=VariantSampleData(),
                    core_annotations=VariantCoreAnnotations(pathogenicity="Likely Pathogenic"),
                    extended_annotations=VariantExtendedAnnotations(),
                ),
                GenomicVariantResult(
                    variant_id="V3",
                    sample_data=VariantSampleData(),
                    core_annotations=VariantCoreAnnotations(pathogenicity="Benign"),
                    extended_annotations=VariantExtendedAnnotations(),
                ),
            ],
            pathogenic_count=0,  # will be overridden by the specialist
        )
        slot: GenomicVariantsStateOutput = await specialist.run(  # type: ignore[assignment]
            inputs=_INPUTS, ctx=_CTX, llm=_stub_llm(result_list)
        )
        assert slot.output is not None
        assert slot.output.patient_id == "P1"
        assert slot.output.pathogenic_count == 2

    async def test_provenance_matches_on_variant_id(self) -> None:
        specialist = GenomicVariantsSpecialist(
            system_prompt="p",
            interpretation_model_name="m",
            repository=MagicMock(),
            provenance_service=ProvenanceService(),
        )
        result_list = GenomicVariantsResultList(
            patient_id="P1",
            results=[
                GenomicVariantResult(
                    variant_id="V1",
                    sample_data=VariantSampleData(),
                    core_annotations=VariantCoreAnnotations(),
                    extended_annotations=VariantExtendedAnnotations(),
                )
            ],
        )
        tool_calls = [
            ToolCall(
                tool_name="get_patient_genomic_variants",
                tool_parameters={"patient_id": "P1"},
                tool_output=[{"variant_id": "V1", "gene": "BRCA1"}],
            )
        ]
        slot: GenomicVariantsStateOutput = await specialist.run(  # type: ignore[assignment]
            inputs=_INPUTS, ctx=_CTX, llm=_stub_llm(result_list, tool_calls=tool_calls)
        )
        assert slot.output is not None
        assert (
            slot.output.results[0].provenance[0].source_row["variant_id"] == "V1"
        )
