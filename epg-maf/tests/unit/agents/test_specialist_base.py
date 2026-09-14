"""Tests for the specialist wrapper template + LLM protocol.

Uses the smallest possible concrete subclass — the PRS specialist — to
exercise the pipeline. Deeper per-domain assertions live in each
per-specialist test file.
"""

from __future__ import annotations

from typing import Any

import pytest

from egp_maf.agents.base import (
    SpecialistBase,
    SpecialistInputs,
    SpecialistReactResult,
    ToolCall,
)
from egp_maf.agents.llm_bridge import StubSpecialistLlm
from egp_maf.agents.prs import PRSSpecialist
from egp_maf.agents.state_outputs import PRSStateOutput
from egp_maf.services.provenance import ProvenanceService
from egp_maf.state.clinician_context import ClinicianContext
from egp_maf.state.results.prs import PRSResult, PRSResultList
from tests.support.authz_doubles import OpenAuthzPolicy
from unittest.mock import MagicMock

pytestmark = pytest.mark.unit


def _prs_specialist() -> PRSSpecialist:
    return PRSSpecialist(
        system_prompt="test system prompt",
        interpretation_model_name="test-model-1",
        repository=MagicMock(),
        provenance_service=ProvenanceService(),
    )


#: A patient-scoped call that returned one row.
#:
#: ``SpecialistBase.run`` skips the extraction pass when no
#: patient-scoped tool returned a row — the guard added after the
#: 2026-09-11 HG010 incident. Tests about the post-retrieval template
#: mechanics have to declare that retrieval happened.
_RETRIEVED_ONE_ROW = [
    ToolCall(
        tool_name="explore_patient_records",
        tool_parameters={"patient_id": "P1"},
        tool_output=[{"patient_id": "P1"}],
    )
]


def _stub_llm_returning(result_list: PRSResultList, *, tool_calls: list[ToolCall] | None = None) -> StubSpecialistLlm:
    """``tool_calls=None`` means "something was retrieved". Pass an
    explicit ``[]`` to simulate a patient with no data."""
    return StubSpecialistLlm(
        react_result=SpecialistReactResult(
            transcript=[{"role": "assistant", "content": "considered"}],
            tool_calls=_RETRIEVED_ONE_ROW if tool_calls is None else tool_calls,
        ),
        extraction_result=result_list,
    )


class TestTemplateHappyPath:
    async def test_full_pipeline_produces_state_output(self) -> None:
        specialist = _prs_specialist()
        result_list = PRSResultList(
            results=[
                PRSResult(
                    prs_name="PRS_CAD_001",
                    disease_name="Coronary Artery Disease",
                    prs_score=1.2,
                    interpretation="Slightly elevated PRS.",
                )
            ],
            summary="Overall low-to-moderate polygenic risk.",
        )
        tool_call = ToolCall(
            tool_name="get_patient_prs",
            tool_parameters={"patient_id": "P1"},
            tool_output=[
                {
                    "prs_name": "PRS_CAD_001",
                    "disease_name": "Coronary Artery Disease",
                    "prs_score": 1.2,
                    "risk_band": "average",
                    "source": "PGS-1234",
                }
            ],
        )
        llm = _stub_llm_returning(result_list, tool_calls=[tool_call])

        slot_output = await specialist.run(
            inputs=SpecialistInputs(
                patient_id="P1",
                original_query="what's the picture?",
                requested_diseases=None,
            ),
            ctx=ClinicianContext.system(),
            llm=llm,
        )
        assert isinstance(slot_output, PRSStateOutput)
        assert slot_output.status == "completed"
        assert slot_output.errors == []
        assert slot_output.output is not None
        # Provenance was attached to the single result.
        assert len(slot_output.output.results[0].provenance) == 1
        # Model attribution filled in.
        assert (
            slot_output.output.results[0].interpretation_model == "test-model-1"
        )
        assert slot_output.output.summary_model == "test-model-1"

    async def test_react_and_extraction_both_called_once(self) -> None:
        specialist = _prs_specialist()
        result_list = PRSResultList(results=[])
        llm = _stub_llm_returning(result_list)
        await specialist.run(
            inputs=SpecialistInputs(
                patient_id="P1",
                original_query="q",
                requested_diseases=None,
            ),
            ctx=ClinicianContext.system(),
            llm=llm,
        )
        assert len(llm.react_calls) == 1
        assert len(llm.extraction_calls) == 1


