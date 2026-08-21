"""Unit tests for the typed result models under
:mod:`egp_maf.state.results`.

The JSON parser has its own file (``test_variant_parser.py``) since it has
many edge cases; the family-history strip logic has ``test_family_history_strip.py``.
This module covers the plain result models + their factory methods.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from egp_maf.state.results import (
    GenomicVariantResult,
    GenomicVariantsResultList,
    PGXAnnotation,
    PGXDrugResult,
    PGXKey,
    PGXResultList,
    PhenotypeDiseaseResult,
    PhenotypeKey,
    PhenotypeResultList,
    PRSAnnotation,
    PRSKey,
    PRSResult,
    PRSResultList,
    VariantCoreAnnotations,
    VariantKey,
    VariantSampleData,
)


# ── PRS ──────────────────────────────────────────────────────────────


class TestPRSResult:
    def test_valid_risk_band_accepted(self) -> None:
        r = PRSResult(prs_name="X", disease_name="Y", prs_score=0.5, risk_band="high")
        assert r.risk_band == "high"

    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("very high", "very_high"),
            ("Very High", "very_high"),
            ("VERY_HIGH", "very_high"),
            ("very-high", "very_high"),
            ("  high  ", "high"),
            ("very high risk", "very_high"),
            ("low risk band", "low"),
        ],
    )
    def test_risk_band_phrasings_are_normalised(
        self, raw: str, expected: str
    ) -> None:
        """This model doubles as the structured-output schema, and the JSON
        schema types ``risk_band`` as a free string — so the LLM writes
        ``"very high"`` where the vocabulary says ``"very_high"``. Rejecting
        those failed the whole PRS specialist with
        ``LlmError: ... ValidationError``.
        """
        r = PRSResult(
            prs_name="X", disease_name="Y", prs_score=0.5, risk_band=raw
        )

        assert r.risk_band == expected

    def test_unrecognised_risk_band_degrades_to_none(self) -> None:
        """The DB row is the source of truth, so dropping a bad derived
        label is far cheaper than losing the answer."""
        r = PRSResult(
            prs_name="X",
            disease_name="Y",
            prs_score=0.5,
            risk_band="not-a-band",
        )

        assert r.risk_band is None

    def test_missing_prs_score_is_tolerated(self) -> None:
        """An LLM omitting the score should cost the number, not the turn."""
        r = PRSResult(prs_name="X", disease_name="Y")

        assert r.prs_score is None

    def test_percentile_bounds(self) -> None:
        with pytest.raises(ValidationError):
            PRSResult(prs_name="X", disease_name="Y", prs_score=0.5, percentile=101)

    def test_extra_fields_rejected(self) -> None:
        with pytest.raises(ValidationError):
            PRSResult(
                prs_name="X",
                disease_name="Y",
                prs_score=0.5,
                unexpected="boom",  # type: ignore[call-arg]
            )

    def test_llm_fields_default_none(self) -> None:
        r = PRSResult(prs_name="X", disease_name="Y", prs_score=0.5)
        assert r.interpretation is None
        assert r.interpretation_model is None


class TestPRSKeyAndAnnotation:
    def test_key(self) -> None:
        k = PRSKey(prs_name="X", disease_name="Y", risk_band="low")
        assert k.risk_band == "low"

    def test_annotation(self) -> None:
        a = PRSAnnotation(prs_name="X", disease_name="Y", source="PGS", notes="n")
        assert a.source == "PGS"

    def test_result_list_factory(self) -> None:
        r = PRSResult(prs_name="X", disease_name="Y", prs_score=0.5)
        lst = PRSResultList.from_results([r])
        assert lst.results == [r]
        assert lst.summary is None


# ── PGX ──────────────────────────────────────────────────────────────


class TestPGXResultList:
    def test_from_results_computes_derived_fields(self) -> None:
        r1 = PGXDrugResult(
            gene="CYP2D6",
            drug="codeine",
            phenotype="Poor Metabolizer",
            recommendation="Avoid",
        )
        r2 = PGXDrugResult(
            gene="CYP2C19",
            drug="clopidogrel",
            phenotype="Rapid Metabolizer",
            recommendation="Alternative agent",
        )
        r3 = PGXDrugResult(
            gene="TPMT",
            drug=None,
            phenotype="Normal Metabolizer",
            recommendation=None,
        )
        lst = PGXResultList.from_results("P001", [r1, r2, r3])
        assert lst.genes_assessed == sorted({"CYP2D6", "CYP2C19", "TPMT"})
        assert lst.drugs_with_recommendations == sorted({"codeine", "clopidogrel"})

    def test_from_results_empty(self) -> None:
        lst = PGXResultList.from_results("P001", [])
        assert lst.genes_assessed == []
        assert lst.drugs_with_recommendations == []

    def test_key_and_annotation(self) -> None:
        k = PGXKey(gene="CYP2D6", diplotype="*1/*2", phenotype="Poor Metabolizer")
        assert k.phenotype == "Poor Metabolizer"
        a = PGXAnnotation(
            gene="CYP2D6",
            phenotype="Poor Metabolizer",
            drug="codeine",
            recommendation="Avoid",
        )
        assert a.recommendation == "Avoid"


# ── Phenotype ─────────────────────────────────────────────────────────


class TestPhenotypeResults:
    def test_disease_result_minimal(self) -> None:
        r = PhenotypeDiseaseResult(disease_name="Diabetes", encounter_count=3)
        assert r.encounter_count == 3
        assert r.relevant_to_query is False
        assert r.codes == []

    def test_key_allows_null_disease_name(self) -> None:
        k = PhenotypeKey(disease_name=None, term="unmapped-term", code_type="ICD10")
        assert k.disease_name is None

    def test_result_list_factory_leaves_relevant_empty(self) -> None:
        r = PhenotypeDiseaseResult(disease_name="Diabetes", encounter_count=3)
        lst = PhenotypeResultList.from_results("P001", [r])
        # relevant_disease_names depends on LLM-populated relevant_to_query,
        # so the factory intentionally does not populate it.
        assert lst.relevant_disease_names == []


# ── Genomic variants ─────────────────────────────────────────────────


class TestVariantSampleData:
    def test_all_optional(self) -> None:
        s = VariantSampleData()
        assert s.genotype is None
        assert s.call_quality is None


class TestVariantCoreAnnotations:
    def test_known_values_accepted(self) -> None:
        core = VariantCoreAnnotations(
            gene="BRCA1",
            variant_type="missense",
            pathogenicity="Pathogenic",
        )
        assert core.gene == "BRCA1"

    def test_unknown_pathogenicity_is_soft(self, caplog: pytest.LogCaptureFixture) -> None:
        # Should not raise — soft warning only.
        VariantCoreAnnotations(pathogenicity="Definitely Bad")

    def test_unknown_variant_type_is_soft(self) -> None:
        VariantCoreAnnotations(variant_type="mystery")


class TestGenomicVariantsResultList:
    def test_pathogenic_count_from_results(self) -> None:
        results = [
            GenomicVariantResult(
                variant_id="V1",
                core_annotations=VariantCoreAnnotations(pathogenicity="Pathogenic"),
            ),
            GenomicVariantResult(
                variant_id="V2",
                core_annotations=VariantCoreAnnotations(
                    pathogenicity="Likely Pathogenic"
                ),
            ),
            GenomicVariantResult(
                variant_id="V3",
                core_annotations=VariantCoreAnnotations(pathogenicity="Benign"),
            ),
            GenomicVariantResult(
                variant_id="V4",
                core_annotations=None,
            ),
        ]
        lst = GenomicVariantsResultList.from_results("P001", results)
        assert lst.pathogenic_count == 2

    def test_variant_key(self) -> None:
        k = VariantKey(variant_id="V1", genotype="0/1")
        assert k.genotype == "0/1"
