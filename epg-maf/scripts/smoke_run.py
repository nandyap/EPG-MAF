"""End-to-end smoke run — no LLM key, no Postgres, no Cosmos.

Wires the workflow with deterministic stubs so you can watch a
clinician turn flow through the whole pipeline (chat router →
orchestration router → 5 specialists → synthesis) and produce a
:class:`ChatWorkflowState` — plus, optionally, exercise the FastAPI
HTTP layer via :class:`fastapi.testclient.TestClient`.

Usage
-----

    cd epg-maf
    .\.venv\Scripts\Activate.ps1
    python scripts\smoke_run.py                    # workflow only
    python scripts\smoke_run.py --http             # + FastAPI Swagger-shaped call
    python scripts\smoke_run.py --scenario multi   # multi-domain scenario

Scenarios
---------

``simple``   — chat router decides no clinical data needed; synthesis stub replies.
``prs``      — orchestration runs the PRS specialist with a canned result.
``multi``    — orchestration runs PRS + PGX in one turn.

When the Compass key lands, flip a single env var to swap the stubs
for real MAF-backed LLMs. See :func:`_note` at the bottom of this
file for the exact instructions.

This script does NOT touch Postgres or Cosmos. Specialist repositories
are stubbed via :class:`unittest.mock.MagicMock` so no DB is needed.
The seeded DuckDB at ``test_data/clinical_genetics.duckdb`` is not
read here (that requires Postgres-backed repositories from W02).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

# Ensure LLM_API_KEY exists so Settings() validation passes even though
# no real key is required for this smoke run.
os.environ.setdefault("LLM_API_KEY", "smoke-run-stub")

# Make the ``tests`` package importable so we can reuse
# ``tests.support.authz_doubles.OpenAuthzPolicy`` — the same test double
# the unit + DI-container tests use.
_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))


def _build_container() -> Any:
    """Construct a fully-wired :class:`Container` using stubs everywhere.

    Mirrors the ``_build_test_container`` helper in the DI test — same
    shape, same fakes, no external services required.
    """
    from egp_maf.agents.family_history import FamilyHistorySpecialist
    from egp_maf.agents.genomic_variants import GenomicVariantsSpecialist
    from egp_maf.agents.llm_bridge import StubSpecialistLlm
    from egp_maf.agents.pgx import PGXSpecialist
    from egp_maf.agents.phenotype import PhenotypeSpecialist
    from egp_maf.agents.prs import PRSSpecialist
    from egp_maf.agents.registry import SpecialistRegistry
    from egp_maf.agents.base import SpecialistReactResult
    from egp_maf.auth.audit import AuditEventEmitter, NullAuditSink
    from egp_maf.auth.authenticator import StubAuthenticator
    from egp_maf.config.settings import Settings
    from egp_maf.di.container import Container
    from egp_maf.infrastructure.compass_client import LlmClientFactory
    from egp_maf.services.provenance import ProvenanceService
    from egp_maf.services.thread_state_memory import InMemoryThreadStateProvider
    from egp_maf.state.results.family_history import FamilyHistoryResultList
    from egp_maf.state.results.genomic_variants import GenomicVariantsResultList
    from egp_maf.state.results.pgx import PGXDrugResult, PGXResultList
    from egp_maf.state.results.phenotype import PhenotypeResultList
    from egp_maf.state.results.prs import PRSResult, PRSResultList
    from egp_maf.telemetry import NullMetricEmitter, build_telemetry_provider
    from egp_maf.workflow.decisions import ChatRouterDecision, SpecialistDispatchSet
    from egp_maf.workflow.chat.synthesize_response import StubSynthesisLlm
    from egp_maf.workflow.router_llm import StubOrchRouterLlm, StubRouterLlm
    from egp_maf.workflow.runtime import WorkflowRuntime
    from tests.support.authz_doubles import OpenAuthzPolicy

    # Slice 1: smoke server uses OpenAuthzPolicy (accepts everything) so
    # the demo Just Works with any patient_id. The seed_allowlist.json
    # sibling file documents the shape for real deployments; wire it in
    # for a stricter demo by swapping to AllowlistAuthzPolicy in
    # _make_container below.
    settings = Settings(  # type: ignore[call-arg]
        auth_stub_enabled=True,
        auth_required_role="Clinician",
    )

    # ── Infra factories (no-op stubs) ────────────────────────────
    class _NoopFactory:
        async def open(self) -> None: ...
        async def close(self) -> None: ...

    class _NoopPrompts:
        async def warm_cache(self) -> None: ...
        def get(self, name: str) -> str:
            return f"[stub prompt for {name}]"

    db_pool = _NoopFactory()
    cosmos = _NoopFactory()
    llm_factory = LlmClientFactory(settings, client_constructor=lambda **_: object())
    prompt_service = _NoopPrompts()
    thread_state = InMemoryThreadStateProvider()

    # ── Specialists with mocked repositories + canned typed results ──
    provenance = ProvenanceService()
    registry = SpecialistRegistry()

    registry.specialists["prs"] = PRSSpecialist(
        system_prompt="[smoke]", interpretation_model_name="stub",
        repository=MagicMock(), provenance_service=provenance,
    )
    registry.specialists["genomic_variants"] = GenomicVariantsSpecialist(
        system_prompt="[smoke]", interpretation_model_name="stub",
        repository=MagicMock(), provenance_service=provenance,
    )
    registry.specialists["family_history"] = FamilyHistorySpecialist(
        system_prompt="[smoke]", interpretation_model_name="stub",
        repository=MagicMock(), provenance_service=provenance,
    )
    registry.specialists["pgx"] = PGXSpecialist(
        system_prompt="[smoke]", interpretation_model_name="stub",
        repository=MagicMock(), provenance_service=provenance,
    )
    registry.specialists["phenotype"] = PhenotypeSpecialist(
        system_prompt="[smoke]", interpretation_model_name="stub",
        repository=MagicMock(), provenance_service=provenance,
    )

    # Canned typed results the extraction stub returns.
    prs_result = PRSResultList(results=[
        PRSResult(
            prs_name="PRS_CAD_001",
            disease_name="Coronary Artery Disease",
            prs_score=1.4,
            interpretation="Elevated relative to population mean.",
        ),
    ])
    pgx_result = PGXResultList(patient_id="P001", results=[
        PGXDrugResult(
            gene="CYP2C9",
            drug="warfarin",
            diplotype="*1/*3",
            phenotype="Intermediate Metaboliser",
            recommendation="Reduce initial dose by 30-50%.",
            interpretation="Reduced metabolism; consider dose adjustment.",
        ),
    ])
    empty = {
        "prs": prs_result,
        "genomic_variants": GenomicVariantsResultList(patient_id="P001", results=[]),
        "family_history": FamilyHistoryResultList(patient_id="P001", results=[]),
        "pgx": pgx_result,
        "phenotype": PhenotypeResultList(patient_id="P001", results=[]),
    }
    for name, result in empty.items():
        registry.llms[name] = StubSpecialistLlm(
            react_result=SpecialistReactResult(transcript=[], tool_calls=[]),
            extraction_result=result,
        )

    return Container, _NoopFactory, _NoopPrompts, {
        "settings": settings,
        "db_pool": db_pool,
        "cosmos": cosmos,
        "llm_factory": llm_factory,
        "prompt_service": prompt_service,
        "thread_state": thread_state,
        "provenance": provenance,
        "registry": registry,
    }


def _make_runtime(*, scenario: str, parts: dict[str, Any]) -> Any:
    from egp_maf.workflow.decisions import ChatRouterDecision, SpecialistDispatchSet
    from egp_maf.workflow.chat.synthesize_response import StubSynthesisLlm
    from egp_maf.workflow.router_llm import StubOrchRouterLlm, StubRouterLlm
    from egp_maf.workflow.runtime import WorkflowRuntime

    if scenario == "simple":
        chat_router = StubRouterLlm(
            ChatRouterDecision(needs_clinical_data=False, reason="chat only")
        )
        orch_router = StubOrchRouterLlm([
            SpecialistDispatchSet(specialists=[], reason="none"),
        ])
    elif scenario == "prs":
        chat_router = StubRouterLlm(
            ChatRouterDecision(needs_clinical_data=True, reason="need clinical data")
        )
        orch_router = StubOrchRouterLlm([
            SpecialistDispatchSet(specialists=["prs"], reason="need PRS"),
            SpecialistDispatchSet(specialists=[], reason="done"),
        ])
    elif scenario == "multi":
        chat_router = StubRouterLlm(
            ChatRouterDecision(needs_clinical_data=True, reason="need multi-domain")
        )
        orch_router = StubOrchRouterLlm([
            SpecialistDispatchSet(specialists=["prs"], reason="need PRS"),
            SpecialistDispatchSet(specialists=["pgx"], reason="need PGX"),
            SpecialistDispatchSet(specialists=[], reason="done"),
        ])
    else:
        raise SystemExit(f"unknown scenario: {scenario}")

    return WorkflowRuntime(
        settings=parts["settings"],
        chat_router_llm=chat_router,
        orch_router_llm=orch_router,
        synthesis_llm=StubSynthesisLlm(
            template="[smoke reply] you asked: {query}"
        ),
        specialist_registry=parts["registry"],
    )


def _make_container(*, scenario: str) -> Any:
    from egp_maf.auth.audit import AuditEventEmitter, NullAuditSink
    from egp_maf.auth.authenticator import StubAuthenticator
    from egp_maf.telemetry import NullMetricEmitter, build_telemetry_provider
    from tests.support.authz_doubles import OpenAuthzPolicy

    Container, _NoopFactory, _NoopPrompts, parts = _build_container()
    runtime = _make_runtime(scenario=scenario, parts=parts)

    audit = AuditEventEmitter(sink=NullAuditSink())
    return Container(
        settings=parts["settings"],
        db_pool_factory=parts["db_pool"],  # type: ignore[arg-type]
        cosmos_client_factory=parts["cosmos"],  # type: ignore[arg-type]
        llm_client_factory=parts["llm_factory"],
        prompt_service=parts["prompt_service"],  # type: ignore[arg-type]
        thread_state_provider=parts["thread_state"],
        provenance_service=parts["provenance"],
        authz_policy=OpenAuthzPolicy(),
        audit_emitter=audit,
        authenticator=StubAuthenticator(settings=parts["settings"], audit=audit),
        telemetry_provider=build_telemetry_provider(parts["settings"]),
        metric_emitter=NullMetricEmitter(),
        specialist_registry=parts["registry"],
        workflow_runtime=runtime,
    )


async def _run_workflow_scenario(scenario: str) -> None:
    """Drive the workflow directly (no HTTP)."""
    from egp_maf.state.clinician_context import ClinicianContext
    from egp_maf.workflow.state import ChatWorkflowState, SessionMessage

    print(f"\n=== Workflow scenario: {scenario} ===")
    container = _make_container(scenario=scenario)

    query = {
        "simple": "Hi, how does this system work?",
        "prs": "What polygenic risk scores does patient P001 have?",
        "multi": "Give me a combined risk + pharmacogenomics picture for P001.",
    }[scenario]

    initial = ChatWorkflowState(
        ctx=ClinicianContext.system(),
        patient_id="P001",
        thread_id=f"smoke-{scenario}",
        original_query=query,
        messages=[SessionMessage(role="user", content=query)],
    )

    result = await container.workflow_runtime.run_turn(initial)
    final = next(
        o for o in result.get_outputs()
        if isinstance(o, ChatWorkflowState)
    )

    print(f"\nquery: {query}")
    print(f"agents_completed: {final.agents_completed}")
    print(f"reply: {_last_assistant(final.messages)}")
    for name in ("prs", "genomic_variants", "family_history", "pgx", "phenotype"):
        slot = getattr(final, name)
        if slot is not None:
            print(f"  {name}: status={slot.status}, output_keys={list((slot.output or {}).keys())}")


def _last_assistant(messages: list[Any]) -> str:
    for msg in reversed(messages):
        if getattr(msg, "role", None) == "assistant":
            return getattr(msg, "content", "")
    return "(no assistant reply)"


def _run_http_scenario(scenario: str) -> None:
    """Drive the FastAPI /chat route via TestClient."""
    from fastapi.testclient import TestClient
    from egp_maf.api import create_app

    print(f"\n=== HTTP scenario: {scenario} ===")
    container = _make_container(scenario=scenario)
    app = create_app(container)
    client = TestClient(app)

    # Stub-authenticator eats a JSON claim dict as the bearer token.
    token = json.dumps({
        "oid": "smoke-user",
        "tid": "smoke-tenant",
        "roles": ["Clinician"],
        "exp": 9999999999,
    })

    resp = client.get("/healthz")
    print(f"GET /healthz -> {resp.status_code} {resp.json()}")

    query = {
        "simple": "Hi, how does this system work?",
        "prs": "What polygenic risk scores does patient P001 have?",
        "multi": "Give me a combined risk + pharmacogenomics picture for P001.",
    }[scenario]

    resp = client.post(
        "/chat",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "thread_id": f"smoke-http-{scenario}",
            "patient_id": "P001",
            "message": query,
        },
    )
    print(f"POST /chat -> {resp.status_code}")
    print(json.dumps(resp.json(), indent=2, default=str))


def _note() -> None:
    print("""
