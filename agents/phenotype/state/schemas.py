from __future__ import annotations
from typing import List, Optional
from pydantic import BaseModel, Field

from agents.shared.state.provenance import DBProvenance


class PhenotypeDiseaseResult(BaseModel):
    """
    A collapsed result for one disease/condition group.

    Aggregates all diagnosis encounters sharing the same disease_name
    (or term, when disease_name is null) into a single record with
    encounter statistics and an LLM interpretation.

    Rows with null disease_name are grouped by term via COALESCE in the DB query.
    """

    # ── Identifiers ────────────────────────────────────────────────
    disease_name: str = Field(
        ...,
        description=(
            "Normalised disease label. Derived from diagnoses.disease_name via "
            "COALESCE(disease_name, term) in the DB query."
        ),
    )

    # ── Encounter statistics — from grouped DB query ───────────────
    encounter_count: int = Field(
        ..., description="Number of diagnosis encounters for this condition."
    )
    first_encounter_date: Optional[str] = Field(
        None, description="ISO date string of the earliest recorded encounter."
    )
    last_encounter_date: Optional[str] = Field(
        None, description="ISO date string of the most recent encounter."
    )
    codes: List[str] = Field(
        default_factory=list,
        description="Distinct diagnosis codes (ICD-10, SNOMED-CT, etc.) for this condition.",
    )
    terms: List[str] = Field(
        default_factory=list,
        description="Distinct human-readable terms associated with this condition.",
    )
    code_types: List[str] = Field(
        default_factory=list,
        description="Distinct coding systems used. e.g. ['ICD-10-CM', 'SNOMED-CT'].",
    )

    # ── LLM-generated ──────────────────────────────────────────────
    relevant_to_query: bool = Field(
        False,
        description=(
            "Whether this condition is relevant to the original user query. "
            "Determined by the LLM via semantic matching."
        ),
    )
    interpretation: Optional[str] = Field(
        None,
        description=(
            "Brief clinical interpretation of this condition in the context of "
            "the original query. Only populated when relevant_to_query is True."
        ),
    )
    interpretation_model: Optional[str] = Field(
        None, description="LLM that generated the interpretation."
    )

    # ── Provenance ─────────────────────────────────────────────────
    provenance: List[DBProvenance] = Field(
        default_factory=list,
        description="Provenance record for the grouped DB row that produced this result.",
    )


class PhenotypeResultList(BaseModel):
    """Top-level output schema of the phenotype agent."""

    patient_id: str
    results: List[PhenotypeDiseaseResult] = Field(default_factory=list)
    relevant_disease_names: List[str] = Field(
        default_factory=list,
        description=(
            "Disease names where relevant_to_query is True. "
            "Computed programmatically — not LLM-filled."
        ),
    )
    summary: Optional[str] = None
    summary_model: Optional[str] = None


class PhenotypeKey(BaseModel):
    """
    Minimal patient-scoped phenotype key returned by explore_patient_phenotype.
    One row per distinct (disease_name, term, code_type) combination for the patient.
    """
    disease_name: Optional[str] = Field(None, description="Normalised disease label. May be null for unmapped codes.")
    term: str = Field(..., description="Human-readable diagnosis term.")
    code_type: str = Field(..., description="Coding system. e.g. ICD10, SNOMED.")
