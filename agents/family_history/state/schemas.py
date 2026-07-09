from __future__ import annotations
from typing import List, Optional
from pydantic import BaseModel, Field

from agents.shared.state.provenance import DBProvenance


class FamilyHistoryCriteriaResult(BaseModel):
    """
    A single family history criteria result for one disease.

    Combines patient threshold data (patient_kinship_history) with
    reference criteria annotations (kinship_history_annotations).

    search_context_notes carries an aggregate demographic completeness
    summary (e.g. "0 eligible females over 30 included in search").
    This is NOT individual PHI — it is a pre-populated summary note
    used by the agent to qualify its interpretation.
    """

    # ── Identifiers ────────────────────────────────────────────────
    disease_name: str = Field(..., description="Disease assessed. e.g. 'Breast Cancer'.")
    criteria_name: str = Field(..., description="Criteria applied. e.g. 'NCCN HBOC'.")

    # ── Threshold data — from patient_kinship_history ──────────────
    affected_relative_count: Optional[int] = Field(
        None, description="Number of affected relatives identified."
    )
    total_relatives_searched: Optional[int] = Field(
        None, description="Total relatives included in this criteria evaluation."
    )
    meets_threshold: bool = Field(
        ..., description="Whether the patient meets this criteria threshold."
    )
    search_context_notes: Optional[str] = Field(
        None,
        description=(
            "Aggregate demographic completeness note. e.g. '0 eligible females over 30 "
            "included in search'. Used to qualify interpretations. Not individual PHI."
        ),
    )
    last_observed_diagnosis_in_database: Optional[str] = Field(
        None,
        description=(
            "ISO date string of the OMOP DB release used for this family history search. "
            "Indicates data currency — diagnoses after this date would not be captured."
        ),
    )

    # ── Annotation data — from kinship_history_annotations (JOIN) ──
    criteria_description: Optional[str] = Field(
        None, description="What this criteria checks for."
    )
    criteria_source: Optional[str] = Field(
        None, description="Guideline source. e.g. 'NCCN 2024'."
    )

    # ── LLM-generated ──────────────────────────────────────────────
    interpretation: Optional[str] = Field(
        None,
        description=(
            "Clinical interpretation of the threshold result. "
            "Must qualify with search_context_notes when the search was incomplete."
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


class FamilyHistoryResultList(BaseModel):
    """Top-level output schema of the family history agent."""
    patient_id: str
    results: List[FamilyHistoryCriteriaResult] = Field(default_factory=list)
    diseases_meeting_threshold: List[str] = Field(
        default_factory=list,
        description="Diseases where at least one criteria threshold is met. Computed programmatically.",
    )
    summary: Optional[str] = None
    summary_model: Optional[str] = None


# ── Public (orchestrator-facing) types ─────────────────────────────────
# Fields that are aggregate search-context data or structural criteria
# details are omitted entirely — they never reach the orchestrator or
# report agent. Criteria context is captured in criteria_description and
# in the interpretation text produced by the agent.

class FamilyHistoryCriteriaResultPublic(BaseModel):
    """
    Orchestrator-facing result. Omits privacy-sensitive aggregate fields
    and structural threshold details that are not needed downstream.
    """
    disease_name: str
    criteria_name: str
    meets_threshold: bool
    criteria_description: Optional[str] = None
    criteria_source: Optional[str] = None
    interpretation: Optional[str] = None
    interpretation_model: Optional[str] = None
    provenance: List[DBProvenance] = Field(default_factory=list)


class FamilyHistoryResultListPublic(BaseModel):
    """Orchestrator-facing result list using the public result type."""
    patient_id: str
    results: List[FamilyHistoryCriteriaResultPublic] = Field(default_factory=list)
    diseases_meeting_threshold: List[str] = Field(default_factory=list)
    summary: Optional[str] = None
    summary_model: Optional[str] = None


class FamilyHistoryKey(BaseModel):
    """
    Minimal patient-scoped key returned by explore_patient_family_history.
    One row per (disease_name, criteria_name) combination for this patient.
    """
    disease_name: str = Field(..., description="Disease assessed.")
    criteria_name: str = Field(..., description="Criteria applied.")
    meets_threshold: bool = Field(..., description="Whether this patient meets the criteria threshold.")