class TestNoDataShortCircuit:
    """The 2026-09-11 HG010 guard.

    Patient-scoped tools returned nothing, the ReAct pass said so, and
    the extraction pass returned two fully-specified BRCA1 variants —
    rsIDs, ClinVar accessions, ACMG criteria, none of it real. The
    extraction instruction asserts rows exist ("copy them unchanged")
    while the transcript said none did, and the model resolved the
    contradiction in favour of the instruction.

    With nothing to extract from, the call is not made at all.
    """

    async def test_extraction_not_called_when_no_rows_retrieved(self) -> None:
        specialist = _prs_specialist()
        # The fabrication shape: the stub is *willing* to return results,
        # exactly as the live model did. It must never be asked.
        fabricated = PRSResultList(
            results=[
                PRSResult(
                    prs_name="PRS_INVENTED",
                    disease_name="Coronary Artery Disease",
                    prs_score=2.4,
                )
            ]
        )
        llm = _stub_llm_returning(fabricated, tool_calls=[])

        slot_output = await specialist.run(
            inputs=SpecialistInputs(
                patient_id="P1", original_query="q", requested_diseases=None
            ),
            ctx=ClinicianContext.system(),
            llm=llm,
        )

        assert len(llm.react_calls) == 1
        assert len(llm.extraction_calls) == 0
        assert slot_output.output is not None
        assert slot_output.output.results == []

    async def test_search_only_does_not_count_as_retrieval(self) -> None:
        """``search_*`` reads the reference annotation tables with no
        ``patient_id`` filter, so it returns rows for a patient that does
        not exist. Counting it would defeat the guard in precisely the
        case the guard exists for."""
        specialist = _prs_specialist()
        llm = _stub_llm_returning(
            PRSResultList(
                results=[
                    PRSResult(
                        prs_name="PRS_INVENTED",
                        disease_name="Coronary Artery Disease",
                    )
                ]
            ),
            tool_calls=[
                ToolCall(
                    tool_name="search_prs_annotations",
                    tool_parameters={"prs_name": "PRS313_BC"},
                    tool_output=[{"prs_name": "PRS313_BC", "source": "PGS000004"}],
                )
            ],
        )

        slot_output = await specialist.run(
            inputs=SpecialistInputs(
                patient_id="P1", original_query="q", requested_diseases=None
            ),
            ctx=ClinicianContext.system(),
            llm=llm,
        )

        assert len(llm.extraction_calls) == 0
        assert slot_output.output is not None
        assert slot_output.output.results == []

    async def test_no_rows_reports_absence_not_failure(self) -> None:
        """A successful query returning zero rows is a true negative."""
        specialist = _prs_specialist()
        llm = _stub_llm_returning(PRSResultList(results=[]), tool_calls=[])

        slot_output = await specialist.run(
            inputs=SpecialistInputs(
                patient_id="P1", original_query="q", requested_diseases=None
            ),
            ctx=ClinicianContext.system(),
            llm=llm,
        )

        assert slot_output.status == "completed"
        assert slot_output.errors == []
        assert slot_output.output is not None
        assert "No prs records exist" in (slot_output.output.summary or "")

    async def test_errored_tools_report_failure_not_absence(self) -> None:
        """The distinction that matters clinically: a retrieval failure
        must not be reported as "no findings". We know nothing, and
        saying "none found" would turn not-knowing into a negative
        clinical finding."""
        specialist = _prs_specialist()
        llm = _stub_llm_returning(
            PRSResultList(results=[]),
            tool_calls=[
                ToolCall(
                    tool_name="get_patient_prs",
                    tool_parameters={"patient_id": "P1"},
                    tool_output=[],
                    error="DatabaseUnavailable: Query failed",
                )
            ],
        )

        slot_output = await specialist.run(
            inputs=SpecialistInputs(
                patient_id="P1", original_query="q", requested_diseases=None
            ),
            ctx=ClinicianContext.system(),
            llm=llm,
        )

        assert len(llm.extraction_calls) == 0
        assert slot_output.status == "failed"
        assert slot_output.errors
        assert slot_output.output is not None
        summary = slot_output.output.summary or ""
        assert "could NOT be retrieved" in summary
        assert "not a finding" in summary

    async def test_no_data_summary_is_not_attributed_to_the_model(self) -> None:
        """The summary is written in Python. Stamping the interpretation
        model name on it would attribute a process-authored sentence to
        the LLM — the same false-attribution fault fixed in 67d12af."""
        specialist = _prs_specialist()
        llm = _stub_llm_returning(PRSResultList(results=[]), tool_calls=[])

        slot_output = await specialist.run(
            inputs=SpecialistInputs(
                patient_id="P1", original_query="q", requested_diseases=None
            ),
            ctx=ClinicianContext.system(),
            llm=llm,
        )

        assert slot_output.output is not None
        assert slot_output.output.summary_model is None

    async def test_disease_filter_appears_in_user_message(self) -> None:
        specialist = _prs_specialist()
        llm = _stub_llm_returning(PRSResultList(results=[]))
        await specialist.run(
            inputs=SpecialistInputs(
                patient_id="P1",
                original_query="q",
                requested_diseases=["Alzheimer's disease"],
            ),
            ctx=ClinicianContext.system(),
            llm=llm,
        )
        user_msg = llm.react_calls[0].user_message
        assert "Alzheimer's disease" in user_msg
        assert "Focus on the following diseases only" in user_msg


