"""Slice 4 golden-set harness.

Thin adapter that runs one :class:`GoldenItem` through a FastAPI
``TestClient``. Used by :mod:`tests.unit.evals.test_scope_guard_full_golden`
and any future CLI runner.

Not a test runner in its own right — it just delegates to the scorers
and reports pass/fail per item, respecting the ``expected_fail_reason``
field so items awaiting real Compass access do not fail the suite.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from fastapi.testclient import TestClient

from egp_maf.evals.golden import GoldenItem
from egp_maf.evals.scorers import (
    FactSubstringScorer,
    ForbiddenSubstringScorer,
    RefusalShapeScorer,
    ScorerResult,
)


@dataclass(frozen=True)
class GoldenRunResult:
    """Outcome of running one golden item through the harness."""

    item: GoldenItem
    http_status: int
    reply: str
    agents_completed: list[str]
    scores: dict[str, ScorerResult]
    passed: bool
    # True when at least one scorer reports failed but the item carries
    # an ``expected_fail_reason``. Treated as green in aggregate CI.
    expected_fail: bool = False
    error: str | None = None
    raw_body: dict[str, Any] = field(default_factory=dict)


def run_golden_item(
    client: TestClient,
    item: GoldenItem,
    *,
    token: str,
    thread_id: str | None = None,
) -> GoldenRunResult:
    """Drive ``POST /chat`` with ``item`` and score the response."""
    tid = thread_id or f"T-{item.id}"
    resp = client.post(
        "/chat",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "thread_id": tid,
            "patient_id": item.patient_id,
            "message": item.question,
        },
    )
    if resp.status_code != 200:
        return GoldenRunResult(
            item=item,
            http_status=resp.status_code,
            reply="",
            agents_completed=[],
            scores={},
            passed=False,
            expected_fail=item.expected_fail_reason is not None,
            error=f"HTTP {resp.status_code}: {resp.text[:200]}",
            raw_body={},
        )

    body = resp.json()
    reply = body.get("reply", "") or ""
    agents = body.get("agents_completed", []) or []

    scores: dict[str, ScorerResult] = {}
    if item.expected_refusal_substrings or item.tags and "cohort_allowed" in item.tags:
        scores["refusal_shape"] = RefusalShapeScorer().score(
            item, reply=reply, agents_completed=agents
        )
    if item.expected_fact_substrings:
        scores["fact_substring"] = FactSubstringScorer().score(item, reply=reply)
    if item.forbidden_substrings:
        scores["forbidden_substring"] = ForbiddenSubstringScorer().score(
            item, reply=reply
        )

    passed = all(s.passed for s in scores.values()) if scores else True
    expected_fail = (
        not passed and item.expected_fail_reason is not None
    )
    return GoldenRunResult(
        item=item,
        http_status=200,
        reply=reply,
        agents_completed=agents,
        scores=scores,
        passed=passed,
        expected_fail=expected_fail,
        raw_body=body,
    )
