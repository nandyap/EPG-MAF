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


def _stub_llm_returning(result_list: PRSResultList, *, tool_calls: list[ToolCall] | None = None) -> StubSpecialistLlm:
    return StubSpecialistLlm(
        react_result=SpecialistReactResult(
            transcript=[{"role": "assistant", "content": "considered"}],
            tool_calls=tool_calls or [],
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
                return SpecialistReactResult(transcript=[], tool_calls=[])

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
