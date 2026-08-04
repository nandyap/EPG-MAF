"""Slice 4 shape tests for the full golden dataset.

Asserts the bundled JSON files parse, IDs are unique, tags follow a
controlled vocabulary, and cross-patient scope items have plausible
mismatch between the session's patient and any ID mentioned in the
question.
"""

from __future__ import annotations

import re
from collections import Counter

import pytest

from egp_maf.evals.golden import load_golden_set

pytestmark = pytest.mark.unit


# Controlled tag vocabulary. New tags must be added here as the golden
# set evolves — makes drift visible in the shape test.
_ALLOWED_TAGS: frozenset[str] = frozenset({
    # Provenance / status.
    "awaiting-compass",
    "bix_pending",
    # Golden-dataset provenance (matches PDF IDs).
    *{f"golden_g{i}" for i in range(1, 10)},
    *{f"golden_s{i}" for i in range(1, 15)},
    *{f"golden_r{i}" for i in range(1, 25)},
    # Domain grouping.
    "prs",
    "genomic_variants",
    "family_history",
    "pgx",
    "phenotype",
    "multi",
    "scope_guard",
    # Behaviour categories.
    "happy_path",
    "edge_case",
    "empty_result",
    "cross_domain",
    "correlation",
    "cross_patient",
    "cohort_scan",
    "cohort_allowed",
    "annotation_partial",
    "phi_redaction",
    "privacy",
    "family_history",
    # PRS.
    "evaluated",
    "noeval_disclosure",
    "many_scores",
    "high_risk",
    "low_risk",
    # Variants.
    "pathogenic",
    "vus",
    "benign",
    "homozygous",
    # PGX.
    "actionable",
    "normal",
    "extreme_profile",
    "mixed",
    # Family history.
    "met",
    "not_met",
    "low_quality",
    "high_quality",
    "multiple",
    # Assessment.
    "complete_profile",
    "complex",
    "sparse",
    "risk_assessment",
    "drug_safety",
    "multi_domain",
    "dispatch_mode_parity",
    "wide_fanout",
    "gap_1",
    "gap_2",
    "gap_3",
    "diagnosis_correlation",
})


class TestGoldenSetShape:
    def test_loads_at_least_43_items(self) -> None:
        items = load_golden_set()
        assert len(items) >= 43

    def test_ids_are_unique(self) -> None:
        items = load_golden_set()
        ids = [i.id for i in items]
        duplicates = [i for i, count in Counter(ids).items() if count > 1]
        assert not duplicates, f"Duplicate golden ids: {duplicates}"

    def test_tags_are_from_controlled_vocabulary(self) -> None:
        items = load_golden_set()
        unknown: dict[str, list[str]] = {}
        for item in items:
            for t in item.tags:
                if t not in _ALLOWED_TAGS:
                    unknown.setdefault(item.id, []).append(t)
        assert not unknown, (
            f"Unknown tags (add to _ALLOWED_TAGS if intentional): {unknown}"
        )

    def test_all_pdf_golden_items_present(self) -> None:
        """Every golden_g1..g9, golden_s1..s14, golden_r1..r24 is covered."""
        items = load_golden_set()
        tags_present = {t for item in items for t in item.tags}
        missing = []
        for i in range(1, 10):
            if f"golden_g{i}" not in tags_present:
                missing.append(f"G{i}")
        for i in range(1, 15):
            if f"golden_s{i}" not in tags_present:
                missing.append(f"S{i}")
        for i in range(1, 25):
            if f"golden_r{i}" not in tags_present:
                missing.append(f"R{i}")
        assert not missing, f"PDF items missing from golden set: {missing}"

    def test_refusal_items_have_expected_substrings(self) -> None:
        items = load_golden_set()
        cross_patient_items = [
            i for i in items if "cross_patient" in i.tags
        ]
        for item in cross_patient_items:
            assert item.expected_refusal_substrings, (
                f"{item.id}: cross_patient item has no expected_refusal_substrings"
            )

        cohort_scan_items = [
            i for i in items if "cohort_scan" in i.tags and i.domain == "scope_guard"
        ]
        for item in cohort_scan_items:
            assert item.expected_refusal_substrings, (
                f"{item.id}: cohort_scan item has no expected_refusal_substrings"
            )

    def test_cohort_allowed_items_have_no_refusal_substrings(self) -> None:
        items = load_golden_set()
        cohort_allowed_items = [
            i for i in items
            if "cohort_allowed" in i.tags and i.domain == "scope_guard"
        ]
        for item in cohort_allowed_items:
            assert not item.expected_refusal_substrings, (
                f"{item.id}: cohort_allowed item should not expect a refusal"
            )

    def test_cross_patient_items_mention_different_id(self) -> None:
        """A cross_patient scope item must name a patient ID that is
        NOT the session-pinned ``patient_id``. Otherwise the test data
        is inconsistent with what the ScopeGuard would detect.
        """
        items = load_golden_set()
        # Cover the golden dataset's known ID formats.
        id_regex = re.compile(r"\b(?:PGP\d+|HG\d{5}|NA\d{5})\b")
        for item in items:
            if "cross_patient" not in item.tags:
                continue
            matches = set(id_regex.findall(item.question))
            different = matches - {item.patient_id}
            assert different, (
                f"{item.id}: cross_patient question does not mention a "
                f"different patient (session={item.patient_id}, "
                f"matches={matches})"
            )

    def test_phi_redaction_items_have_forbidden_substrings(self) -> None:
        items = load_golden_set()
        phi_items = [i for i in items if "phi_redaction" in i.tags]
        for item in phi_items:
            assert item.forbidden_substrings, (
                f"{item.id}: phi_redaction item has empty forbidden_substrings"
            )

    def test_gap3_items_have_noeval_disclosure_tag_or_fact(self) -> None:
        """S4 and any R item flagged for Gap 3 should either be tagged
        ``noeval_disclosure`` or carry the disclosure fact substring."""
        items = load_golden_set()
        for item in items:
            if "gap_3" not in item.tags:
                continue
            has_tag = "noeval_disclosure" in item.tags
            has_fact = any(
                "not been evaluated" in f.lower()
                for f in item.expected_fact_substrings
            )
            assert has_tag or has_fact, (
                f"{item.id}: gap_3 item lacks noeval_disclosure signal"
            )
