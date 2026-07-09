"""Family history result models — port with public/internal projection split.

Prototype reference: ``agents/family_history/state/schemas.py``.

Privacy split (Design ADR-017, §11.7): three fields carry aggregate
demographic completeness context that must never reach the orchestrator
or the synthesis LLM:

- ``affected_relative_count``
- ``total_relatives_searched``
- ``search_context_notes``

They are useful *inside* the specialist for qualifying interpretations
(e.g. "Threshold not met; however, 0 eligible relatives were searched …").
The Repository returns the internal projection; callers who need the
orchestrator-facing view call ``.to_public()`` on the model.

The same three keys are also stripped from every ``DBProvenance.source_row``
so audit records emitted downstream carry no privacy-sensitive fields.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from egp_maf.state.provenance import DBProvenance

# Fields stripped from both the model and the provenance source rows in
# the public projection.
_PRIVACY_STRIP_KEYS: frozenset[str] = frozenset(
    {
        "affected_relative_count",
        "total_relatives_searched",
        "search_context_notes",
    }
)


class FamilyHistoryKey(BaseModel):
    """Minimal per-patient key returned by ``explore_patient_family_history``."""

    disease_name: str
    criteria_name: str
    meets_threshold: bool

    model_config = ConfigDict(extra="forbid")


class KinshipHistoryAnnotation(BaseModel):
    """One row of ``kinship_history_annotations`` — reference data."""

    disease_name: str
    criteria_name: str
    description: str | None = None
    source: str | None = None

    model_config = ConfigDict(extra="forbid")


class FamilyHistoryCriteriaResult(BaseModel):
    """Internal projection — includes privacy-sensitive aggregate fields.

    Held inside the specialist for interpretation-qualification. Never
    written to orchestrator state, never logged in spans. Convert to
    :class:`FamilyHistoryCriteriaResultPublic` before crossing that
    boundary via :meth:`to_public`.
    """

    # ── Identifiers ─────────────────────────────────────────────────
    disease_name: str
    criteria_name: str

    # ── PRIVACY-SENSITIVE (aggregate demographic completeness) ──────
    affected_relative_count: int | None = None
    total_relatives_searched: int | None = None
    search_context_notes: str | None = None

    # ── DB-sourced (both patient_kinship_history and JOIN) ──────────
    meets_threshold: bool
    last_observed_diagnosis_in_database: str | None = None
    criteria_description: str | None = None
    criteria_source: str | None = None

    # ── LLM-derived ─────────────────────────────────────────────────
    interpretation: str | None = None
    interpretation_model: str | None = None

    # ── Provenance ──────────────────────────────────────────────────
    provenance: list[DBProvenance] = Field(default_factory=list)

    model_config = ConfigDict(extra="forbid")

    def to_public(self) -> "FamilyHistoryCriteriaResultPublic":
        """Return the orchestrator-facing projection.

        Strips the three privacy-sensitive fields from the model AND strips
        the same keys from each provenance record's ``source_row``.
        """
        stripped_provenance = [
            p.model_copy(
                update={
                    "source_row": {
                        k: v
                        for k, v in p.source_row.items()
                        if k not in _PRIVACY_STRIP_KEYS
                    }
                }
            )
            for p in self.provenance
        ]
        return FamilyHistoryCriteriaResultPublic(
            disease_name=self.disease_name,
            criteria_name=self.criteria_name,
            meets_threshold=self.meets_threshold,
            criteria_description=self.criteria_description,
            criteria_source=self.criteria_source,
            interpretation=self.interpretation,
            interpretation_model=self.interpretation_model,
            provenance=stripped_provenance,
        )


class FamilyHistoryCriteriaResultPublic(BaseModel):
    """Orchestrator-facing projection — privacy-sensitive fields absent."""

    disease_name: str
    criteria_name: str
    meets_threshold: bool
    criteria_description: str | None = None
    criteria_source: str | None = None
    interpretation: str | None = None
    interpretation_model: str | None = None
    provenance: list[DBProvenance] = Field(default_factory=list)

    model_config = ConfigDict(extra="forbid")


class FamilyHistoryResultList(BaseModel):
    """Internal collection — kept inside the specialist for audit."""

    patient_id: str
    results: list[FamilyHistoryCriteriaResult] = Field(default_factory=list)
    diseases_meeting_threshold: list[str] = Field(default_factory=list)
    summary: str | None = None
    summary_model: str | None = None

    model_config = ConfigDict(extra="forbid")

    @classmethod
    def from_results(
        cls,
        patient_id: str,
        results: list[FamilyHistoryCriteriaResult],
    ) -> "FamilyHistoryResultList":
        """Factory — computes ``diseases_meeting_threshold`` programmatically."""
        met = sorted({r.disease_name for r in results if r.meets_threshold})
        return cls(
            patient_id=patient_id,
            results=list(results),
            diseases_meeting_threshold=met,
        )

    def to_public(self) -> "FamilyHistoryResultListPublic":
        """Return the orchestrator-facing projection of the whole list."""
        return FamilyHistoryResultListPublic(
            patient_id=self.patient_id,
            results=[r.to_public() for r in self.results],
            diseases_meeting_threshold=list(self.diseases_meeting_threshold),
            summary=self.summary,
            summary_model=self.summary_model,
        )


class FamilyHistoryResultListPublic(BaseModel):
    """Public collection — safe for orchestrator state and logs."""

    patient_id: str
    results: list[FamilyHistoryCriteriaResultPublic] = Field(default_factory=list)
    diseases_meeting_threshold: list[str] = Field(default_factory=list)
    summary: str | None = None
    summary_model: str | None = None

    model_config = ConfigDict(extra="forbid")
