"""Golden question set — F12.1.

Design §27.2 defines the golden set as the source-of-truth for
regression and pre-release evaluation. Each item pins:

- The clinician question (plain text).
- The patient the question is asked against.
- The expected tool-call *set* — a permutation-tolerant list of
  ``(tool_name, tool_parameters)`` pairs the specialist should have
  invoked. Order is significant only when a downstream call depends
  on the output of an earlier one; per-tool ordering is captured via
  the ``depends_on`` field (a rare edge case, so default is order-free).
- The expected structured-output shape — a subset of keys the final
  slot payload must contain. We do NOT pin the natural-language
  interpretation here (that's the LLM-as-judge scorer's job).
- Optional tags for filtering (``domain``, ``edge_case``, etc.).

The bundled JSON files live under
``src/egp_maf/evals/golden/*.json`` and are loaded by
:func:`load_golden_set`. Callers can pass an override path to load a
private / larger golden set from disk without touching the package.
"""

from __future__ import annotations

import json
from importlib import resources
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

# Package-relative resource root for bundled JSON fixtures.
_BUNDLED_ROOT_PACKAGE = "egp_maf.evals.golden_set"


class GoldenToolCall(BaseModel):
    """One expected tool invocation."""

    tool_name: str = Field(..., min_length=1)
    tool_parameters: dict[str, Any] = Field(default_factory=dict)
    # Optional ordering constraint: this call must happen AFTER any
    # tool named in ``depends_on``. Empty list = order-free w.r.t. others.
    depends_on: list[str] = Field(default_factory=list)

    model_config = ConfigDict(extra="forbid")


class GoldenItem(BaseModel):
    """One item in the golden set."""

    id: str = Field(..., min_length=1)
    domain: str = Field(..., min_length=1)  # prs | genomic_variants | pgx | phenotype | family_history | multi | scope_guard
    question: str = Field(..., min_length=1)
    patient_id: str = Field(..., min_length=1)
    expected_tool_calls: list[GoldenToolCall] = Field(default_factory=list)
    # Subset of keys the final specialist-slot payload must carry
    # (e.g. ``["output", "output.results"]``). Dotted-path notation;
    # values not compared here — the LLM-judge scorer covers that.
    expected_output_keys: list[str] = Field(default_factory=list)
    # Slice 3: refusal-shape items assert that ``reply`` contains
    # every substring in ``expected_refusal_substrings`` (case-insensitive)
    # and that ``agents_completed`` is empty.
    expected_refusal_substrings: list[str] = Field(default_factory=list)
    # Slice 4: content-shape assertions on the reply text.
    # ``expected_fact_substrings`` are substrings that MUST appear
    # (case-insensitive). ``forbidden_substrings`` are substrings that
    # MUST NOT appear (case-sensitive so PHI matches are exact).
    # Zero-tolerance policy on the forbidden list — one match is a
    # hard fail.
    expected_fact_substrings: list[str] = Field(default_factory=list)
    forbidden_substrings: list[str] = Field(default_factory=list)
    # Free-form tags for filtering (``edge_case``, ``privacy``,
    # ``multi_domain``, ``dispatch_mode_parity``, ``scope_guard``,
    # ``cohort_allowed``, ``noeval_disclosure``, ``phi_redaction``,
    # ``cross_domain``, ``awaiting-compass``, etc.).
    tags: list[str] = Field(default_factory=list)
    # Slice 4: items whose passing requires the real Compass LLM.
    # When set, the harness treats a failing content-scorer as an
    # expected-fail rather than a real failure. Cleared once the LLM
    # key arrives and the item genuinely passes.
    expected_fail_reason: str | None = None
    # BIX sign-off metadata. Empty until the SME approves.
    bix_reviewed: bool = False
    bix_reviewer: str | None = None
    bix_review_date: str | None = None  # ISO-8601 date

    model_config = ConfigDict(extra="forbid")


def load_golden_set(
    *,
    external_path: Path | None = None,
    include_bundled: bool = True,
) -> list[GoldenItem]:
    """Return the merged golden set from bundled + optional external.

    Parameters
    ----------
    external_path:
        Optional path to a directory containing additional ``*.json``
        golden-set files. Each file must be a JSON array of GoldenItem
        objects. Ids must be unique across all files (bundled +
        external).
    include_bundled:
        Set False to skip the bundled seed set (used by tests that want
        to isolate their own fixtures).
    """
    items: list[GoldenItem] = []
    seen_ids: set[str] = set()

    def _extend(source: str, raw: list[dict[str, Any]]) -> None:
        for entry in raw:
            item = GoldenItem.model_validate(entry)
            if item.id in seen_ids:
                raise ValueError(
                    f"Duplicate golden-set id '{item.id}' (source={source})"
                )
            seen_ids.add(item.id)
            items.append(item)

    if include_bundled:
        try:
            pkg = resources.files(_BUNDLED_ROOT_PACKAGE)
        except (ModuleNotFoundError, FileNotFoundError):
            pkg = None
        if pkg is not None:
            for entry in pkg.iterdir():
                if entry.is_file() and entry.name.endswith(".json"):
                    with entry.open("r", encoding="utf-8") as fh:
                        _extend(entry.name, json.load(fh))

    if external_path is not None:
        for path in sorted(external_path.glob("*.json")):
            with path.open("r", encoding="utf-8") as fh:
                _extend(str(path), json.load(fh))

    return items
