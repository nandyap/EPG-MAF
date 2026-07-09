"""PGX result models — port of the LangGraph prototype's PGX schemas.

Prototype reference: ``agents/pgx/state/schemas.py``.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from egp_maf.state.provenance import DBProvenance


class PGXKey(BaseModel):
    """Minimal patient-scoped PGX key returned by ``explore_patient_pgx``."""

    gene: str
    diplotype: str | None = None
    phenotype: str | None = None

    model_config = ConfigDict(extra="forbid")


class PGXAnnotation(BaseModel):
    """One row of the ``pgx_annotations`` reference table.

    Keyed by ``(gene, phenotype, drug)``. Returned by ``search_pgx_annotations``.
    """

    gene: str
    phenotype: str
    drug: str
    recommendation: str | None = None
    summary: str | None = None
    source: str | None = None

    model_config = ConfigDict(extra="forbid")


class PGXDrugResult(BaseModel):
    """Full PGX result for one gene-drug pair.

    ``get_patient_pgx`` uses ``LEFT JOIN`` on ``(gene, phenotype)`` — a
    patient's phenotype with no matching drug annotations still returns
    the gene row, with ``drug``, ``recommendation``, ``summary``,
    ``source`` all null.
    """

    # ── Identifiers ─────────────────────────────────────────────────
    gene: str
    drug: str | None = None

    # ── DB-sourced (patient_pgx_status) ─────────────────────────────
    diplotype: str | None = None
    phenotype: str | None = None

    # ── DB-sourced (pgx_annotations, LEFT JOIN) ─────────────────────
    recommendation: str | None = None
    summary: str | None = None
    source: str | None = None

    # ── LLM-derived (populated by specialist in W05) ────────────────
    interpretation: str | None = None
    interpretation_model: str | None = None

    # ── Provenance ──────────────────────────────────────────────────
    provenance: list[DBProvenance] = Field(default_factory=list)

    model_config = ConfigDict(extra="forbid")


class PGXResultList(BaseModel):
    """Collection of PGX results plus programmatic + LLM summary fields."""

    patient_id: str
    results: list[PGXDrugResult] = Field(default_factory=list)
    genes_assessed: list[str] = Field(default_factory=list)
    drugs_with_recommendations: list[str] = Field(default_factory=list)
    summary: str | None = None
    summary_model: str | None = None

    model_config = ConfigDict(extra="forbid")

    @classmethod
    def from_results(
        cls,
        patient_id: str,
        results: list[PGXDrugResult],
    ) -> "PGXResultList":
        """Factory — computes programmatic fields, leaves LLM fields None."""
        genes = sorted({r.gene for r in results if r.gene})
        drugs = sorted(
            {r.drug for r in results if r.drug and r.recommendation is not None}
        )
        return cls(
            patient_id=patient_id,
            results=list(results),
            genes_assessed=genes,
            drugs_with_recommendations=drugs,
        )
