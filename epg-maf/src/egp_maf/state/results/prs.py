"""PRS result models — port of the LangGraph prototype's PRS schemas.

Prototype reference: ``agents/prs/state/schemas.py``.
"""

from __future__ import annotations

from typing import ClassVar

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

    **Validation is deliberately lenient on the LLM-facing fields.** This
    model doubles as the structured-output schema for the extraction pass,
    and one unparseable field there fails the whole specialist —
    ``LlmError: LLM upstream error: ValidationError``, no PRS answer at
    all. Every value here originates from the DB row, so rejecting the turn
    buys no correctness; it only loses the interpretation. See
    :meth:`_normalise_risk_band`.
    """

    # ── Identifiers ─────────────────────────────────────────────────
    prs_name: str
    disease_name: str

    # ── DB-sourced (patient_prs) ────────────────────────────────────
    # ``prs_score`` is optional purely so an LLM that omits it during
    # extraction degrades to a missing number rather than a failed turn.
    # The Repository always supplies it.
    prs_score: float | None = None
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

    _RISK_BANDS: ClassVar[tuple[str, ...]] = (
        "low",
        "average",
        "high",
        "very_high",
    )

    @field_validator("risk_band", mode="before")
    @classmethod
    def _normalise_risk_band(cls, v: object) -> str | None:
        """Coerce common phrasings onto the controlled vocabulary.

        The JSON schema types this as a free string, so structured output
        gives the model no constraint — it naturally writes ``"very high"``
        or ``"Very High"`` where the vocabulary says ``"very_high"``. The
        previous strict validator rejected those and took the entire PRS
        result down with them.

        Anything still unrecognised becomes ``None`` rather than an error:
        the authoritative value is on the DB row, and losing a derived
        label is far cheaper than losing the answer.
        """
        if v is None:
            return None
        collapsed = " ".join(
            str(v).strip().lower().replace("-", " ").replace("_", " ").split()
        )
        canonical = collapsed.replace(" ", "_")
        if canonical in cls._RISK_BANDS:
            return canonical
        # Tolerate qualifiers such as "very high risk" / "low risk band".
        for band in cls._RISK_BANDS:
            if collapsed.startswith(band.replace("_", " ")):
                return band
        return None


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
