"""Unit tests for the deterministic ``annotations_json`` parser.

The parser exists to replace the prototype's LLM-driven JSON decomposition
(Design ADR-006). These tests are the primary safety net against JSON-shape
edge cases in the seed data.
"""

from __future__ import annotations

import pytest

from egp_maf.state.results import (
    VariantExtendedAnnotations,
    parse_annotations_json,
)


class TestEmpty:
    def test_none_returns_empty(self) -> None:
        assert parse_annotations_json(None) == VariantExtendedAnnotations()

    def test_empty_string_returns_empty(self) -> None:
        assert parse_annotations_json("") == VariantExtendedAnnotations()

    def test_empty_dict_returns_empty(self) -> None:
        assert parse_annotations_json({}) == VariantExtendedAnnotations()


class TestTypedFields:
    def test_all_known_fields_promoted(self) -> None:
        blob = {
            "clinvar_id": "VCV000001",
            "rsid": "rs123",
            "hgvs_c": "c.5266dup",
            "hgvs_p": "p.Gln1756fs",
            "gnomad_af": 0.0001,
            "gnomad_af_popmax": 0.0005,
            "sift": "deleterious",
            "polyphen": "probably_damaging",
            "cadd_score": 33.5,
            "acmg_criteria": ["PS1", "PM2"],
        }
        result = parse_annotations_json(blob)
        assert result.clinvar_id == "VCV000001"
        assert result.rsid == "rs123"
        assert result.hgvs_c == "c.5266dup"
        assert result.hgvs_p == "p.Gln1756fs"
        assert result.gnomad_af == 0.0001
        assert result.gnomad_af_popmax == 0.0005
        assert result.sift == "deleterious"
        assert result.polyphen == "probably_damaging"
        assert result.cadd_score == 33.5
        assert result.acmg_criteria == ["PS1", "PM2"]
        assert result.raw_annotations is None

    def test_partial_known_fields(self) -> None:
        result = parse_annotations_json({"rsid": "rs123", "gnomad_af": 0.5})
        assert result.rsid == "rs123"
        assert result.gnomad_af == 0.5
        assert result.hgvs_c is None
        assert result.raw_annotations is None


class TestRawAnnotationsCatchAll:
    def test_unknown_keys_land_in_raw(self) -> None:
        blob = {
            "rsid": "rs123",
            "custom_field": "some value",
            "another": 42,
        }
        result = parse_annotations_json(blob)
        assert result.rsid == "rs123"
        assert result.raw_annotations == {
            "custom_field": "some value",
            "another": 42,
        }

    def test_all_unknown_no_typed_fields(self) -> None:
        blob = {"only_unknown": "value"}
        result = parse_annotations_json(blob)
        assert result.rsid is None
        assert result.raw_annotations == {"only_unknown": "value"}


class TestJsonStringInput:
    def test_json_string_parses(self) -> None:
        result = parse_annotations_json('{"rsid": "rs123", "cadd_score": 12.3}')
        assert result.rsid == "rs123"
        assert result.cadd_score == 12.3

    def test_malformed_json_raises(self) -> None:
        with pytest.raises(ValueError, match="not valid JSON"):
            parse_annotations_json("{not json")

    def test_non_object_json_raises(self) -> None:
        with pytest.raises(ValueError, match="must decode to a dict"):
            parse_annotations_json("[1, 2, 3]")


class TestAcmgCriteriaCoercion:
    def test_list_stays_list(self) -> None:
        result = parse_annotations_json({"acmg_criteria": ["PS1", "PM2"]})
        assert result.acmg_criteria == ["PS1", "PM2"]

    def test_single_string_becomes_list(self) -> None:
        result = parse_annotations_json({"acmg_criteria": "PS1"})
        assert result.acmg_criteria == ["PS1"]


class TestRoundTrip:
    def test_dump_parse_stable(self) -> None:
        blob = {
            "rsid": "rs123",
            "cadd_score": 12.3,
            "custom_field": "value",
        }
        result = parse_annotations_json(blob)
        # Serialise and re-parse via the model
        dumped = result.model_dump()
        # raw_annotations should still be intact
        assert dumped["raw_annotations"] == {"custom_field": "value"}
