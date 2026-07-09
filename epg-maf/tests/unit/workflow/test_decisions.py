"""Tests for :mod:`egp_maf.workflow.decisions`."""

from __future__ import annotations

import pytest

from egp_maf.workflow.decisions import (
    ChatRouterDecision,
    SpecialistDispatchSet,
)


class TestChatRouterDecision:
    def test_minimal(self) -> None:
        d = ChatRouterDecision(needs_clinical_data=True, reason="need data")
        assert d.reset_agents == []

    def test_reset_agents_must_be_valid(self) -> None:
        # Unknown specialist name is rejected by the Literal type.
        with pytest.raises(Exception):
            ChatRouterDecision(
                needs_clinical_data=True,
                reason="reset unknown",
                reset_agents=["not_a_specialist"],  # type: ignore[list-item]
            )

    def test_extra_fields_forbidden(self) -> None:
        with pytest.raises(Exception):
            ChatRouterDecision(
                needs_clinical_data=True,
                reason="x",
                bogus_field=True,  # type: ignore[call-arg]
            )


class TestSpecialistDispatchSet:
    def test_terminal_when_empty(self) -> None:
        d = SpecialistDispatchSet(specialists=[], reason="done")
        assert d.is_terminal()

    def test_non_terminal_with_one(self) -> None:
        d = SpecialistDispatchSet(specialists=["prs"], reason="start")
        assert not d.is_terminal()

    def test_duplicates_rejected(self) -> None:
        with pytest.raises(Exception, match="duplicate"):
            SpecialistDispatchSet(specialists=["prs", "prs"], reason="dup")

    def test_unknown_specialist_rejected_by_literal(self) -> None:
        with pytest.raises(Exception):
            SpecialistDispatchSet(
                specialists=["not_a_specialist"],  # type: ignore[list-item]
                reason="bogus",
            )
