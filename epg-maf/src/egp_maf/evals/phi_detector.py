"""PHI-safety detector — F12.7.

Grep-style detector that scans a blob (a log line, a span-attributes
JSON dump, an exported OTEL trace) for the exact
:data:`FORBIDDEN_ATTRIBUTES` names delivered in W08.

This is a *complement* to the runtime enforcement in
:func:`egp_maf.telemetry.phi_safe.safe_set_attribute`. That function
prevents forbidden attributes from ever being written to a live span;
this detector catches:

- Forbidden names that were serialised through a different path (e.g.
  a structured-log field that bypassed ``safe_set_attribute``).
- Regressions where a developer adds a new attribute name that
  overlaps with the forbidden set.

The CI job runs the golden set end-to-end, captures the exported
span/log records, and calls :func:`detect_phi_in_export` on each. Any
finding fails the build.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Iterable

from egp_maf.telemetry.attributes import FORBIDDEN_ATTRIBUTES


@dataclass(frozen=True)
class PhiFinding:
    """One occurrence of a forbidden attribute name in exported data."""

    attribute: str
    context: str  # short snippet around the match


@dataclass
class PhiScanResult:
    """Scan outcome; iterate :attr:`findings` for detail."""

    findings: list[PhiFinding] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.findings

    def raise_if_findings(self) -> None:
        """Raise ``AssertionError`` when :attr:`findings` is non-empty."""
        if self.findings:
            summary = "; ".join(
                f"{f.attribute} @ {f.context!r}" for f in self.findings[:5]
            )
            more = "" if len(self.findings) <= 5 else f" (+{len(self.findings) - 5} more)"
            raise AssertionError(
                f"PHI-safety CI: forbidden attribute leak — {summary}{more}"
            )


# Build a single OR-regex once — order the alternatives from longest
# to shortest so ``messages.content`` matches before ``message.content``.
def _build_regex(names: Iterable[str]) -> re.Pattern[str]:
    ordered = sorted(names, key=len, reverse=True)
    pattern = r"\b(" + "|".join(re.escape(n) for n in ordered) + r")\b"
    return re.compile(pattern)


_DEFAULT_REGEX: re.Pattern[str] = _build_regex(FORBIDDEN_ATTRIBUTES)


def detect_phi_in_export(
    blob: str,
    *,
    forbidden: Iterable[str] | None = None,
    context_window: int = 40,
) -> PhiScanResult:
    """Scan ``blob`` for any of ``forbidden``.

    Parameters
    ----------
    blob:
        Arbitrary string (log line, JSON dump, streaming text). Not
        interpreted — we simply grep for the forbidden names.
    forbidden:
        Optional override. Default is :data:`FORBIDDEN_ATTRIBUTES` from
        W08.
    context_window:
        Number of characters before/after each match captured in
        :attr:`PhiFinding.context` (bounded to blob length).
    """
    regex = _build_regex(forbidden) if forbidden is not None else _DEFAULT_REGEX
    result = PhiScanResult()
    for match in regex.finditer(blob):
        start = max(0, match.start() - context_window)
        end = min(len(blob), match.end() + context_window)
        result.findings.append(
            PhiFinding(attribute=match.group(1), context=blob[start:end])
        )
    return result
