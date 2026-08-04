"""Tests for the Slice 3 refusal templates."""

from __future__ import annotations

import pytest

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

pytestmark = pytest.mark.unit


class TestCrossPatientRefusal:
    def test_contains_invariant_substrings(self) -> None:
        text = cross_patient_refusal("PGP001").lower()
        assert CROSS_PATIENT_INVARIANT in text
        assert NEW_CHAT_INVARIANT in text

    def test_interpolates_patient_id(self) -> None:
        assert "PGP001" in cross_patient_refusal("PGP001")
        assert "HG04001" in cross_patient_refusal("HG04001")

    def test_pure_function(self) -> None:
        assert cross_patient_refusal("PGP001") == cross_patient_refusal("PGP001")


class TestCohortScanRefusal:
    def test_contains_invariant_substrings(self) -> None:
        text = cohort_scan_refusal("PGP001").lower()
        assert COHORT_SCAN_INVARIANT in text
        assert NO_SCAN_INVARIANT in text

    def test_mentions_patient_twice(self) -> None:
        # Once for "I can only report on X" and once for the offer to
        # report X's own findings.
        text = cohort_scan_refusal("PGP001")
        assert text.count("PGP001") >= 2


class TestAnnotationMissingRefusal:
    def test_contains_invariant_substring(self) -> None:
        assert ANNOTATION_MISSING_INVARIANT in ANNOTATION_MISSING_REFUSAL.lower()

    def test_static_constant(self) -> None:
        # No interpolation — it's a plain str constant.
        assert isinstance(ANNOTATION_MISSING_REFUSAL, str)
        assert len(ANNOTATION_MISSING_REFUSAL) > 0