class TestTemplateFailurePath:
    async def test_react_exception_produces_failed_slot_output(self) -> None:
        specialist = _prs_specialist()

        class BoomLlm:
            async def run_react(self, request: Any) -> Any:
                raise RuntimeError("Compass unavailable")

            async def run_extraction(self, request: Any) -> Any:
                raise AssertionError("should not be reached")

        slot_output = await specialist.run(
            inputs=SpecialistInputs(patient_id="P1", original_query="q", requested_diseases=None),
            ctx=ClinicianContext.system(),
            llm=BoomLlm(),
        )
        assert isinstance(slot_output, PRSStateOutput)
        assert slot_output.status == "failed"
        assert slot_output.output is None
        assert any("Compass unavailable" in e for e in slot_output.errors)

    async def test_extraction_exception_produces_failed_slot_output(self) -> None:
        specialist = _prs_specialist()

        class BadExtractionLlm:
            async def run_react(self, request: Any) -> Any:
                # Rows must come back, or the template short-circuits
                # before extraction and this path is never exercised.
                return SpecialistReactResult(
                    transcript=[], tool_calls=_RETRIEVED_ONE_ROW
                )

            async def run_extraction(self, request: Any) -> Any:
                raise ValueError("schema mismatch")

        slot_output = await specialist.run(
            inputs=SpecialistInputs(patient_id="P1", original_query="q", requested_diseases=None),
            ctx=ClinicianContext.system(),
            llm=BadExtractionLlm(),
        )
        assert slot_output.status == "failed"
        assert any("schema mismatch" in e for e in slot_output.errors)


class TestModelAttribution:
    async def test_already_set_interpretation_model_not_overwritten(self) -> None:
        specialist = _prs_specialist()
        result_list = PRSResultList(
            results=[
                PRSResult(
                    prs_name="X",
                    disease_name="Y",
                    prs_score=1.0,
                    interpretation="Set by extraction LLM.",
                    interpretation_model="upstream-model-99",
                )
            ]
        )
        llm = _stub_llm_returning(result_list)
        out = await specialist.run(
            inputs=SpecialistInputs(patient_id="P1", original_query="q", requested_diseases=None),
            ctx=ClinicianContext.system(),
            llm=llm,
        )
        assert out.output is not None
        # Existing attribution preserved.
        assert (
            out.output.results[0].interpretation_model == "upstream-model-99"
        )