-----------------------------------------------------------------
When the Compass / OpenAI key arrives:

  1. Set LLM_API_KEY (and LLM_BASE_URL if not Compass) in your env.
  2. Replace this script's call to _build_container / _make_container
     with egp_maf.di.container.build_container(). That factory
     produces the SAME Container shape but with real MAF-backed
     LLMs and real repositories (Postgres - see README for the
     seeder). The workflow topology is identical.

The stub scenarios here exercise every executor, every span, every
error handler, and every response schema field - they just don't
call a real LLM.
-----------------------------------------------------------------
""")


def main() -> None:
    parser = argparse.ArgumentParser(description="EGP Window smoke run")
    parser.add_argument(
        "--scenario",
        choices=["simple", "prs", "multi", "all"],
        default="all",
        help="Which scenario(s) to run (default: all).",
    )
    parser.add_argument(
        "--http",
        action="store_true",
        help="Also drive the FastAPI /chat route via TestClient.",
    )
    args = parser.parse_args()

    scenarios = ["simple", "prs", "multi"] if args.scenario == "all" else [args.scenario]

    for scenario in scenarios:
        asyncio.run(_run_workflow_scenario(scenario))
        if args.http:
            _run_http_scenario(scenario)

    _note()


if __name__ == "__main__":
    main()
