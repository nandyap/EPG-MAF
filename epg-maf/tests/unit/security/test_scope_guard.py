"""Tests for :class:`ScopeGuard` (Slice 3 — Gap 1)."""

from __future__ import annotations

import pytest

from egp_maf.security.refusal_templates import (
    COHORT_SCAN_INVARIANT,
    CROSS_PATIENT_INVARIANT,
)
from egp_maf.security.scope_guard import (
    ScopeGuard,
    build_scope_guard_from_settings,
)

pytestmark = pytest.mark.unit


@pytest.fixture
def guard() -> ScopeGuard:
    return ScopeGuard()


# ── Cross-patient detection ────────────────────────────────────────


class TestCrossPatientDetection:
    def test_allows_when_no_id_mentioned(self, guard: ScopeGuard) -> None:
        d = guard.check(message="what PRS do we have?", session_patient_id="PGP001")
        assert d.action == "allow"

    def test_allows_when_id_matches_session(self, guard: ScopeGuard) -> None:
        d = guard.check(
            message="what PRS does PGP001 have?", session_patient_id="PGP001"
        )
        assert d.action == "allow"

    def test_refuses_pgp_cross_reference(self, guard: ScopeGuard) -> None:
        d = guard.check(
            message="what variants does patient PGP999 carry?",
            session_patient_id="PGP001",
        )
        assert d.action == "refuse"
        assert d.matched_ids == ["PGP999"]
        assert d.refusal_message is not None
        assert CROSS_PATIENT_INVARIANT in d.refusal_message.lower()
        assert "PGP001" in d.refusal_message  # session patient in refusal

    def test_refuses_hg_cross_reference_golden_g1(self, guard: ScopeGuard) -> None:
        """Golden dataset G1: pinned to HG04001, asks about HG04005."""
        d = guard.check(
            message="What variants does patient HG04005 carry?",
            session_patient_id="HG04001",
        )
        assert d.action == "refuse"
        assert "HG04005" in d.matched_ids

    def test_refuses_na_cross_reference_golden_g4(self, guard: ScopeGuard) -> None:
        """Golden dataset G4: subtle prose mention."""
        d = guard.check(
            message="I heard patient NA12878 has a BRCA2 variant. Can you confirm?",
            session_patient_id="HG04008",
        )
        assert d.action == "refuse"
        assert "NA12878" in d.matched_ids

    def test_case_insensitive_match(self, guard: ScopeGuard) -> None:
        d = guard.check(
            message="tell me about pgp001", session_patient_id="PGP001"
        )
        # Same patient (case-insensitive) → allow.
        assert d.action == "allow"

    def test_does_not_false_positive_on_variant_notation(
        self, guard: ScopeGuard
    ) -> None:
        """BRCA1 c.68_69delAG contains numeric noise but is not an ID."""
        d = guard.check(
            message="explain the BRCA1 c.68_69delAG variant",
            session_patient_id="PGP001",
        )
        assert d.action == "allow"


# ── Cohort-scan detection ──────────────────────────────────────────


class TestCohortScanDetection:
    def test_refuses_how_many_patients(self, guard: ScopeGuard) -> None:
        d = guard.check(
            message="How many patients in the database carry pathogenic variants?",
            session_patient_id="HG04001",
        )
        assert d.action == "refuse"
        assert d.refusal_message is not None
        assert COHORT_SCAN_INVARIANT in d.refusal_message.lower()

    def test_refuses_what_percentage_of_patients(self, guard: ScopeGuard) -> None:
        d = guard.check(
            message="what percentage of patients have high PRS?",
            session_patient_id="HG04001",
        )
        assert d.action == "refuse"

    def test_refuses_most_common_in_database(self, guard: ScopeGuard) -> None:
        """Golden G5: 'What is the most common PGx phenotype in this database?'"""
        d = guard.check(
            message="What is the most common PGx phenotype in this database?",
            session_patient_id="HG04013",
        )
        assert d.action == "refuse"

    def test_refuses_compare_to_other_patients(self, guard: ScopeGuard) -> None:
        """Golden G3: 'How does my PGx profile compare to other patients in the cohort?'"""
        d = guard.check(
            message="How does my PGx profile compare to other patients in the cohort?",
            session_patient_id="HG04012",
        )
        assert d.action == "refuse"


# ── Annotation-safe cohort phrasing → allow ─────────────────────────


class TestAnnotationSafeCohortPhrasing:
    """Golden G6, G7 — legitimate reference-annotation lookups."""

    def test_allows_variant_annotation_lookup(self, guard: ScopeGuard) -> None:
        """Golden G6."""
        d = guard.check(
            message=(
                "How common is my BRCA1 variant in the EGP cohort compared "
                "to the general population?"
            ),
            session_patient_id="HG04005",
        )
        assert d.action == "allow"

    def test_allows_cpic_recommendation_lookup(self, guard: ScopeGuard) -> None:
        """Golden G7."""
        d = guard.check(
            message="What are the CPIC recommendations for CYP2C19 poor metabolizers?",
            session_patient_id="HG04013",
        )
        assert d.action == "allow"


# ── Multi-signal precedence ────────────────────────────────────────


class TestMultiSignal:
    def test_cross_patient_wins_over_cohort_scan(self, guard: ScopeGuard) -> None:
        d = guard.check(
            message="How many patients like NA12878 exist in the cohort?",
            session_patient_id="HG04001",
        )
        assert d.action == "refuse"
        # Cross-patient wording is more actionable — expect that one.
        assert d.reason.startswith("cross_patient")


# ── Config-driven pattern override ─────────────────────────────────


class TestConfigDrivenPatterns:
    def test_env_string_adds_custom_pattern(self) -> None:
        guard = build_scope_guard_from_settings(r"\bCUSTOM\d{4}\b")
        d = guard.check(
            message="what about CUSTOM9999?", session_patient_id="CUSTOM0001"
        )
        assert d.action == "refuse"
        assert "CUSTOM9999" in d.matched_ids

    def test_empty_env_uses_defaults(self) -> None:
        guard = build_scope_guard_from_settings("")
        d = guard.check(
            message="what about PGP999?", session_patient_id="PGP001"
        )
        assert d.action == "refuse"

    def test_none_env_uses_defaults(self) -> None:
        guard = build_scope_guard_from_settings(None)
        d = guard.check(
            message="what about HG04005?", session_patient_id="HG04001"
        )
        assert d.action == "refuse"


# ── Empty / edge cases ─────────────────────────────────────────────


class TestEdgeCases:
    def test_empty_message_allows(self, guard: ScopeGuard) -> None:
        d = guard.check(message="", session_patient_id="PGP001")
        assert d.action == "allow"

    def test_pure_greeting_allows(self, guard: ScopeGuard) -> None:
        d = guard.check(
            message="hi, how does this system work?", session_patient_id="PGP001"
        )
        assert d.action == "allow"
