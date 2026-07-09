"""Reducer + state-model tests for :mod:`egp_maf.workflow.state`."""

from __future__ import annotations

import pytest

from egp_maf.state.clinician_context import ClinicianContext
from egp_maf.workflow.state import (
    ChatWorkflowState,
    OrchestrationWorkflowState,
    Remove,
    SpecialistSlot,
    apply_agents_completed,
    apply_specialist_slot,
)


class TestApplyAgentsCompleted:
    def test_append_single_str(self) -> None:
        assert apply_agents_completed([], "prs") == ["prs"]

    def test_append_dedupe(self) -> None:
        assert apply_agents_completed(["prs"], "prs") == ["prs"]

    def test_append_multiple_and_sorted(self) -> None:
        result = apply_agents_completed([], ["prs", "family_history", "pgx"])
        assert result == sorted(["prs", "family_history", "pgx"])

    def test_remove_sentinel_drops_name(self) -> None:
        assert apply_agents_completed(["prs", "pgx"], Remove(name="prs")) == ["pgx"]

    def test_remove_missing_name_is_noop(self) -> None:
        assert apply_agents_completed(["prs"], Remove(name="phenotype")) == ["prs"]

    def test_mixed_add_and_remove(self) -> None:
        result = apply_agents_completed(
            ["prs", "pgx"],
            [Remove(name="prs"), "family_history"],
        )
        assert result == sorted(["pgx", "family_history"])

    def test_unknown_specialist_rejected(self) -> None:
        with pytest.raises(ValueError, match="Unknown specialist"):
            apply_agents_completed([], "not_a_specialist")

    def test_output_is_deterministic_regardless_of_delta_order(self) -> None:
        a = apply_agents_completed([], ["prs", "phenotype", "pgx"])
        b = apply_agents_completed([], ["pgx", "prs", "phenotype"])
        assert a == b == sorted({"prs", "phenotype", "pgx"})


class TestApplySpecialistSlot:
    def test_last_write_wins(self) -> None:
        first = SpecialistSlot(status="running")
        second = SpecialistSlot(status="completed", output={"x": 1})
        assert apply_specialist_slot(first, second) is second

    def test_last_write_wins_over_none(self) -> None:
        slot = SpecialistSlot(status="completed", output={"y": 2})
        assert apply_specialist_slot(None, slot) is slot


class TestSpecialistSlotFactories:
    def test_completed_with(self) -> None:
        slot = SpecialistSlot.completed_with({"a": 1})
        assert slot.status == "completed"
        assert slot.output == {"a": 1}
        assert slot.errors == []

    def test_failed_with(self) -> None:
        slot = SpecialistSlot.failed_with("boom")
        assert slot.status == "failed"
        assert slot.output is None
        assert slot.errors == ["boom"]


class TestChatWorkflowState:
    def test_minimum_required_fields(self) -> None:
        state = ChatWorkflowState(
            ctx=ClinicianContext.system(),
            patient_id="P1",
            thread_id="T1",
        )
        assert state.original_query == ""
        assert state.next_action == ""
        assert state.messages == []
        assert state.agents_completed == []
        assert state.prs is None


class TestOrchestrationWorkflowState:
    def test_minimum_required_fields(self) -> None:
        state = OrchestrationWorkflowState(
            ctx=ClinicianContext.system(),
            patient_id="P1",
            original_query="q",
        )
        assert state.router_iterations == 0
        assert state.agents_completed == []
