from __future__ import annotations
from typing import List, Optional
from pydantic import BaseModel, Field

from agents.shared.state.provenance import DBProvenance


class PGXDrugResult(BaseModel):
    """
    A single pharmacogenomics result for one gene-drug pair.

    Combines patient diplotype/phenotype data (patient_pgx_status) with
    drug recommendation annotations (pgx_annotations).

    One patient may have multiple results per gene — one per drug that
    has a CPIC guideline for their phenotype at that gene.
    """

    # ── Identifiers ────────────────────────────────────────────────
    gene: str = Field(..., description="Gene assessed. e.g. 'CYP2D6'.")
    drug: str = Field(..., description="Drug for which the recommendation applies. e.g. 'codeine'.")

    # ── Patient data — from patient_pgx_status ─────────────────────
    diplotype: Optional[str] = Field(
        None, description="Patient's diplotype for this gene. e.g. '*1/*2'."
    )
    phenotype: Optional[str] = Field(
        None, description="Patient's metabolizer phenotype. e.g. 'Poor Metabolizer'."
    )

    # ── Annotation — from pgx_annotations JOIN ─────────────────────
    recommendation: Optional[str] = Field(
        None, description="CPIC-sourced clinical recommendation for this drug-gene pair."
    )
    summary: Optional[str] = Field(
        None, description="Brief summary of the recommendation."
    )
    source: Optional[str] = Field(
        None, description="Source of the CPIC guideline for this drug-gene pair."
    )

    # ── LLM-generated ──────────────────────────────────────────────
    interpretation: Optional[str] = Field(
        None,
        description=(
            "Clinical interpretation of what the patient's phenotype means for this drug "
            "and what action the recommendation implies."
        ),
    )
    interpretation_model: Optional[str] = Field(
        None, description="LLM that generated the interpretation."
    )

    # ── Provenance ─────────────────────────────────────────────────
    provenance: List[DBProvenance] = Field(
        default_factory=list,
        description="One provenance record per DB table touched to build this result.",
    )


class PGXResultList(BaseModel):
    """Top-level output schema of the PGX agent."""

    patient_id: str
    results: List[PGXDrugResult] = Field(default_factory=list)
    genes_assessed: List[str] = Field(
        default_factory=list,
        description="Unique genes assessed for this patient. Computed programmatically.",
    )
    drugs_with_recommendations: List[str] = Field(
        default_factory=list,
        description=(
            "Drugs for which a non-null recommendation was found. "
            "Computed programmatically."
        ),
    )
    summary: Optional[str] = None
    summary_model: Optional[str] = None


class PGXKey(BaseModel):
    """
    Minimal patient-scoped PGX key returned by explore_patient_pgx.
    One row per gene assessed for this patient.
    """
    gene: str = Field(..., description="Gene assessed. e.g. 'CYP2D6'.")
    diplotype: Optional[str] = Field(None, description="Patient diplotype. e.g. '*1/*2'.")
    phenotype: Optional[str] = Field(None, description="Metabolizer phenotype. e.g. 'Normal Metabolizer'.")
