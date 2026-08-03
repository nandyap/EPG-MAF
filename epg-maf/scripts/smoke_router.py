"""Keyword-based orch-router stub for the smoke server (Slice 2).

The production orchestration router is a real LLM behind
:class:`egp_maf.workflow.router_llm.OrchRouterLlm`. The smoke server
runs without an LLM key so it needs a deterministic replacement that
still *looks* like realistic routing to non-technical demo audiences.

This stub inspects the ``original_query`` for coarse keyword patterns
and emits a plausible :class:`SpecialistDispatchSet`:

- broad ("comprehensive", "everything", "combined", "all", "profile"
  in isolation) → all five specialists.
- PRS keywords → ``prs``.
- Variant keywords → ``genomic_variants``.
- Family history keywords → ``family_history``.
- PGx / drug-gene keywords → ``pgx``.
- Phenotype / diagnosis keywords → ``phenotype``.

Multiple keyword families dispatch a set. Anything else falls through
to a terminal empty dispatch (chat router will synthesise from cache /
respond directly).

**Never used in production.** Import path is ``scripts.smoke_router``.
"""

from __future__ import annotations

import re

from egp_maf.workflow.decisions import SpecialistDispatchSet


_KEYWORDS: dict[str, list[re.Pattern[str]]] = {
    "prs": [
        re.compile(r"\bprs\b", re.I),
        re.compile(r"\bpolygenic\b", re.I),
        re.compile(r"\brisk score\b", re.I),
    ],
    "genomic_variants": [
        re.compile(r"\bvariant\b", re.I),
        re.compile(r"\bvariants\b", re.I),
        re.compile(r"\bmutation\b", re.I),
        re.compile(r"\bpathogen\w*\b", re.I),
        re.compile(r"\bbrca[12]?\b", re.I),
        re.compile(r"\bmsh[26]\b", re.I),
        re.compile(r"\bldlr\b", re.I),
        re.compile(r"\bgene\b", re.I),
    ],
    "family_history": [
        re.compile(r"\bfamily history\b", re.I),
        re.compile(r"\bpedigree\b", re.I),
        re.compile(r"\bhereditary\b", re.I),
        re.compile(r"\bkinship\b", re.I),
        re.compile(r"\brelatives?\b", re.I),
    ],
    "pgx": [
        re.compile(r"\bpgx\b", re.I),
        re.compile(r"\bpharmacog\w*\b", re.I),
        re.compile(r"\bmetaboli\w*\b", re.I),
        re.compile(r"\bdrug\b", re.I),
        re.compile(r"\bdrugs\b", re.I),
        re.compile(r"\bcyp\w*\b", re.I),
        re.compile(r"\bwarfarin\b", re.I),
        re.compile(r"\bcodeine\b", re.I),
        re.compile(r"\bclopidogrel\b", re.I),
        re.compile(r"\bsimvastatin\b", re.I),
        re.compile(r"\btpmt\b", re.I),
        re.compile(r"\bdpyd\b", re.I),
        re.compile(r"\bslco1b1\b", re.I),
    ],
    "phenotype": [
        re.compile(r"\bphenotype\b", re.I),
        re.compile(r"\bdiagnos\w*\b", re.I),
        re.compile(r"\bcondition\b", re.I),
        re.compile(r"\bhpo\b", re.I),
        re.compile(r"\bmondo\b", re.I),
    ],
}

_BROAD_PATTERNS = [
    re.compile(r"\bcomprehensive\b", re.I),
    re.compile(r"\beverything\b", re.I),
    re.compile(r"\bcomplete profile\b", re.I),
    re.compile(r"\ball findings\b", re.I),
    re.compile(r"\bfull report\b", re.I),
    re.compile(r"\bcombined\b", re.I),
    re.compile(r"\bacross all domains\b", re.I),
]

_ALL_SPECIALISTS = ["prs", "genomic_variants", "family_history", "pgx", "phenotype"]


def _detect(query: str) -> list[str]:
    """Return the specialists implied by ``query`` in a deterministic order."""
    if not query:
        return []
    for pat in _BROAD_PATTERNS:
        if pat.search(query):
            return list(_ALL_SPECIALISTS)
    matched: list[str] = []
    for name, patterns in _KEYWORDS.items():
        if any(pat.search(query) for pat in patterns):
            matched.append(name)
    return matched


class KeywordSmokeOrchRouterLlm:
    """Smoke-only implementation of :class:`OrchRouterLlm`.

    Emits one dispatch per iteration (compatible with the default
    ``ORCH_DISPATCH_MODE=sequential`` + ``ORCH_MAX_FANOUT_WIDTH=1``
    settings): pick the first keyword-matched specialist not yet in
    ``agents_completed`` and dispatch it. When all matched specialists
    are done, emit a terminal empty dispatch.
    """

    def __init__(self) -> None:
        self._call_count = 0

    async def decide_dispatch(
        self,
        *,
        original_query: str,
        agents_completed: list[str],
        requested_diseases: list[str] | None,
    ) -> SpecialistDispatchSet:
        self._call_count += 1
        detected = _detect(original_query)
        remaining = [s for s in detected if s not in agents_completed]
        if not remaining:
            return SpecialistDispatchSet(
                specialists=[],
                reason="smoke-router.done" if detected else "smoke-router.no-keyword-match",
                requested_diseases=requested_diseases,
            )
        # Sequential-friendly: one specialist per iteration.
        next_up = remaining[0]
        return SpecialistDispatchSet(
            specialists=[next_up],
            reason=f"smoke-router.dispatch={next_up}",
            requested_diseases=requested_diseases,
        )

    @property
    def call_count(self) -> int:
        return self._call_count
