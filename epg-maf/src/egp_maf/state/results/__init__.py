"""Typed result models — the shape each Repository returns.

One module per domain, mirroring the prototype ``agents/<domain>/state/schemas.py``.
Repositories build these and populate the DB-derived fields; LLM-derived
fields (``interpretation``, ``summary``, ...) are populated by the
specialist agents in W05.
"""

from egp_maf.state.results.family_history import (
    FamilyHistoryCriteriaResult,
    FamilyHistoryCriteriaResultPublic,
    FamilyHistoryKey,
    FamilyHistoryResultList,
    FamilyHistoryResultListPublic,
    KinshipHistoryAnnotation,
)
from egp_maf.state.results.genomic_variants import (
    KNOWN_PATHOGENICITY_VALUES,
    KNOWN_VARIANT_TYPES,
    GenomicVariantResult,
    GenomicVariantsResultList,
    VariantAnnotation,
    VariantCoreAnnotations,
    VariantExtendedAnnotations,
    VariantKey,
    VariantSampleData,
    parse_annotations_json,
)
from egp_maf.state.results.pgx import (
    PGXAnnotation,
    PGXDrugResult,
    PGXKey,
    PGXResultList,
)
from egp_maf.state.results.phenotype import (
    PhenotypeDiseaseResult,
    PhenotypeKey,
    PhenotypeResultList,
)
from egp_maf.state.results.prs import (
    PRSAnnotation,
    PRSKey,
    PRSResult,
    PRSResultList,
)

__all__ = [
    # PRS
    "PRSAnnotation",
    "PRSKey",
    "PRSResult",
    "PRSResultList",
    # Genomic variants
    "GenomicVariantResult",
    "GenomicVariantsResultList",
    "KNOWN_PATHOGENICITY_VALUES",
    "KNOWN_VARIANT_TYPES",
    "VariantAnnotation",
    "VariantCoreAnnotations",
    "VariantExtendedAnnotations",
    "VariantKey",
    "VariantSampleData",
    "parse_annotations_json",
    # Family history
    "FamilyHistoryCriteriaResult",
    "FamilyHistoryCriteriaResultPublic",
    "FamilyHistoryKey",
    "FamilyHistoryResultList",
    "FamilyHistoryResultListPublic",
    "KinshipHistoryAnnotation",
    # PGX
    "PGXAnnotation",
    "PGXDrugResult",
    "PGXKey",
    "PGXResultList",
    # Phenotype
    "PhenotypeDiseaseResult",
    "PhenotypeKey",
    "PhenotypeResultList",
]
