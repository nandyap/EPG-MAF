"""PGx results are ordered by clinical actionability.

Customer report, 2026-09-14, patient HG04012: "The presentation of the
PGx results needs to be changed to have the metabolizer status and the
drug recommendation prior to others."

A PGx panel is mostly Normal Metabolizer rows. If the one Poor
Metabolizer sits fifth, the only finding that changes prescribing is
buried under five that change nothing.

Ordering is done in ``apply_derived_fields`` — deterministic Python, not
a prompt instruction — so the slot, the synthesis context, the
specialist card and the evidence panel all agree on the order.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from egp_maf.agents.pgx import PGXSpecialist
from egp_maf.services.provenance import ProvenanceService
from egp_maf.state.results.pgx import PGXDrugResult, PGXResultList

pytestmark = pytest.mark.unit


def _specialist() -> PGXSpecialist:
    return PGXSpecialist(
        system_prompt="p",
        interpretation_model_name="m",
        repository=MagicMock(),
        provenance_service=ProvenanceService(),
    )


def _ordered_genes(results: list[PGXDrugResult]) -> list[str]:
    out = _specialist().apply_derived_fields(
        PGXResultList(patient_id="P1", results=results), "P1"
    )
    return [r.gene for r in out.results]


class TestActionabilityOrdering:
    def test_non_normal_precedes_normal(self) -> None:
        """The headline case: HG04012's panel as the customer saw it."""
        genes = _ordered_genes(
            [
                PGXDrugResult(gene="CYP2C9", phenotype="Normal Metabolizer"),
                PGXDrugResult(gene="DPYD", phenotype="Normal Metabolizer"),
                PGXDrugResult(
                    gene="CYP2D6",
                    phenotype="Rapid Metabolizer",
                    drug="codeine",
                    recommendation="Avoid codeine",
                ),
                PGXDrugResult(gene="TPMT", phenotype="Normal Metabolizer"),
            ]
        )

        assert genes[0] == "CYP2D6"

    def test_full_clinical_order(self) -> None:
        genes = _ordered_genes(
            [
                PGXDrugResult(gene="NORM", phenotype="Normal Metabolizer"),
                PGXDrugResult(gene="UNK", phenotype="Unknown"),
                PGXDrugResult(gene="INT", phenotype="Intermediate Metabolizer"),
                PGXDrugResult(gene="RAP", phenotype="Rapid Metabolizer"),
                PGXDrugResult(gene="POOR", phenotype="Poor Metabolizer"),
            ]
        )

        assert genes == ["POOR", "RAP", "INT", "UNK", "NORM"]

    def test_recommendation_wins_within_a_phenotype(self) -> None:
        """The second half of the request. The LEFT JOIN leaves
        ``recommendation`` null where no annotation matched, and those
        rows have nothing to act on."""
        genes = _ordered_genes(
            [
                PGXDrugResult(gene="NO_REC", phenotype="Poor Metabolizer"),
                PGXDrugResult(
                    gene="HAS_REC",
                    phenotype="Poor Metabolizer",
                    drug="clopidogrel",
                    recommendation="Use an alternative antiplatelet",
                ),
            ]
        )

        assert genes == ["HAS_REC", "NO_REC"]

    def test_phenotype_casing_does_not_change_the_order(self) -> None:
        """``phenotype`` is re-typed by the extraction pass, not copied
        from the row, so casing varies. Exact matching would sort a Poor
        Metabolizer to the bottom — the §4d bug with a prescribing
        consequence."""
        genes = _ordered_genes(
            [
                PGXDrugResult(gene="NORM", phenotype="Normal Metabolizer"),
                PGXDrugResult(gene="POOR", phenotype="poor metabolizer"),
                PGXDrugResult(gene="RAP", phenotype="RAPID METABOLIZER"),
            ]
        )

        assert genes == ["POOR", "RAP", "NORM"]

    def test_unrecognised_phenotype_is_not_sorted_below_normal(self) -> None:
        """An unknown value is not a clean "no action indicated" and must
        not be presented as reassuringly as one."""
        genes = _ordered_genes(
            [
                PGXDrugResult(gene="NORM", phenotype="Normal Metabolizer"),
                PGXDrugResult(gene="ODD", phenotype="Indeterminate"),
                PGXDrugResult(gene="MISSING", phenotype=None),
            ]
        )

        assert genes.index("ODD") < genes.index("NORM")
        assert genes.index("MISSING") < genes.index("NORM")

    def test_equal_rank_keeps_repository_order(self) -> None:
        """``sorted`` is stable. Rows the repository returned in a
        deliberate order must not be shuffled."""
        genes = _ordered_genes(
            [
                PGXDrugResult(gene="A", phenotype="Normal Metabolizer"),
                PGXDrugResult(gene="B", phenotype="Normal Metabolizer"),
                PGXDrugResult(gene="C", phenotype="Normal Metabolizer"),
            ]
        )

        assert genes == ["A", "B", "C"]

    def test_derived_fields_still_computed(self) -> None:
        """Sorting must not disturb what this method already did."""
        out = _specialist().apply_derived_fields(
            PGXResultList(
                patient_id="",
                results=[
                    PGXDrugResult(gene="CYP2C9", phenotype="Normal Metabolizer"),
                    PGXDrugResult(
                        gene="CYP2D6",
                        phenotype="Poor Metabolizer",
                        drug="codeine",
                        recommendation="Avoid",
                    ),
                ],
            ),
            "P1",
        )

        assert out.patient_id == "P1"
        assert out.genes_assessed == ["CYP2C9", "CYP2D6"]
        assert out.drugs_with_recommendations == ["codeine"]

    def test_provenance_travels_with_its_result(self) -> None:
        """Sorting happens at step 8, after provenance is attached at
        step 6. Records are held on the result objects, so reordering the
        list cannot detach them — but this is the kind of assumption
        worth pinning."""
        specialist = _specialist()
        normal = PGXDrugResult(gene="NORM", phenotype="Normal Metabolizer")
        poor = PGXDrugResult(gene="POOR", phenotype="Poor Metabolizer")
        normal.provenance.append(MagicMock(source_row={"gene": "NORM"}))
        poor.provenance.append(MagicMock(source_row={"gene": "POOR"}))

        out = specialist.apply_derived_fields(
            PGXResultList(patient_id="P1", results=[normal, poor]), "P1"
        )

        assert out.results[0].gene == "POOR"
        assert out.results[0].provenance[0].source_row == {"gene": "POOR"}
        assert out.results[1].provenance[0].source_row == {"gene": "NORM"}
