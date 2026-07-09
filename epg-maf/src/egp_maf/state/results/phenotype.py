"""Phenotype result models — port of the LangGraph prototype's schemas.

Prototype reference: ``agents/phenotype/state/schemas.py``.

Phenotype is the only 2-tool domain (no annotation table exists for
diagnoses). ``PhenotypeKey`` is the ``explore`` output;
``PhenotypeDiseaseResult`` is the ``get`` output.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from egp_maf.state.provenance import DBProvenance


class PhenotypeKey(BaseModel):
    """Minimal per-patient phenotype key returned by ``explore_patient_phenotype``.

    One row per distinct ``(disease_name, term, code_type)`` combination.
    ``disease_name`` may be null for diagnoses without a normalised mapping.
    """

    disease_name: str | None = None
    term: str
    code_type: str

    model_config = ConfigDict(extra="forbid")


class PhenotypeDiseaseResult(BaseModel):
    """Grouped result for one disease/condition.

    Encounter statistics are aggregated in SQL (COUNT / MIN / MAX / array_agg
    DISTINCT). Repository populates every DB-sourced field. LLM populates
    ``relevant_to_query``, ``interpretation``, ``interpretation_model``.
    """

    # ── Identifiers ─────────────────────────────────────────────────
    disease_name: str

    # ── DB-sourced (diagnoses, grouped) ─────────────────────────────
    encounter_count: int
    first_encounter_date: str | None = None
    last_encounter_date: str | None = None
    codes: list[str] = Field(default_factory=list)
    terms: list[str] = Field(default_factory=list)
    code_types: list[str] = Field(default_factory=list)

    # ── LLM-derived (populated by specialist in W05) ────────────────
    relevant_to_query: bool = False
    interpretation: str | None = None
    interpretation_model: str | None = None

    # ── Provenance ──────────────────────────────────────────────────
    provenance: list[DBProvenance] = Field(default_factory=list)

    model_config = ConfigDict(extra="forbid")


class PhenotypeResultList(BaseModel):
    """Collection of phenotype disease results.

    ``relevant_disease_names`` depends on ``relevant_to_query`` which is
    LLM-derived, so it's populated by the specialist after the LLM pass —
    not by the Repository.
    """

    patient_id: str
    results: list[PhenotypeDiseaseResult] = Field(default_factory=list)
    relevant_disease_names: list[str] = Field(default_factory=list)
    summary: str | None = None
    summary_model: str | None = None

    model_config = ConfigDict(extra="forbid")

    @classmethod
    def from_results(
        cls,
        patient_id: str,
        results: list[PhenotypeDiseaseResult],
    ) -> "PhenotypeResultList":
        """Factory — leaves ``relevant_disease_names`` empty (LLM-dependent)."""
        return cls(patient_id=patient_id, results=list(results))
