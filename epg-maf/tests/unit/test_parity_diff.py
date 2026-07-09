"""Unit tests for the parity-diff helper.

The helper is the load-bearing primitive of the mode-parity harness —
if it lies, the harness lies. Coverage targets: dict/list/scalar
walks, ignore-keys at any depth, order-insensitive lists, type
mismatches, missing keys.
"""

from __future__ import annotations

import pytest

from tests.support.parity_diff import DEFAULT_IGNORE_KEYS, deep_diff

pytestmark = pytest.mark.unit


class TestScalars:
    def test_equal_scalars_no_diff(self) -> None:
        assert deep_diff(1, 1) == []
        assert deep_diff("x", "x") == []
        assert deep_diff(None, None) == []

    def test_unequal_scalars(self) -> None:
        diffs = deep_diff(1, 2)
        assert diffs == ["<root>: 1 != 2"]


class TestDicts:
    def test_equal_dicts(self) -> None:
        assert deep_diff({"a": 1, "b": 2}, {"a": 1, "b": 2}) == []

    def test_unequal_dicts(self) -> None:
        diffs = deep_diff({"a": 1}, {"a": 2})
        assert diffs == ["a: 1 != 2"]

    def test_missing_keys(self) -> None:
        diffs = deep_diff({"a": 1, "b": 2}, {"a": 1})
        assert any("only in first" in d for d in diffs)

    def test_extra_keys(self) -> None:
        diffs = deep_diff({"a": 1}, {"a": 1, "c": 3})
        assert any("only in second" in d for d in diffs)

    def test_nested(self) -> None:
        diffs = deep_diff(
            {"outer": {"inner": {"leaf": 1}}},
            {"outer": {"inner": {"leaf": 2}}},
        )
        assert diffs == ["outer.inner.leaf: 1 != 2"]


class TestIgnoreKeys:
    def test_default_ignore_keys_dropped(self) -> None:
        # All the defaults must be silently ignored regardless of depth.
        for key in DEFAULT_IGNORE_KEYS:
            a = {"a": 1, key: "before"}
            b = {"a": 1, key: "after"}
            assert deep_diff(a, b) == [], f"{key} not being ignored"

    def test_ignore_key_deep(self) -> None:
        a = {"slots": {"prs": {"updated_at": "T1", "status": "ok"}}}
        b = {"slots": {"prs": {"updated_at": "T2", "status": "ok"}}}
        assert deep_diff(a, b) == []

    def test_custom_ignore(self) -> None:
        a = {"x": 1, "y": 2}
        b = {"x": 99, "y": 2}
        assert deep_diff(a, b, ignore_keys={"x"}) == []


class TestListsInOrder:
    def test_equal_lists_pass(self) -> None:
        assert deep_diff([1, 2, 3], [1, 2, 3]) == []

    def test_unequal_lengths(self) -> None:
        diffs = deep_diff({"xs": [1, 2]}, {"xs": [1, 2, 3]})
        assert diffs == ["xs: list length 2 != 3"]

    def test_element_mismatch_reports_index(self) -> None:
        diffs = deep_diff({"xs": [1, 2]}, {"xs": [1, 9]})
        assert diffs == ["xs[1]: 2 != 9"]


class TestListsOrderInsensitive:
    def test_agents_completed_order_insensitive(self) -> None:
        # ``agents_completed`` is in the ``ignore_list_order_at`` default,
        # so different orders must not be reported as diffs.
        a = {"agents_completed": ["prs", "pgx"]}
        b = {"agents_completed": ["pgx", "prs"]}
        assert deep_diff(a, b) == []

    def test_agents_completed_actual_mismatch_reported(self) -> None:
        a = {"agents_completed": ["prs", "pgx"]}
        b = {"agents_completed": ["prs", "phenotype"]}
        diffs = deep_diff(a, b)
        assert any("sorted lists differ" in d for d in diffs)


class TestTypes:
    def test_type_mismatch_reported(self) -> None:
        diffs = deep_diff(1, "1")
        assert any("type" in d for d in diffs)
