"""Unit tests for :mod:`egp_maf.prompts.bundle`."""

from __future__ import annotations

import pytest

from egp_maf.errors import PromptNotFound
from egp_maf.prompts.bundle import KNOWN_PROMPTS, PROMPT_BUNDLE, load_bundle


class TestPromptBundle:
    def test_known_prompts_are_eight(self) -> None:
        # 7 agents + 1 (chat has both router and synthesis).
        assert len(KNOWN_PROMPTS) == 8

    def test_known_prompts_names(self) -> None:
        assert KNOWN_PROMPTS == frozenset(
            {
                "chat_router",
                "chat_synthesis",
                "main_agent",
                "prs_agent",
                "genomic_variants_agent",
                "family_history_agent",
                "pgx_agent",
                "phenotype_agent",
            }
        )

    def test_every_prompt_loaded(self) -> None:
        assert set(PROMPT_BUNDLE.keys()) == KNOWN_PROMPTS

    def test_no_prompt_is_empty(self) -> None:
        for name, text in PROMPT_BUNDLE.items():
            assert text.strip(), f"prompt {name} is empty"

    def test_prompts_are_strings(self) -> None:
        for text in PROMPT_BUNDLE.values():
            assert isinstance(text, str)

    def test_load_bundle_returns_fresh_dict(self) -> None:
        a = load_bundle()
        b = load_bundle()
        assert a == b
        assert a is not b

    def test_main_agent_rule_6_deduplicated(self) -> None:
        """The bundled prompt fixes the duplicate rule 6 (Design §15.5)."""
        text = PROMPT_BUNDLE["main_agent"]
        # Exactly one occurrence of the rule-6 opening string.
        marker = "6. If the query is broad"
        assert text.count(marker) == 1, "duplicated rule 6 should be removed"

    def test_prompts_have_no_trailing_python_syntax(self) -> None:
        """Prompt files must be pure text — no leftover Python constant
        assignment (e.g. ``PROMPT = \"\"\"``)."""
        for name, text in PROMPT_BUNDLE.items():
            first_line = text.splitlines()[0] if text.splitlines() else ""
            assert not first_line.endswith('= """'), f"leftover Python in {name}"
            assert not first_line.endswith('= "'), f"leftover Python in {name}"

    def test_chat_router_contains_reset_agents_section(self) -> None:
        assert "reset_agents" in PROMPT_BUNDLE["chat_router"]

    def test_family_history_privacy_note_preserved(self) -> None:
        text = PROMPT_BUNDLE["family_history_agent"]
        assert "Do NOT reproduce relative details" in text

    def test_phenotype_stay_in_lane_guardrail_preserved(self) -> None:
        text = PROMPT_BUNDLE["phenotype_agent"]
        assert "Do not suggest further genetic testing" in text
