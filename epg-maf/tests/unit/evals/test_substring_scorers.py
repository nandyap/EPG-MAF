"""Tests for the Slice 4 ``FactSubstringScorer`` and
``ForbiddenSubstringScorer``."""

from __future__ import annotations

import pytest

from egp_maf.evals.golden import GoldenItem
from egp_maf.evals.scorers import (
    FactSubstringScorer,
    ForbiddenSubstringScorer,
)

pytestmark = pytest.mark.unit


def _item(**overrides) -> GoldenItem:
    base = dict(
        id="test.item",
        domain="test",
        question="q",
        patient_id="P001",
    )
    base.update(overrides)
    return GoldenItem(**base)  # type: ignore[arg-type]


# ── FactSubstringScorer ────────────────────────────────────────────


class TestFactSubstringScorer:
    def test_no_op_when_no_expected_facts(self) -> None:
        scorer = FactSubstringScorer()
        r = scorer.score(_item(), reply="anything at all")
        assert r.passed
        assert r.score == 1.0

    def test_passes_when_all_substrings_present(self) -> None:
        scorer = FactSubstringScorer()
        item = _item(expected_fact_substrings=["PRS313_BC", "95th percentile", "very high"])
        r = scorer.score(
            item,
            reply="PRS313_BC is at the 95th percentile — very high risk.",
        )
        assert r.passed
        assert r.score == 1.0

    def test_case_insensitive(self) -> None:
        scorer = FactSubstringScorer()
        item = _item(expected_fact_substrings=["Alzheimer's disease"])
        r = scorer.score(item, reply="This is about alzheimer's DISEASE risk.")
        assert r.passed

    def test_reports_missing(self) -> None:
        scorer = FactSubstringScorer()
        item = _item(expected_fact_substrings=["PRS313_BC", "95th percentile"])
        r = scorer.score(item, reply="PRS313_BC only")
        assert not r.passed
        assert "95th percentile" in r.reason
        # Partial credit: 1 of 2 found.
        assert r.score == 0.5


# ── ForbiddenSubstringScorer ────────────────────────────────────────


class TestForbiddenSubstringScorer:
    def test_no_op_when_no_forbidden_substrings(self) -> None:
        scorer = ForbiddenSubstringScorer()
        r = scorer.score(_item(), reply="anything at all")
        assert r.passed
        assert r.score == 1.0

    def test_passes_when_no_forbidden_present(self) -> None:
        scorer = ForbiddenSubstringScorer()
        item = _item(forbidden_substrings=["Alice Smith", "age 47"])
        r = scorer.score(
            item,
            reply="The family history assessment meets the NCCN threshold.",
        )
        assert r.passed
        assert r.score == 1.0

    def test_zero_tolerance_case_sensitive(self) -> None:
        """PHI matches are case-sensitive by design."""
        scorer = ForbiddenSubstringScorer()
        item = _item(forbidden_substrings=["Alice Smith"])
        r = scorer.score(item, reply="Report includes Alice Smith's history")
        assert not r.passed
        assert r.score == 0.0
        assert "Alice Smith" in r.reason

    def test_ignores_case_mismatch(self) -> None:
        """Case-mismatch does NOT leak — case-sensitive comparison."""
        scorer = ForbiddenSubstringScorer()
        item = _item(forbidden_substrings=["Alice Smith"])
        r = scorer.score(item, reply="Report includes ALICE SMITH's history")
        assert r.passed  # case-different, so no exact match

    def test_multiple_leaks_reported(self) -> None:
        scorer = ForbiddenSubstringScorer()
        item = _item(forbidden_substrings=["Alice", "age 47", "MRN 1234"])
        r = scorer.score(item, reply="Alice, age 47, MRN 1234")
        assert not r.passed
        # All three should be listed in the reason.
        for token in ("Alice", "age 47", "MRN 1234"):
            assert token in r.reason
