"""Tests for the Slice 2 keyword-driven smoke router.

The smoke router is NOT production code — it lives in the ``scripts/``
tree. These tests document the demo-time routing behaviour so the
Swagger demo remains predictable.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

# Load smoke_router.py directly from the scripts/ folder without
# polluting sys.path.
_ROUTER_PATH = (
    Path(__file__).resolve().parents[3] / "scripts" / "smoke_router.py"
)
_spec = importlib.util.spec_from_file_location(
    "egp_smoke_router", _ROUTER_PATH
)
assert _spec is not None and _spec.loader is not None
_module = importlib.util.module_from_spec(_spec)
sys.modules["egp_smoke_router"] = _module
_spec.loader.exec_module(_module)

KeywordSmokeOrchRouterLlm = _module.KeywordSmokeOrchRouterLlm
_detect = _module._detect

pytestmark = pytest.mark.unit


class TestDetectKeywords:
    def test_empty_query(self) -> None:
        assert _detect("") == []

    def test_no_match(self) -> None:
        assert _detect("hello, how are you today?") == []

    def test_prs_keyword(self) -> None:
        assert _detect("what PRS does this patient have?") == ["prs"]

    def test_variant_keywords(self) -> None:
        assert "genomic_variants" in _detect("does this patient carry a BRCA1 variant?")

    def test_family_history_keywords(self) -> None:
        assert "family_history" in _detect("summarise the family history for this patient")

    def test_pgx_keywords(self) -> None:
        assert "pgx" in _detect("any warfarin interactions?")

    def test_phenotype_keywords(self) -> None:
        assert "phenotype" in _detect("list this patient's diagnoses")

    def test_broad_keyword_dispatches_all(self) -> None:
        assert _detect("give me a comprehensive report") == [
            "prs",
            "genomic_variants",
            "family_history",
            "pgx",
            "phenotype",
        ]

    def test_multi_keyword_query(self) -> None:
        result = _detect("show me the BRCA variants and any warfarin drug interactions")
        assert "genomic_variants" in result
        assert "pgx" in result


class TestKeywordSmokeOrchRouterLlm:
    @pytest.mark.asyncio
    async def test_dispatches_one_at_a_time_then_terminates(self) -> None:
        """Sequential-mode compatible: one specialist per call, then empty."""
        router = KeywordSmokeOrchRouterLlm()

        first = await router.decide_dispatch(
            original_query="show me the BRCA variants and warfarin interactions",
            agents_completed=[],
            requested_diseases=None,
        )
        assert len(first.specialists) == 1

        # Simulate the joiner adding the first back to agents_completed.
        second = await router.decide_dispatch(
            original_query="show me the BRCA variants and warfarin interactions",
            agents_completed=list(first.specialists),
            requested_diseases=None,
        )
        assert len(second.specialists) == 1
        assert second.specialists[0] != first.specialists[0]

        # After both are done → terminal.
        third = await router.decide_dispatch(
            original_query="show me the BRCA variants and warfarin interactions",
            agents_completed=list(first.specialists) + list(second.specialists),
            requested_diseases=None,
        )
        assert third.specialists == []

    @pytest.mark.asyncio
    async def test_no_keyword_terminates_immediately(self) -> None:
        router = KeywordSmokeOrchRouterLlm()
        decision = await router.decide_dispatch(
            original_query="hi",
            agents_completed=[],
            requested_diseases=None,
        )
        assert decision.specialists == []

    @pytest.mark.asyncio
    async def test_passes_requested_diseases_through(self) -> None:
        router = KeywordSmokeOrchRouterLlm()
        decision = await router.decide_dispatch(
            original_query="what PRS?",
            agents_completed=[],
            requested_diseases=["Alzheimer"],
        )
        assert decision.requested_diseases == ["Alzheimer"]
