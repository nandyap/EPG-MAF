"""Unit tests for :mod:`egp_maf.config.llm_config`."""

from __future__ import annotations

from egp_maf.config.llm_config import (
    AGENT_LLM_CONFIGS,
    AgentLlmConfig,
    KNOWN_AGENT_NAMES,
)


class TestAgentLlmConfigs:
    def test_all_seven_agents_present(self) -> None:
        expected = {
            "prs",
            "pgx",
            "genomic_variants",
            "family_history",
            "phenotype",
            "main",
            "chat",
        }
        assert set(AGENT_LLM_CONFIGS.keys()) == expected
        assert KNOWN_AGENT_NAMES == frozenset(expected)

    def test_chat_uses_gpt_5_1(self) -> None:
        assert AGENT_LLM_CONFIGS["chat"].model == "gpt-5.1"

    def test_all_other_agents_use_gpt_4_1(self) -> None:
        for name, cfg in AGENT_LLM_CONFIGS.items():
            if name == "chat":
                continue
            assert cfg.model == "gpt-4.1", f"agent {name} uses {cfg.model}"

    def test_all_agents_use_zero_temperature(self) -> None:
        for name, cfg in AGENT_LLM_CONFIGS.items():
            assert cfg.temperature == 0.0, f"agent {name} temperature={cfg.temperature}"

    def test_configs_are_frozen(self) -> None:
        # frozen dataclass — attempts to mutate must raise.
        cfg = AGENT_LLM_CONFIGS["prs"]
        try:
            cfg.temperature = 0.5  # type: ignore[misc]
        except Exception as exc:  # noqa: BLE001
            assert exc.__class__.__name__ in {"FrozenInstanceError", "AttributeError"}
        else:
            raise AssertionError("Expected AgentLlmConfig to be frozen")

    def test_notes_populated(self) -> None:
        for name, cfg in AGENT_LLM_CONFIGS.items():
            assert cfg.note.strip(), f"agent {name} has empty note"


class TestAgentLlmConfigModel:
    def test_construction(self) -> None:
        cfg = AgentLlmConfig(model="gpt-4.1", temperature=0.0)
        assert cfg.model == "gpt-4.1"
        assert cfg.temperature == 0.0
        assert cfg.reasoning is False
        assert cfg.note == ""

    def test_full_construction(self) -> None:
        cfg = AgentLlmConfig(
            model="o1", temperature=0.0, reasoning=True, note="reasoning"
        )
        assert cfg.reasoning is True
        assert cfg.note == "reasoning"
