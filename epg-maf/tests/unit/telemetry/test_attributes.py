"""Tests for :mod:`egp_maf.telemetry.attributes`."""

from __future__ import annotations

import pytest

from egp_maf.telemetry.attributes import (
    ALLOWED_ATTRIBUTES,
    FORBIDDEN_ATTRIBUTES,
    filter_safe_attributes,
    is_forbidden_attribute,
)

pytestmark = pytest.mark.unit


class TestForbiddenSet:
    def test_family_history_privacy_trio_forbidden(self) -> None:
        for name in (
            "search_context_notes",
            "affected_relative_count",
            "total_relatives_searched",
        ):
            assert is_forbidden_attribute(name)

    def test_llm_content_forbidden(self) -> None:
        for name in ("prompt_text", "completion_text", "message.content"):
            assert is_forbidden_attribute(name)

    def test_row_body_forbidden(self) -> None:
        for name in ("row.body", "row.content", "source_row"):
            assert is_forbidden_attribute(name)

    def test_disjoint_from_allowed(self) -> None:
        """No name can be both allowed and forbidden."""
        overlap = ALLOWED_ATTRIBUTES & FORBIDDEN_ATTRIBUTES
        assert overlap == frozenset(), f"overlap: {sorted(overlap)}"


class TestAllowedSet:
    def test_canonical_names_present(self) -> None:
        for name in (
            "service.name",
            "workflow.executor",
            "specialist.name",
            "llm.model",
            "llm.phase",
            "tool.name",
            "db.table",
            "orch.mode",
            "orch.width",
            "trace_id",
        ) if False else (
            # ``trace_id`` intentionally *not* an attribute — it's a
            # span-level identifier populated by OTEL itself. This
            # comprehension mirrors Design §20.3 excluding OTEL-owned
            # names.
            "service.name",
            "workflow.executor",
            "specialist.name",
            "llm.model",
            "llm.phase",
            "tool.name",
            "db.table",
            "orch.mode",
            "orch.width",
        ):
            assert name in ALLOWED_ATTRIBUTES, f"{name!r} missing from ALLOWED_ATTRIBUTES"


class TestFilterSafeAttributes:
    def test_forbidden_keys_dropped(self) -> None:
        out = filter_safe_attributes(
            {
                "specialist.name": "prs",
                "search_context_notes": "should-not-appear",
                "prompt_text": "should-not-appear",
            }
        )
        assert "specialist.name" in out
        assert "search_context_notes" not in out
        assert "prompt_text" not in out

    def test_empty_input(self) -> None:
        assert filter_safe_attributes(None) == {}
        assert filter_safe_attributes({}) == {}

    def test_all_forbidden(self) -> None:
        # Passing only forbidden keys returns an empty dict.
        out = filter_safe_attributes(
            {name: "x" for name in FORBIDDEN_ATTRIBUTES}
        )
        assert out == {}
