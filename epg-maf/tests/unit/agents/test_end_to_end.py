"""End-to-end workflow test using real :class:`SpecialistExecutor`s.

Wires the orchestration sub-workflow with real specialists that use stub
:class:`SpecialistLlm`s. Confirms the full W04 → W05 handoff: the
placeholder is replaced by the real ``SpecialistExecutor``, which invokes
the ``SpecialistBase`` pipeline and writes a typed payload back onto the
:class:`SpecialistSlot`.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from egp_maf.agents.base import (
    SpecialistInputs,
    SpecialistReactResult,
    ToolCall,
)
from egp_maf.agents.family_history import FamilyHistorySpecialist
from egp_maf.agents.genomic_variants import GenomicVariantsSpecialist
from egp_maf.agents.llm_bridge import StubSpecialistLlm
from egp_maf.agents.pgx import PGXSpecialist
from egp_maf.agents.phenotype import PhenotypeSpecialist
from egp_maf.agents.prs import PRSSpecialist
from egp_maf.agents.registry import SpecialistRegistry
from egp_maf.agents.state_outputs import PRSStateOutput
from egp_maf.config.settings import Settings
from egp_maf.services.provenance import ProvenanceService
from egp_maf.state.clinician_context import ClinicianContext
from egp_maf.state.results.family_history import FamilyHistoryResultList
from egp_maf.state.results.genomic_variants import GenomicVariantsResultList
from egp_maf.state.results.pgx import PGXResultList
from egp_maf.state.results.phenotype import PhenotypeResultList
from egp_maf.state.results.prs import PRSResult, PRSResultList
from egp_maf.workflow.decisions import ChatRouterDecision, SpecialistDispatchSet
from egp_maf.workflow.router_llm import StubOrchRouterLlm, StubRouterLlm
from egp_maf.workflow.runtime import WorkflowRuntime
from egp_maf.workflow.state import ChatWorkflowState, SessionMessage

pytestmark = pytest.mark.unit


import os

os.environ.setdefault("LLM_API_KEY", "test")


def _empty_result_for(name: str) -> object:
    """Empty typed result-list for each domain — the specialist populates
    derived fields but has no rows to interpret."""
    if name == "prs":
        return PRSResultList(results=[])
    if name == "pgx":
        return PGXResultList(patient_id="", results=[])
    if name == "phenotype":
        return PhenotypeResultList(patient_id="", results=[])
    if name == "family_history":
        return FamilyHistoryResultList(patient_id="", results=[])
    if name == "genomic_variants":
        return GenomicVariantsResultList(patient_id="", results=[])
    raise ValueError(name)


def _stub_llm_for(name: str, extraction_result: object | None = None) -> StubSpecialistLlm:
    return StubSpecialistLlm(
        react_result=SpecialistReactResult(transcript=[], tool_calls=[]),
        extraction_result=extraction_result if extraction_result is not None else _empty_result_for(name),
    )


def _build_registry_with_prs_data() -> SpecialistRegistry:
    """A registry where the PRS specialist returns one typed result;
    the other four return empty lists."""
    provenance = ProvenanceService()
    registry = SpecialistRegistry()

    registry.specialists["prs"] = PRSSpecialist(
        system_prompt="test",
        interpretation_model_name="m",
        repository=MagicMock(),
        provenance_service=provenance,
    )
    registry.specialists["genomic_variants"] = GenomicVariantsSpecialist(
        system_prompt="test",
        interpretation_model_name="m",
        repository=MagicMock(),
        provenance_service=provenance,
    )
    registry.specialists["family_history"] = FamilyHistorySpecialist(
        system_prompt="test",
        interpretation_model_name="m",
        repository=MagicMock(),
        provenance_service=provenance,
    )
    registry.specialists["pgx"] = PGXSpecialist(
        system_prompt="test",
        interpretation_model_name="m",
        repository=MagicMock(),
        provenance_service=provenance,
    )
    registry.specialists["phenotype"] = PhenotypeSpecialist(
        system_prompt="test",
        interpretation_model_name="m",
        repository=MagicMock(),
        provenance_service=provenance,
    )

    prs_result_list = PRSResultList(
        results=[
            PRSResult(
                prs_name="PRS_CAD_001",
                disease_name="Coronary Artery Disease",
                prs_score=1.4,
                interpretation="Slightly elevated.",
            )
        ]
    )
    registry.llms["prs"] = StubSpecialistLlm(
        react_result=SpecialistReactResult(
            transcript=[],
            tool_calls=[
                ToolCall(
                    tool_name="get_patient_prs",
                    tool_parameters={"patient_id": "P1"},
                    tool_output=[
                        {"prs_name": "PRS_CAD_001", "prs_score": 1.4}
                    ],
                )
            ],
        ),
        extraction_result=prs_result_list,
    )
    for name in ["genomic_variants", "family_history", "pgx", "phenotype"]:
        registry.llms[name] = _stub_llm_for(name)

    return registry


class TestSpecialistExecutorEndToEnd:
    async def test_prs_specialist_runs_and_writes_payload_to_slot(self) -> None:
        registry = _build_registry_with_prs_data()
        runtime = WorkflowRuntime(
            settings=Settings(),  # type: ignore[call-arg]
            chat_router_llm=StubRouterLlm(
                ChatRouterDecision(needs_clinical_data=True, reason="need data")
            ),
            orch_router_llm=StubOrchRouterLlm(
                [
                    SpecialistDispatchSet(specialists=["prs"], reason="start with prs"),
                    SpecialistDispatchSet(specialists=[], reason="done"),
                ]
            ),
            specialist_registry=registry,
        )

        result = await runtime.run_turn(
            ChatWorkflowState(
                ctx=ClinicianContext.system(),
                patient_id="P1",
                thread_id="T1",
                messages=[
                    SessionMessage(role="user", content="what PRS does this patient have?")
                ],
            )
        )
        outputs = result.get_outputs()
        final = next(o for o in outputs if isinstance(o, ChatWorkflowState))
        assert final.agents_completed == ["prs"]
        assert final.prs is not None
        assert final.prs.status == "completed"
        assert final.prs.output is not None
        # The payload has the shape of a serialised PRSStateOutput.
        assert final.prs.output["status"] == "completed"
        assert final.prs.output["output"]["results"][0]["prs_name"] == "PRS_CAD_001"

    async def test_family_history_specialist_writes_public_projection_only(self) -> None:
        """The workflow slot must carry the public projection — no
        privacy fields should reach the outer state."""
        registry = _build_registry_with_prs_data()
        # Give family_history a non-empty result with private fields set.
        from egp_maf.state.results.family_history import (
            FamilyHistoryCriteriaResult,
        )

        fh_result_list = FamilyHistoryResultList(
            patient_id="",
            results=[
                FamilyHistoryCriteriaResult(
                    disease_name="Breast Cancer",
                    criteria_name="NCCN HBOC",
                    affected_relative_count=2,
                    total_relatives_searched=6,
                    search_context_notes="0 eligible females over 30 in search",
                    meets_threshold=True,
                    interpretation="Meets threshold.",
                )
            ],
        )
        registry.llms["family_history"] = StubSpecialistLlm(
            react_result=SpecialistReactResult(transcript=[], tool_calls=[]),
            extraction_result=fh_result_list,
        )
        runtime = WorkflowRuntime(
            settings=Settings(),  # type: ignore[call-arg]
            chat_router_llm=StubRouterLlm(
                ChatRouterDecision(needs_clinical_data=True, reason="need data")
            ),
            orch_router_llm=StubOrchRouterLlm(
                [
                    SpecialistDispatchSet(specialists=["family_history"], reason="fh"),
                    SpecialistDispatchSet(specialists=[], reason="done"),
                ]
            ),
            specialist_registry=registry,
        )
        result = await runtime.run_turn(
            ChatWorkflowState(
                ctx=ClinicianContext.system(),
                patient_id="P1",
                thread_id="T1",
                messages=[
                    SessionMessage(role="user", content="what's the family history?")
                ],
            )
        )
        final = next(o for o in result.get_outputs() if isinstance(o, ChatWorkflowState))
        assert final.family_history is not None
        assert final.family_history.output is not None
        payload = final.family_history.output
        # Public shape: privacy fields absent from every result.
        for r in payload["output"]["results"]:
            assert "affected_relative_count" not in r
            assert "search_context_notes" not in r
            assert "total_relatives_searched" not in r
