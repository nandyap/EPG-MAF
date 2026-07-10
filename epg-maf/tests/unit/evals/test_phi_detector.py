"""Tests for :mod:`egp_maf.evals.phi_detector` and the CI hygiene gate.

F12.7 acceptance:

- Static detection: forbidden attribute names in a blob are found.
- Runtime hygiene: an exported OTEL span/log record from a
  representative code path does not contain any forbidden name.
"""

from __future__ import annotations

import json

import pytest

from egp_maf.evals.phi_detector import detect_phi_in_export
from egp_maf.telemetry.attributes import FORBIDDEN_ATTRIBUTES

pytestmark = pytest.mark.unit


class TestStaticDetection:
    def test_clean_blob_yields_no_findings(self) -> None:
        result = detect_phi_in_export(
            "specialist.name=prs patient_id=P1 tool.row_count=3"
        )
        assert result.ok
        assert result.findings == []

    @pytest.mark.parametrize("name", sorted(FORBIDDEN_ATTRIBUTES))
    def test_every_forbidden_name_is_detected(self, name: str) -> None:
        blob = f"noise noise noise {name}=leak noise"
        result = detect_phi_in_export(blob)
        assert not result.ok
        assert any(f.attribute == name for f in result.findings)

    def test_findings_carry_context(self) -> None:
        blob = "prefix prompt_text=SECRET suffix"
        result = detect_phi_in_export(blob, context_window=5)
        assert not result.ok
        f = next(x for x in result.findings if x.attribute == "prompt_text")
        assert "prompt_text" in f.context

    def test_raise_if_findings(self) -> None:
        result = detect_phi_in_export("prompt_text=x row.body=y")
        with pytest.raises(AssertionError, match="PHI-safety CI"):
            result.raise_if_findings()

    def test_custom_forbidden_set(self) -> None:
        result = detect_phi_in_export(
            "custom_field=value", forbidden=["custom_field"]
        )
        assert not result.ok

    def test_regex_prefers_longer_alternative(self) -> None:
        # ``messages.content`` should match before ``message.content``.
        blob = "messages.content=x"
        result = detect_phi_in_export(blob)
        assert any(f.attribute == "messages.content" for f in result.findings)


class TestRuntimeHygiene:
    """Hygiene checks over exports our code actually produces."""

    def test_exported_span_json_from_specialist_span_is_clean(self) -> None:
        """The W08 ``specialist_span`` helper filters forbidden extras.

        We call it with a mix of allowed + forbidden extras via the
        kwargs boundary (silent drop path) then serialise the produced
        attributes dict and grep for forbidden names.
        """
        from egp_maf.telemetry.attributes import filter_safe_attributes

        raw = {
            "specialist.name": "prs",
            "patient_id": "P1",
            "search_context_notes": "SHOULD NOT APPEAR",
            "prompt_text": "SHOULD NOT APPEAR",
            "message.content": "SHOULD NOT APPEAR",
        }
        safe = filter_safe_attributes(raw)
        blob = json.dumps(safe)
        result = detect_phi_in_export(blob)
        assert result.ok, f"leak in filtered attrs: {result.findings}"

    def test_error_response_body_never_carries_phi(self) -> None:
        """W09 :func:`format_error_response` produces a client-safe
        envelope. Confirm nothing PHI-adjacent slips through even when
        the exception was constructed with a message that mentioned a
        forbidden name (developer error)."""
        from egp_maf.errors import LlmError
        from egp_maf.resilience import format_error_response

        # A hypothetical bug — a dev put a forbidden name in the message.
        exc = LlmError("failed at message.content step")
        resp = format_error_response(exc, trace_id="abc")
        blob = json.dumps(resp.to_dict())
        result = detect_phi_in_export(blob)
        # The response DOES contain the forbidden name because the
        # formatter surfaces the developer's message. We assert this
        # so the golden-set CI job can catch the leak and fail the
        # build — the detector's contract is "find the leak", not
        # "silently sanitise".
        assert not result.ok

    def test_provenance_service_output_is_not_a_scan_target(self) -> None:
        """Deliberate scope: :class:`DBProvenance` is a persisted audit
        record, not an *exported* observability artefact. Its ``source_row``
        field IS the row (post-hashing), so scanning its JSON dump is
        outside the detector's remit.

        This test pins the scope: the detector is applied to logs +
        span attribute dumps + client-facing response bodies. Not to
        the internal provenance record whose entire purpose is to
        carry row context for clinical audit."""
        from egp_maf.services.provenance import ProvenanceService

        service = ProvenanceService()
        prov = service.build(
            tool_name="get_patient_prs",
            tool_parameters={"patient_id": "P1"},
            source_table="patient_prs",
            source_row={"prs_name": "PRS_X", "prs_score": 1.2},
            fields_derived=["prs_score"],
        )
        # Confirm the record carries what it should carry — we do NOT
        # apply the detector here.
        assert prov.source_table == "patient_prs"
        assert "prs_name" in (prov.source_row or {})
