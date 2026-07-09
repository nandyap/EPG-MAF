"""Prompt parity — the bundle must match the LangGraph prototype byte-for-byte,
except for the one documented change: the duplicated rule 6 in
``MAIN_AGENT_SYSTEM`` (Design §15.5).

Locates the prototype prompts at ``<repo-root>/agents/*/prompts/prompt.py``.
Skips silently if the prototype is not present alongside this checkout.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from egp_maf.prompts.bundle import PROMPT_BUNDLE

# ── Locate the prototype relative to this file ───────────────────────
#   epg-maf/tests/parity/test_prompt_parity.py
#   epg-maf/tests
#   epg-maf
#   <workspace root>              ← parents[3]
#   <workspace root>/agents/...
_HERE = Path(__file__).resolve()
_WORKSPACE = _HERE.parents[3]
_PROTOTYPE_AGENTS = _WORKSPACE / "agents"


PROMPT_MAP: dict[str, tuple[Path, str]] = {
    "chat_router": (_PROTOTYPE_AGENTS / "chat/prompts/prompt.py", "CHAT_ROUTER_SYSTEM"),
    "chat_synthesis": (_PROTOTYPE_AGENTS / "chat/prompts/prompt.py", "CHAT_SYNTHESIS_SYSTEM"),
    "main_agent": (_PROTOTYPE_AGENTS / "main/prompts/prompt.py", "MAIN_AGENT_SYSTEM"),
    "prs_agent": (_PROTOTYPE_AGENTS / "prs/prompts/prompt.py", "PRS_AGENT_SYSTEM_PROMPT"),
    "genomic_variants_agent": (
        _PROTOTYPE_AGENTS / "genomic_variants/prompts/prompt.py",
        "GENOMIC_VARIANTS_AGENT_SYSTEM_PROMPT",
    ),
    "family_history_agent": (
        _PROTOTYPE_AGENTS / "family_history/prompts/prompt.py",
        "FAMILY_HISTORY_AGENT_SYSTEM_PROMPT",
    ),
    "pgx_agent": (_PROTOTYPE_AGENTS / "pgx/prompts/prompt.py", "PGX_AGENT_SYSTEM_PROMPT"),
    "phenotype_agent": (
        _PROTOTYPE_AGENTS / "phenotype/prompts/prompt.py",
        "PHENOTYPE_AGENT_SYSTEM_PROMPT",
    ),
}


def _extract_prompt_from_file(file_path: Path, symbol: str) -> str:
    """Extract a triple-quoted string constant from a Python file.

    Handles the two prototype forms:

        NAME = \"\"\"..."\"\"      (single-line closer)
        NAME = \"\"\"\\
        ...
        \"\"\"                     (backslash continuation on line 1)
    """
    source = file_path.read_text(encoding="utf-8")
    # Match ``NAME = """[optional backslash+newline]<body>"""``.
    pattern = re.compile(
        rf'{re.escape(symbol)}\s*=\s*"""(?:\\\n)?(.*?)"""',
        re.DOTALL,
    )
    match = pattern.search(source)
    if match is None:
        raise AssertionError(
            f"Could not locate {symbol} in {file_path}. "
            f"Prototype file layout may have changed."
        )
    return match.group(1)


def _requires_prototype() -> pytest.MarkDecorator:
    if not _PROTOTYPE_AGENTS.exists():
        return pytest.mark.skip(
            reason=f"LangGraph prototype not found at {_PROTOTYPE_AGENTS}"
        )
    return pytest.mark.parity


@_requires_prototype()
class TestPromptBundleParity:
    def test_every_bundled_prompt_has_a_prototype_source(self) -> None:
        for name in PROMPT_BUNDLE:
            assert name in PROMPT_MAP, f"No mapping declared for prompt '{name}'"

    def test_chat_prompts_match_prototype_byte_for_byte(self) -> None:
        for name in ("chat_router", "chat_synthesis"):
            src_file, symbol = PROMPT_MAP[name]
            expected = _extract_prompt_from_file(src_file, symbol)
            actual = PROMPT_BUNDLE[name]
            assert actual == expected, f"prompt {name} does not match prototype"

    def test_specialist_prompts_match_prototype_byte_for_byte(self) -> None:
        for name in (
            "prs_agent",
            "genomic_variants_agent",
            "family_history_agent",
            "pgx_agent",
            "phenotype_agent",
        ):
            src_file, symbol = PROMPT_MAP[name]
            expected = _extract_prompt_from_file(src_file, symbol)
            actual = PROMPT_BUNDLE[name]
            assert actual == expected, f"prompt {name} does not match prototype"

    def test_main_agent_matches_prototype_except_for_rule_6_dupe(self) -> None:
        """The only intentional change (Design §15.5): remove the duplicated
        rule 6 from ``MAIN_AGENT_SYSTEM``.

        We construct the *expected* text by taking the prototype's string and
        removing the second copy of the rule-6 block.
        """
        src_file, symbol = PROMPT_MAP["main_agent"]
        prototype = _extract_prompt_from_file(src_file, symbol)

        # Assert the prototype has the duplicated rule 6 (guardrail — if
        # someone fixes the prototype we should update this test).
        rule6_block = (
            '6. If the query is broad (e.g. "overall genetic risk") → dispatch all relevant agents\n'
            "   in sequence, one per step."
        )
        assert prototype.count(rule6_block) == 2, (
            "Prototype no longer has the duplicated rule 6 — update this parity test "
            "and the bundle if the prototype is fixed upstream."
        )

        # Build expected by removing the duplicated block once.
        expected = prototype.replace(
            f"{rule6_block}\n\n{rule6_block}",
            rule6_block,
            1,
        )
        actual = PROMPT_BUNDLE["main_agent"]
        assert actual == expected, "main_agent prompt drift beyond rule-6 fix"

    def test_bundled_main_agent_has_no_duplicate_rule_6(self) -> None:
        text = PROMPT_BUNDLE["main_agent"]
        assert text.count("6. If the query is broad") == 1
