"""Tests for :mod:`egp_maf.evals.scorers`."""

from __future__ import annotations

import pytest

from egp_maf.agents.base import ToolCall
from egp_maf.evals.golden import GoldenItem, GoldenToolCall
from egp_maf.evals.scorers import (
    InterpretationJudgeScorer,
    StubJudge,
    ToolCallScorer,
)

pytestmark = pytest.mark.unit


def _item(
    *,
    expected: list[GoldenToolCall],
    keys: list[str] | None = None,
    tags: list[str] | None = None,
) -> GoldenItem:
    return GoldenItem(
        id="test.001",
        domain="prs",
        question="q",
        patient_id="P1",
        expected_tool_calls=expected,
        expected_output_keys=keys or [],
        tags=tags or [],
    )


def _call(name: str, **params: object) -> ToolCall:
    return ToolCall(
        tool_name=name,
        tool_parameters=dict(params),
        tool_output=[],
    )


class TestToolCallScorer:
    def test_empty_expectation_passes(self) -> None:
        item = _item(expected=[])
        result = ToolCallScorer().score(item, [_call("something")])
        assert result.passed
        assert result.score == 1.0

    def test_exact_match_passes(self) -> None:
        item = _item(
            expected=[GoldenToolCall(tool_name="get_patient_prs", tool_parameters={"patient_id": "P1"})]
        )
        result = ToolCallScorer().score(item, [_call("get_patient_prs", patient_id="P1")])
        assert result.passed
        assert result.score == 1.0

    def test_missing_tool_fails(self) -> None:
        item = _item(
            expected=[GoldenToolCall(tool_name="get_patient_prs")]
        )
        result = ToolCallScorer().score(item, [_call("get_patient_pgx")])
        assert not result.passed
        assert result.score == 0.0
        assert "missing" in result.reason

    def test_extra_call_does_not_fail_by_default(self) -> None:
        item = _item(
            expected=[GoldenToolCall(tool_name="get_patient_prs")]
        )
        result = ToolCallScorer().score(
            item,
            [_call("get_patient_prs"), _call("unexpected_tool")],
        )
        assert result.passed
        # But the extras are reported.
        assert "extras" in result.reason

    def test_strict_extras_flag_fails_on_extras(self) -> None:
        item = _item(
            expected=[GoldenToolCall(tool_name="get_patient_prs")]
        )
        result = ToolCallScorer(strict_extras=True).score(
            item,
            [_call("get_patient_prs"), _call("unexpected_tool")],
        )
        assert not result.passed

    def test_partial_match_scores_between_zero_and_one(self) -> None:
        item = _item(
            expected=[
                GoldenToolCall(tool_name="a"),
                GoldenToolCall(tool_name="b"),
            ]
        )
        result = ToolCallScorer().score(item, [_call("a")])
        assert 0.0 < result.score < 1.0
        assert not result.passed

    def test_parameter_mismatch_counts_as_missing(self) -> None:
        item = _item(
            expected=[GoldenToolCall(tool_name="get_patient_prs", tool_parameters={"patient_id": "P1"})]
        )
        result = ToolCallScorer().score(
            item, [_call("get_patient_prs", patient_id="P2")]
        )
        assert not result.passed

    def test_actual_can_have_extra_parameters(self) -> None:
        """A superset of the expected parameters is allowed."""
        item = _item(
            expected=[GoldenToolCall(tool_name="t", tool_parameters={"patient_id": "P1"})]
        )
        result = ToolCallScorer().score(
            item, [_call("t", patient_id="P1", extra="ok")]
        )
        assert result.passed

    def test_ordering_violation_fails(self) -> None:
        item = _item(
            expected=[
                GoldenToolCall(tool_name="a"),
                GoldenToolCall(tool_name="b", depends_on=["a"]),
            ]
        )
        result = ToolCallScorer().score(item, [_call("b"), _call("a")])
        assert not result.passed
        assert "ordering" in result.reason


class TestJudgeScorer:
    def test_stub_judge_passes_when_needles_present(self) -> None:
        item = _item(
            expected=[GoldenToolCall(tool_name="t")],
            keys=["output.results"],
        )
        scorer = InterpretationJudgeScorer(StubJudge())
        result = scorer.score(item, "results are shown here")
        assert result.passed

    def test_stub_judge_fails_when_needle_missing(self) -> None:
        item = _item(
            expected=[],
            keys=["output.results"],
        )
        scorer = InterpretationJudgeScorer(StubJudge())
        result = scorer.score(item, "no relevant content")
        assert not result.passed
        assert "missing" in result.reason
