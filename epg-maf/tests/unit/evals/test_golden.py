"""Tests for :mod:`egp_maf.evals.golden`."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from egp_maf.evals.golden import GoldenItem, GoldenToolCall, load_golden_set

pytestmark = pytest.mark.unit


class TestBundledSeedSet:
    def test_seed_set_loads_and_has_all_domains(self) -> None:
        items = load_golden_set()
        assert len(items) >= 6, "seed set should cover the 5 domains + multi"
        domains = {i.domain for i in items}
        assert {"prs", "genomic_variants", "pgx", "phenotype", "family_history"} <= domains

    def test_every_item_has_an_id_and_a_patient(self) -> None:
        for item in load_golden_set():
            assert item.id
            assert item.patient_id
            assert item.question
            assert item.domain

    def test_every_expected_tool_call_has_a_tool_name(self) -> None:
        for item in load_golden_set():
            for call in item.expected_tool_calls:
                assert call.tool_name

    def test_privacy_tag_is_present_for_family_history_items(self) -> None:
        items = [i for i in load_golden_set() if i.domain == "family_history"]
        assert items, "seed set must include at least one family-history item"
        assert any("privacy" in i.tags for i in items)


class TestExternalOverride:
    def test_external_items_are_merged(self, tmp_path: Path) -> None:
        extra = [
            {
                "id": "external.001",
                "domain": "prs",
                "question": "extra question",
                "patient_id": "P999",
                "expected_tool_calls": [],
                "expected_output_keys": [],
                "tags": ["external"],
            }
        ]
        (tmp_path / "extra.json").write_text(json.dumps(extra), encoding="utf-8")
        items = load_golden_set(external_path=tmp_path)
        assert any(i.id == "external.001" for i in items)

    def test_duplicate_id_raises(self, tmp_path: Path) -> None:
        # Duplicate a bundled id.
        bundled_id = load_golden_set(include_bundled=True)[0].id
        (tmp_path / "dup.json").write_text(
            json.dumps(
                [
                    {
                        "id": bundled_id,
                        "domain": "prs",
                        "question": "q",
                        "patient_id": "P1",
                        "expected_tool_calls": [],
                        "expected_output_keys": [],
                        "tags": [],
                    }
                ]
            ),
            encoding="utf-8",
        )
        with pytest.raises(ValueError, match="Duplicate golden-set id"):
            load_golden_set(external_path=tmp_path)

    def test_include_bundled_false_excludes_seed(self, tmp_path: Path) -> None:
        assert load_golden_set(external_path=tmp_path, include_bundled=False) == []


class TestGoldenItemValidation:
    def test_extra_forbid(self) -> None:
        with pytest.raises(ValueError):
            GoldenItem.model_validate(
                {
                    "id": "x",
                    "domain": "prs",
                    "question": "q",
                    "patient_id": "P1",
                    "expected_tool_calls": [],
                    "expected_output_keys": [],
                    "tags": [],
                    "made_up_field": "no",
                }
            )

    def test_tool_call_extra_forbid(self) -> None:
        with pytest.raises(ValueError):
            GoldenToolCall.model_validate(
                {"tool_name": "x", "extra": 1}
            )
