"""Slice 3 security package: ScopeGuard + refusal templates."""

from egp_maf.security.refusal_templates import (
    ANNOTATION_MISSING_INVARIANT,
    ANNOTATION_MISSING_REFUSAL,
    COHORT_SCAN_INVARIANT,
    CROSS_PATIENT_INVARIANT,
    NEW_CHAT_INVARIANT,
    NO_SCAN_INVARIANT,
    cohort_scan_refusal,
    cross_patient_refusal,
)
from egp_maf.security.scope_guard import ScopeDecision, ScopeGuard

__all__ = [
    "ANNOTATION_MISSING_INVARIANT",
    "ANNOTATION_MISSING_REFUSAL",
    "COHORT_SCAN_INVARIANT",
    "CROSS_PATIENT_INVARIANT",
    "NEW_CHAT_INVARIANT",
    "NO_SCAN_INVARIANT",
    "ScopeDecision",
    "ScopeGuard",
    "cohort_scan_refusal",
    "cross_patient_refusal",
]
