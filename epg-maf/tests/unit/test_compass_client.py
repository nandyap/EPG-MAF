"""Unit tests for :class:`egp_maf.infrastructure.compass_client.LlmClientFactory`."""

from __future__ import annotations

from typing import Any

import pytest

from egp_maf.config.llm_config import AGENT_LLM_CONFIGS, AgentLlmConfig
from egp_maf.config.settings import Settings
from egp_maf.errors import ConfigurationError
from egp_maf.infrastructure.compass_client import LlmClientFactory


class _StubClient:
    """Fake ``OpenAIChatClient`` used to unit-test the factory without MAF."""

    def __init__(self, *, api_key: str, base_url: str, model_id: str) -> None:
        self.api_key = api_key
        self.base_url = base_url
        self.model_id = model_id


def _stub_constructor(**kwargs: Any) -> _StubClient:
    return _StubClient(**kwargs)


class TestLlmClientFactoryValidation:
    def test_unknown_agent_raises(self, settings: Settings) -> None:
        factory = LlmClientFactory(settings, client_constructor=_stub_constructor)
        with pytest.raises(ConfigurationError):
            factory.get("nonexistent_agent")

    def test_config_for_unknown_raises(self, settings: Settings) -> None:
        factory = LlmClientFactory(settings, client_constructor=_stub_constructor)
        with pytest.raises(ConfigurationError):
            factory.config_for("nonexistent_agent")


class TestLlmClientFactoryConstruction:
    def test_get_returns_client_configured_for_agent(self, settings: Settings) -> None:
        factory = LlmClientFactory(settings, client_constructor=_stub_constructor)

        prs_client = factory.get("prs")
        assert isinstance(prs_client, _StubClient)
        assert prs_client.model_id == AGENT_LLM_CONFIGS["prs"].model
        assert prs_client.base_url == settings.llm_base_url
        assert prs_client.api_key == settings.llm_api_key.get_secret_value()

    def test_chat_uses_stronger_model(self, settings: Settings) -> None:
        factory = LlmClientFactory(settings, client_constructor=_stub_constructor)
        chat_client = factory.get("chat")
        prs_client = factory.get("prs")
        assert chat_client.model_id == "gpt-5.1"
        assert prs_client.model_id == "gpt-4.1"

    def test_config_for_returns_dataclass(self, settings: Settings) -> None:
        factory = LlmClientFactory(settings, client_constructor=_stub_constructor)
        cfg = factory.config_for("family_history")
        assert isinstance(cfg, AgentLlmConfig)
        assert cfg.temperature == 0.0

    def test_all_known_agents_resolvable(self, settings: Settings) -> None:
        factory = LlmClientFactory(settings, client_constructor=_stub_constructor)
        for agent_name in AGENT_LLM_CONFIGS:
            client = factory.get(agent_name)
            assert client.model_id == AGENT_LLM_CONFIGS[agent_name].model


class TestLlmClientFactoryCaching:
    def test_same_agent_returns_same_instance(self, settings: Settings) -> None:
        factory = LlmClientFactory(settings, client_constructor=_stub_constructor)
        a = factory.get("prs")
        b = factory.get("prs")
        assert a is b

    def test_different_agents_different_instances(self, settings: Settings) -> None:
        factory = LlmClientFactory(settings, client_constructor=_stub_constructor)
        assert factory.get("prs") is not factory.get("main")

    def test_clear_resets_cache(self, settings: Settings) -> None:
        factory = LlmClientFactory(settings, client_constructor=_stub_constructor)
        a = factory.get("prs")
        factory.clear()
        b = factory.get("prs")
        assert a is not b
