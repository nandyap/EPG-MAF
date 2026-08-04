"""``ScopeGuard`` — deterministic single-patient scope enforcement.

Runs *before* the workflow on every ``POST /chat`` (see
:func:`egp_maf.api.app._enforce_scope`). Detects two refusal signals:

- **Cross-patient reference** (golden items G1, G4). The message
  names a patient ID that differs from the session-pinned patient.
  Refuses with :func:`cross_patient_refusal`.
- **Cohort-scan intent** (golden items G2, G3, G5, R23, R24). The
  message asks for a count or comparison across patient rows.
  Refuses with :func:`cohort_scan_refusal`.

**Annotation-legitimate cohort questions** (G6, G7 — "how common is my
variant in EGP", "what CPIC recommendation for CYP2C19 PMs") are
*allowed*: they can be answered from the shared annotation tables
(``variant_annotations``, ``pgx_annotations`` …) without touching any
other patient's records. The specialists' prompts (Slice 3, part 2)
tell each LLM which cohort questions map to annotation lookups.

Design notes:

- **Deterministic first, LLM fallback deferred.** No LLM call — the
  guard runs synchronously in the API layer. Documented in
  ``docs/adr/ADR-016-scope-guard.md``.
- **Fail-open with audit.** If both signals match, the cross-patient
  refusal wins (its wording is more actionable). If only one matches,
  that one is used.
- **Configurable ID patterns via ``SCOPE_GUARD_ID_PATTERNS``** (comma-
  separated regex list). Defaults cover the three formats visible in
  the golden dataset plus the production ``PGP\\d+`` namespace confirmed
  in B-003.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Iterable, Literal

from egp_maf.security.refusal_templates import (
    cohort_scan_refusal,
    cross_patient_refusal,
)


# ── Default regex patterns ──────────────────────────────────────────

# Word-boundary anchored so "68_69delAG" doesn't false-positive against
# a loose numeric pattern.
_DEFAULT_ID_PATTERNS: tuple[str, ...] = (
    r"\bPGP\d+\b",       # Production namespace (B-003 answer).
    r"\bHG\d{5}\b",      # 1000 Genomes (golden dataset test IDs).
    r"\bNA\d{5}\b",      # 1000 Genomes (golden dataset test IDs).
)

# Cohort-scan intent keywords. These require *counting* or *scanning*
# patient rows. They must be paired with a plural noun ("patients") or
# clearly-collective language ("cohort", "database", "carriers") to
# avoid false-positives on single-patient phrasing.
_COHORT_SCAN_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\bhow many\s+patients?\b", re.I),
    re.compile(r"\bhow many\s+carriers?\b", re.I),
    re.compile(r"\bwhat\s+percentage\s+of\s+patients?\b", re.I),
    re.compile(r"\bwhat\s+proportion\s+of\s+(?:the\s+)?(?:cohort|patients?)\b", re.I),
    re.compile(r"\bmost\s+common\s+.+\s+in\s+(?:this\s+)?(?:database|cohort)\b", re.I),
    re.compile(r"\bcompare\b.{0,80}?\bto\s+other\s+patients?\b", re.I),
    re.compile(r"\bcompare\b.{0,80}?\bacross\s+(?:the\s+)?(?:cohort|patients?)\b", re.I),
    re.compile(r"\bacross\s+all\s+patients?\b", re.I),
    re.compile(r"\bacross\s+(?:the\s+)?cohort\b", re.I),
)


# ── Decision object ────────────────────────────────────────────────


@dataclass(frozen=True)
class ScopeDecision:
    """The verdict of :meth:`ScopeGuard.check`."""

    action: Literal["allow", "refuse"]
    refusal_message: str | None = None
    reason: str = ""
    matched_ids: list[str] = field(default_factory=list)

    def is_refusal(self) -> bool:
        return self.action == "refuse"


# ── The guard ───────────────────────────────────────────────────────


class ScopeGuard:
    """Deterministic single-patient scope enforcement.

    ``id_patterns`` is a sequence of regex source strings; each is
    compiled with ``re.IGNORECASE`` and word-boundary anchoring is
    assumed to be baked into the pattern (see ``_DEFAULT_ID_PATTERNS``).
    ``cohort_patterns`` is optional — callers rarely override it; kept
    injectable for tests.
    """

    def __init__(
        self,
        *,
        id_patterns: Iterable[str] | None = None,
        cohort_patterns: Iterable[re.Pattern[str]] | None = None,
    ) -> None:
        raw = tuple(id_patterns) if id_patterns is not None else _DEFAULT_ID_PATTERNS
        self._id_regexes: tuple[re.Pattern[str], ...] = tuple(
            re.compile(p, re.IGNORECASE) for p in raw
        )
        self._cohort_regexes: tuple[re.Pattern[str], ...] = tuple(
            cohort_patterns if cohort_patterns is not None else _COHORT_SCAN_PATTERNS
        )

    def check(
        self,
        *,
        message: str,
        session_patient_id: str,
    ) -> ScopeDecision:
        """Return the guard's verdict for ``message``.

        Cross-patient always wins over cohort-scan when both trigger.
        """
        if not message:
            return ScopeDecision(action="allow", reason="empty message")

        # 1. Cross-patient ID reference.
        matched = self._find_ids(message)
        foreign = [i for i in matched if i.casefold() != session_patient_id.casefold()]
        if foreign:
            return ScopeDecision(
                action="refuse",
                refusal_message=cross_patient_refusal(session_patient_id),
                reason=f"cross_patient:{','.join(foreign)}",
                matched_ids=foreign,
            )

        # 2. Cohort-scan intent.
        for pat in self._cohort_regexes:
            m = pat.search(message)
            if m:
                return ScopeDecision(
                    action="refuse",
                    refusal_message=cohort_scan_refusal(session_patient_id),
                    reason=f"cohort_scan:{pat.pattern}",
                )

        return ScopeDecision(action="allow", reason="no scope violation")

    def _find_ids(self, message: str) -> list[str]:
        """Return all recognised patient IDs mentioned in ``message``."""
        matches: list[str] = []
        for regex in self._id_regexes:
            matches.extend(regex.findall(message))
        # Preserve order of first appearance without duplicates.
        seen: set[str] = set()
        out: list[str] = []
        for m in matches:
            key = m.casefold()
            if key not in seen:
                seen.add(key)
                out.append(m)
        return out


def build_scope_guard_from_settings(setting_value: str | None) -> ScopeGuard:
    """Construct a :class:`ScopeGuard` from a comma-separated env string.

    Empty / ``None`` → default patterns. Wired into the DI container.
    """
    if not setting_value:
        return ScopeGuard()
    patterns = [p.strip() for p in setting_value.split(",") if p.strip()]
    if not patterns:
        return ScopeGuard()
    return ScopeGuard(id_patterns=patterns)
