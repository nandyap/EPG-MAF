from __future__ import annotations
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field, model_validator
import logging

from agents.shared.state.provenance import DBProvenance

logger = logging.getLogger(__name__)


# ── Known values as documentation only ──────────────────────────────
# Not enforced — here so the LLM and developers know what to expect
# today, without breaking when new values appear tomorrow.

KNOWN_PATHOGENICITY_VALUES = [
    "Pathogenic",
    "Likely Pathogenic",
    "Variant of Uncertain Significance",
    "Likely Benign",
    "Benign",
]

KNOWN_VARIANT_TYPES = [
    "snp", "indel", "cnv", "missense", "nonsense",
    "frameshift", "splice_site", "synonymous", "structural_variant",
]


class VariantSampleData(BaseModel):
    """
    Per-sample data from patient_variants table.
    All fields optional — presence depends on sequencing pipeline.
    No vocabulary enforcement — platform and caller names are
    data-driven and will expand as new technologies are used.
    """
    genotype: Optional[str] = Field(
        None,
        description="Genotype observed in this patient. e.g. '0/1', '1/1', '0/0'"
    )
    sequencing_platform: Optional[str] = Field(
        None,
        description=(
            "Sequencing platform used. "
            "Not enforced — new platforms may appear. "
            "e.g. 'Illumina NovaSeq', 'PacBio HiFi', 'Oxford Nanopore'"
        )
    )
    variant_caller: Optional[str] = Field(
        None,
        description=(
            "Variant caller used. Not enforced — pipeline dependent. "
            "e.g. 'GATK HaplotypeCaller', 'DeepVariant', 'Clair3'"
        )
    )
    call_quality: Optional[float] = Field(
        None,
        description="Call quality score for this variant in this sample."
    )


class VariantCoreAnnotations(BaseModel):
    """
    Core annotation fields from variant_annotations table.
    These are top-level columns — primary axes for filtering.
    
    Pathogenicity and variant_type are described but not enforced —
    values are controlled by ClinVar and the annotation pipeline
    respectively, not by this codebase.
    """
    gene: Optional[str] = Field(
        None,
        description="Gene this variant falls in. e.g. 'BRCA1', 'TP53'."
    )
    variant_type: Optional[str] = Field(
        None,
        description=(
            f"Variant consequence type. Not enforced — pipeline dependent. "
            f"Known values today: {KNOWN_VARIANT_TYPES}. "
            f"New values may appear as pipeline evolves."
        )
    )
    pathogenicity: Optional[str] = Field(
        None,
        description=(
            f"ClinVar clinical significance. Not enforced — ClinVar controls this. "
            f"Known values today: {KNOWN_PATHOGENICITY_VALUES}. "
            f"May expand with ClinVar updates."
        )
    )
    disease_name: Optional[str] = Field(
        None,
        description="Disease associated with this variant."
    )
    notes: Optional[str] = Field(
        None,
        description="Free-text notes from variant_annotations."
    )

    @model_validator(mode="after")
    def warn_unknown_values(self) -> VariantCoreAnnotations:
        """
        Soft warning — logs unexpected values rather than raising.
        Keeps the pipeline running while flagging values to review.
        """
        if (
            self.pathogenicity is not None
            and self.pathogenicity not in KNOWN_PATHOGENICITY_VALUES
        ):
            logger.warning(
                f"Unexpected pathogenicity value: '{self.pathogenicity}'. "
                f"Not in known values {KNOWN_PATHOGENICITY_VALUES}. "
                f"Consider updating KNOWN_PATHOGENICITY_VALUES."
            )

        if (
            self.variant_type is not None
            and self.variant_type not in KNOWN_VARIANT_TYPES
        ):
            logger.warning(
                f"Unexpected variant_type value: '{self.variant_type}'. "
                f"Not in known values {KNOWN_VARIANT_TYPES}. "
                f"Consider updating KNOWN_VARIANT_TYPES."
            )

        return self


class VariantExtendedAnnotations(BaseModel):
    """
    Extended annotations from JSONB blob in variant_annotations.
    
    Explicitly open-ended by design. Typed fields cover well-known
    annotations present today. raw_annotations is the catch-all
    for anything not yet modelled.
    
    As your annotation pipeline stabilises, promote fields from
    raw_annotations up to typed fields here.
    """
    # ── Identifiers ───────────────────────────────────────────────
    clinvar_id: Optional[str] = Field(None, description="ClinVar accession.")
    rsid: Optional[str] = Field(None, description="dbSNP rsID.")
    hgvs_c: Optional[str] = Field(None, description="HGVS coding notation.")
    hgvs_p: Optional[str] = Field(None, description="HGVS protein notation.")

    # ── Population frequencies ────────────────────────────────────
    gnomad_af: Optional[float] = Field(
        None, description="gnomAD global allele frequency."
    )
    gnomad_af_popmax: Optional[float] = Field(
        None, description="gnomAD max allele frequency across populations."
    )

    # ── In silico predictors ──────────────────────────────────────
    sift: Optional[str] = Field(None, description="SIFT prediction.")
    polyphen: Optional[str] = Field(None, description="PolyPhen-2 prediction.")
    cadd_score: Optional[float] = Field(None, description="CADD phred score.")

    # ── ACMG ──────────────────────────────────────────────────────
    acmg_criteria: Optional[List[str]] = Field(
        None, description="ACMG/AMP criteria met. e.g. ['PS1', 'PM2']."
    )

    # ── Catch-all — promotes to typed fields as pipeline matures ──
    raw_annotations: Optional[Dict[str, Any]] = Field(
        None,
        description=(
            "Any annotations from the JSONB blob not yet promoted to "
            "typed fields above. Preserved as-is. When a field appears "
            "consistently here, promote it to a typed field above."
        ),
        json_schema_extra={"additionalProperties": False},
    )


class GenomicVariantResult(BaseModel):
    """
    Single variant result. Composes all three annotation layers
    plus provenance and LLM interpretation.
    """
    variant_id: str = Field(..., description="Primary key from variant_annotations.")

    sample_data: Optional[VariantSampleData] = None
    core_annotations: Optional[VariantCoreAnnotations] = None
    extended_annotations: Optional[VariantExtendedAnnotations] = None

    interpretation: Optional[str] = Field(
        None,
        description="LLM-generated clinical interpretation."
    )
    interpretation_model: Optional[str] = None

    provenance: List[DBProvenance] = Field(default_factory=list)


class GenomicVariantsResultList(BaseModel):
    """Top-level output schema of the genomic variants agent."""
    patient_id: str
    results: List[GenomicVariantResult] = Field(default_factory=list)
    pathogenic_count: int = Field(
        default=0,
        description="Count of Pathogenic or Likely Pathogenic variants."
    )
    summary: Optional[str] = None
    summary_model: Optional[str] = None


class VariantKey(BaseModel):
    """
    Minimal patient-scoped variant key returned by explore_patient_genomic_variants.
    One row per variant carried by this patient.
    """
    variant_id: str = Field(..., description="Variant identifier. Primary key from variant_annotations.")
    genotype: Optional[str] = Field(None, description="Genotype observed in this patient. e.g. '0/1'.")