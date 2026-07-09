"""PRS result models — port of the LangGraph prototype's PRS schemas.

Prototype reference: ``agents/prs/state/schemas.py``.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, field_validator

from egp_maf.state.provenance import DBProvenance


class PRSKey(BaseModel):
    """Minimal patient-scoped PRS key returned by ``explore_patient_prs``."""

    prs_name: str
    disease_name: str
    risk_band: str | None = None

    model_config = ConfigDict(extra="forbid")


class PRSAnnotation(BaseModel):
    """One row of the ``prs_annotations`` reference table.

    Returned by ``search_prs_annotations``. No provenance — reference-only
    data (Discovery §5.7).
    """

    prs_name: str
    disease_name: str
    source: str | None = None
    notes: str | None = None

    model_config = ConfigDict(extra="forbid")


class PRSResult(BaseModel):
    """Full PRS result for one disease/trait, JOINed from patient_prs + prs_annotations.

    LLM-derived fields (``risk_band``, ``interpretation``, ``interpretation_model``)
    are populated by the specialist agent in W05. Repository leaves them ``None``
    on read.

    Note that ``risk_band`` is dual-sourced: the DB stores a value at
    ``patient_prs.risk_band`` which the Repository populates. The specialist
    may override or re-derive it from ``percentile``. Both are legitimate —
    the DB value is the ground truth at read time.
    """

    # ── Identifiers ─────────────────────────────────────────────────
    prs_name: str
    disease_name: str

    # ── DB-sourced (patient_prs) ────────────────────────────────────
    prs_score: float
    percentile: int | None = Field(default=None, ge=0, le=100)
    risk_band: str | None = None

    # ── DB-sourced (prs_annotations, LEFT JOIN) ─────────────────────
    source: str | None = None
    metadata_notes: str | None = None

    # ── LLM-derived (populated by specialist in W05) ────────────────
    interpretation: str | None = None
    interpretation_model: str | None = None

    # ── Provenance ──────────────────────────────────────────────────
    provenance: list[DBProvenance] = Field(default_factory=list)

    model_config = ConfigDict(extra="forbid")

    @field_validator("risk_band")
    @classmethod
    def _validate_risk_band(cls, v: str | None) -> str | None:
        allowed = {"low", "average", "high", "very_high"}
        if v is not None and v not in allowed:
            raise ValueError(f"risk_band must be one of {allowed}, got {v!r}")
        return v


class PRSResultList(BaseModel):
    """Collection of PRS results plus LLM-derived summary.

    Repository does not construct this — specialists in W05 do, after adding
    the summary and any interpretations. Repository returns
    ``list[PRSResult]``.
    """

    results: list[PRSResult] = Field(default_factory=list)
    summary: str | None = None
    summary_model: str | None = None

    model_config = ConfigDict(extra="forbid")

    @classmethod
    def from_results(cls, results: list[PRSResult]) -> "PRSResultList":
        """Factory used by specialists when wrapping repository output."""
        return cls(results=list(results))
