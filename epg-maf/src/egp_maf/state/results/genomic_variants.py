"""Genomic variant result models + deterministic ``annotations_json`` parser.

Prototype reference: ``agents/genomic_variants/state/schemas.py``.

Two W03 changes vs the prototype (both design-ADR-driven):

1. Deterministic ``parse_annotations_json`` (Design ADR-006). The prototype
   asked the LLM to decompose the JSON blob into typed fields. This module
   does that in Python before the specialist's structured extraction ever
   sees the payload — removes the silent-hallucination risk.

2. ``VariantCoreAnnotations.warn_unknown_values`` uses ``structlog`` (via
   :mod:`egp_maf.logging`) with a structured event ``variant.unknown_value``
   instead of ``logging.warning``. Same behaviour, machine-parseable.
"""

from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from egp_maf.logging.setup import get_logger
from egp_maf.state.provenance import DBProvenance

_logger = get_logger(__name__)


# ── Known values (documentation only, not enforced) ──────────────────
KNOWN_PATHOGENICITY_VALUES: list[str] = [
    "Pathogenic",
    "Likely Pathogenic",
    "Variant of Uncertain Significance",
    "Likely Benign",
    "Benign",
]

KNOWN_VARIANT_TYPES: list[str] = [
    "snp",
    "indel",
    "cnv",
    "missense",
    "nonsense",
    "frameshift",
    "splice_site",
    "synonymous",
    "structural_variant",
]

# ── Keys the parser recognises inside annotations_json ───────────────
_TYPED_JSON_KEYS: frozenset[str] = frozenset(
    {
        "clinvar_id",
        "rsid",
        "hgvs_c",
        "hgvs_p",
        "gnomad_af",
        "gnomad_af_popmax",
        "sift",
        "polyphen",
        "cadd_score",
        "acmg_criteria",
    }
)


# ── Explore + reference-annotation types ─────────────────────────────


class VariantKey(BaseModel):
    """Minimal per-patient variant key returned by ``explore_patient_genomic_variants``."""

    variant_id: str
    genotype: str | None = None

    model_config = ConfigDict(extra="forbid")


class VariantAnnotation(BaseModel):
    """One row of ``variant_annotations`` — reference data.

    Includes the raw ``annotations_json`` blob. Callers that want the
    typed decomposition call :func:`parse_annotations_json` on it.
    """

    variant_id: str
    gene: str
    variant_type: str | None = None
    pathogenicity: str | None = None
    pathogenicity_source: str | None = None
    disease_name: str | None = None
    inheritance: str | None = None
    notes: str | None = None
    annotations_json: dict[str, Any] | None = None

    model_config = ConfigDict(extra="forbid")


# ── Composed result layers ───────────────────────────────────────────


class VariantSampleData(BaseModel):
    """Per-sample data from ``patient_variants``. All fields optional."""

    genotype: str | None = None
    sequencing_platform: str | None = None
    variant_caller: str | None = None
    call_quality: float | None = None

    model_config = ConfigDict(extra="forbid")


class VariantCoreAnnotations(BaseModel):
    """Top-level annotation columns from ``variant_annotations``.

    ``pathogenicity`` and ``variant_type`` are described (documentation-only
    known-value lists) but not enforced — ClinVar and pipeline vocabularies
    evolve independently of this codebase.
    """

    gene: str | None = None
    variant_type: str | None = None
    pathogenicity: str | None = None
    disease_name: str | None = None
    notes: str | None = None

    model_config = ConfigDict(extra="forbid")

    @model_validator(mode="after")
    def _warn_unknown_values(self) -> "VariantCoreAnnotations":
        """Emit a structured warning when values fall outside known lists."""
        if (
            self.pathogenicity is not None
            and self.pathogenicity not in KNOWN_PATHOGENICITY_VALUES
        ):
            _logger.warning(
                "variant.unknown_value",
                field="pathogenicity",
                value=self.pathogenicity,
            )
        if (
            self.variant_type is not None
            and self.variant_type not in KNOWN_VARIANT_TYPES
        ):
            _logger.warning(
                "variant.unknown_value",
                field="variant_type",
                value=self.variant_type,
            )
        return self


