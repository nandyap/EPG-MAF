"""Strict-mode extraction schemas + conninfo quoting.

Both regressions were found together in the first production run that
reached a specialist.

1. ``_build_conninfo`` joined parameters by hand. The libpq ``options``
   value contains a space::

       options=-c statement_timeout=30000

   In a conninfo string a bare space separates key=value pairs, so libpq
   read ``options=-c`` and then a stray ``statement_timeout=30000``,
   rejecting it with ``invalid connection option "statement_timeout"``.
   Every connection failed instantly, the pool never reached ``min_size``
   and surfaced ``PoolTimeout: pool initialization incomplete after 10.0
   sec`` — indistinguishable from an unreachable host, which is what it
   was mistaken for.

2. Structured Outputs is strict and rejects free-form objects::

       Invalid schema for response_format 'GenomicVariantsResultList':
       In context=('properties', 'tool_parameters'),
       'additionalProperties' is required to be supplied and to be false.

   ``DBProvenance.tool_parameters`` / ``.source_row`` and
   ``VariantExtendedAnnotations.raw_annotations`` are all
   ``dict[str, Any]``. ADR-021 flagged that MAF parity here needed
   verifying; it never was.
"""

from __future__ import annotations

import json

import pytest
from psycopg.conninfo import conninfo_to_dict

from egp_maf.agents.extraction_schema import strict_extraction_schema
from egp_maf.config.settings import Settings
from egp_maf.infrastructure.db_pool import DbPoolFactory
from egp_maf.state.results.family_history import FamilyHistoryResultList
from egp_maf.state.results.genomic_variants import GenomicVariantsResultList
from egp_maf.state.results.pgx import PGXResultList
from egp_maf.state.results.phenotype import PhenotypeResultList
from egp_maf.state.results.prs import PRSResultList

pytestmark = pytest.mark.unit

_RESULT_LISTS = [
    GenomicVariantsResultList,
    PRSResultList,
    PGXResultList,
    PhenotypeResultList,
    FamilyHistoryResultList,
]


def _free_form_paths(node: object, path: str = "") -> list[str]:
    """Return paths of every object schema that permits extra keys."""
    found: list[str] = []
    if isinstance(node, dict):
        if node.get("type") == "object" and node.get("additionalProperties") is True:
            found.append(path)
        for key, value in node.items():
            found.extend(_free_form_paths(value, f"{path}.{key}"))
    elif isinstance(node, list):
        for index, value in enumerate(node):
            found.extend(_free_form_paths(value, f"{path}[{index}]"))
    return found


def _property_names(node: object) -> set[str]:
    """Return every declared property name anywhere in the schema."""
    names: set[str] = set()
    if isinstance(node, dict):
        properties = node.get("properties")
        if isinstance(properties, dict):
            names.update(properties)
        for value in node.values():
            names |= _property_names(value)
    elif isinstance(node, list):
        for value in node:
            names |= _property_names(value)
    return names


class TestStrictExtractionSchema:
    @pytest.mark.parametrize("model", _RESULT_LISTS, ids=lambda m: m.__name__)
    def test_no_free_form_objects(self, model: type) -> None:
        """The core regression — Compass rejects any free-form object."""
        schema = strict_extraction_schema(model).model_json_schema()

        assert _free_form_paths(schema) == []

    @pytest.mark.parametrize("model", _RESULT_LISTS, ids=lambda m: m.__name__)
    def test_repository_owned_fields_are_not_requested(self, model: type) -> None:
        """The LLM must never author provenance or raw annotations.

        Asserts on declared *properties* — the words also occur in
        inherited docstrings, which are harmless.
        """
        schema = strict_extraction_schema(model).model_json_schema()
        properties = _property_names(schema)

        assert "provenance" not in properties
        assert "raw_annotations" not in properties

    def test_clinical_fields_are_preserved(self) -> None:
        """Stripping must not remove anything the LLM *should* fill."""
        schema = strict_extraction_schema(
            GenomicVariantsResultList
        ).model_json_schema()
        rendered = json.dumps(schema)

        assert "interpretation" in rendered
        assert "summary" in rendered

    def test_nested_models_are_rewritten(self) -> None:
        """Optional nested models sit behind ``X | None``; a naive rewrite
        leaves those untouched and the free-form object survives."""
        derived = strict_extraction_schema(GenomicVariantsResultList)
        defs = derived.model_json_schema().get("$defs", {})

        assert any(name.endswith("Extraction") for name in defs), defs.keys()

    def test_result_is_cached(self) -> None:
        assert strict_extraction_schema(PRSResultList) is strict_extraction_schema(
            PRSResultList
        )

    def test_llm_output_validates_back_into_the_real_model(self) -> None:
        """The wire model is a projection — its payload must round-trip."""
        wire = strict_extraction_schema(PRSResultList)
        instance = wire.model_validate({"results": []})

        restored = PRSResultList.model_validate(instance.model_dump())

        assert restored.results == []


class TestConninfoQuoting:
    def _conninfo(self, **overrides: object) -> str:
        settings = Settings(
            LLM_API_KEY="test-key",
            POSTGRES_HOST="db.example.invalid",
            POSTGRES_PASSWORD="pw",
            **overrides,  # type: ignore[arg-type]
        )
        return DbPoolFactory(settings)._build_conninfo()

    def test_options_parses_as_a_single_parameter(self) -> None:
        """The core regression — an unquoted space split this in two."""
        parsed = conninfo_to_dict(self._conninfo())

        assert "statement_timeout" not in parsed
        assert parsed["options"] == "-c statement_timeout=30000"

    def test_statement_timeout_honours_settings(self) -> None:
        parsed = conninfo_to_dict(
            self._conninfo(POSTGRES_STATEMENT_TIMEOUT_SECONDS=5)
        )

        assert parsed["options"] == "-c statement_timeout=5000"

    def test_core_parameters_present(self) -> None:
        parsed = conninfo_to_dict(self._conninfo())

        assert parsed["host"] == "db.example.invalid"
        assert parsed["dbname"] == "egp"
        assert parsed["application_name"] == "egp-maf"

    def test_password_included_when_not_using_managed_identity(self) -> None:
        parsed = conninfo_to_dict(self._conninfo())

        assert parsed["password"] == "pw"
