"""W10 — Testing, Evaluation & Load.

Public surface:

- :class:`GoldenItem` — one clinician question + expected tool calls +
  expected structured output shape. Schema documented in
  ``docs/testing/golden-set.md``.
- :func:`load_golden_set` — read bundled + optional external
  golden-set JSON files.
- :class:`ToolCallScorer` — deterministic scorer that compares actual
  tool-call sequence against the golden expectation.
- :class:`InterpretationJudgeScorer` — LLM-as-judge scorer contract.
  W10 ships an interface + a :class:`StubJudge` for deterministic
  tests; Foundry Evaluations wires the real judge (W11).
- :class:`ScorerResult` — {passed, score, reason} envelope shared by
  all scorers.
- :func:`detect_phi_in_export` — grep-style detector that scans a
  string blob (log line, span attributes JSON) for
  ``FORBIDDEN_ATTRIBUTES`` names. Used by the PHI-safety CI gate.
"""

from __future__ import annotations

from egp_maf.evals.golden import GoldenItem, GoldenToolCall, load_golden_set
from egp_maf.evals.phi_detector import (
    PhiFinding,
    PhiScanResult,
    detect_phi_in_export,
)
from egp_maf.evals.scorers import (
    InterpretationJudgeScorer,
    ScorerResult,
    StubJudge,
    ToolCallScorer,
)

__all__ = [
    "GoldenItem",
    "GoldenToolCall",
    "InterpretationJudgeScorer",
    "PhiFinding",
    "PhiScanResult",
    "ScorerResult",
    "StubJudge",
    "ToolCallScorer",
    "detect_phi_in_export",
    "load_golden_set",
]