class VariantExtendedAnnotations(BaseModel):
    """Typed decomposition of the ``annotations_json`` blob.

    Known fields are promoted to typed slots; unknown keys go into
    ``raw_annotations``. Use :func:`parse_annotations_json` to construct.
    """

    clinvar_id: str | None = None
    rsid: str | None = None
    hgvs_c: str | None = None
    hgvs_p: str | None = None
    gnomad_af: float | None = None
    gnomad_af_popmax: float | None = None
    sift: str | None = None
    polyphen: str | None = None
    cadd_score: float | None = None
    acmg_criteria: list[str] | None = None
    raw_annotations: dict[str, Any] | None = None

    model_config = ConfigDict(extra="forbid")


def parse_annotations_json(
    blob: dict[str, Any] | str | None,
) -> VariantExtendedAnnotations:
    """Deterministically decompose the ``annotations_json`` value.

    Design ADR-006 — replaces the prototype's LLM-driven JSON parsing.

    Accepts three shapes:

    - ``None`` or ``""`` → returns an empty :class:`VariantExtendedAnnotations`.
    - ``str`` → parsed with :func:`json.loads`. Malformed JSON raises
      :class:`ValueError` (no silent fallback).
    - ``dict`` → used directly.

    Any key not in :data:`_TYPED_JSON_KEYS` is preserved verbatim in
    :attr:`VariantExtendedAnnotations.raw_annotations`. ``acmg_criteria``
    is coerced to a ``list[str]`` if it arrives as a single string.
    """
    if blob is None or blob == "":
        return VariantExtendedAnnotations()

    if isinstance(blob, str):
        try:
            parsed: Any = json.loads(blob)
        except json.JSONDecodeError as exc:
            raise ValueError(
                f"annotations_json is not valid JSON: {exc.msg}"
            ) from exc
        if not isinstance(parsed, dict):
            raise ValueError(
                f"annotations_json must decode to a dict, got {type(parsed).__name__}"
            )
        blob = parsed

    typed_kwargs: dict[str, Any] = {}
    raw: dict[str, Any] = {}

    for key, value in blob.items():
        if key in _TYPED_JSON_KEYS:
            if key == "acmg_criteria" and isinstance(value, str):
                # Tolerate ``"PS1"`` in addition to ``["PS1"]``.
                typed_kwargs[key] = [value]
            else:
                typed_kwargs[key] = value
        else:
            raw[key] = value

    if raw:
        typed_kwargs["raw_annotations"] = raw

    return VariantExtendedAnnotations(**typed_kwargs)


class GenomicVariantResult(BaseModel):
    """Single variant result — composes sample data, core + extended annotations."""

    variant_id: str
    sample_data: VariantSampleData | None = None
    core_annotations: VariantCoreAnnotations | None = None
    extended_annotations: VariantExtendedAnnotations | None = None

    interpretation: str | None = None
    interpretation_model: str | None = None

    provenance: list[DBProvenance] = Field(default_factory=list)

    model_config = ConfigDict(extra="forbid")


class GenomicVariantsResultList(BaseModel):
    """Collection of variant results + programmatic ``pathogenic_count``."""

    patient_id: str
    results: list[GenomicVariantResult] = Field(default_factory=list)
    pathogenic_count: int = 0
    summary: str | None = None
    summary_model: str | None = None

    model_config = ConfigDict(extra="forbid")

    @classmethod
    def from_results(
        cls,
        patient_id: str,
        results: list[GenomicVariantResult],
    ) -> "GenomicVariantsResultList":
        """Factory — computes ``pathogenic_count`` from DB-sourced pathogenicity."""
        pathogenic = {"Pathogenic", "Likely Pathogenic"}
        count = sum(
            1
            for r in results
            if r.core_annotations is not None
            and r.core_annotations.pathogenicity in pathogenic
        )
        return cls(patient_id=patient_id, results=list(results), pathogenic_count=count)
