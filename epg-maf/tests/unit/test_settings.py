"""Unit tests for :mod:`egp_maf.config.settings`."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from egp_maf.config.settings import DispatchMode, PromptsSource, Settings, get_settings


class TestSettingsRequired:
    def test_missing_llm_api_key_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # Ensure neither alias is set.
        monkeypatch.delenv("LLM_API_KEY", raising=False)
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        with pytest.raises(ValidationError):
            Settings()  # type: ignore[call-arg]

    def test_openai_api_key_alias_accepted(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("LLM_API_KEY", raising=False)
        monkeypatch.setenv("OPENAI_API_KEY", "sk-alias")
        s = Settings()  # type: ignore[call-arg]
        assert s.llm_api_key.get_secret_value() == "sk-alias"

    def test_llm_api_key_preferred_over_alias(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("LLM_API_KEY", "sk-preferred")
        monkeypatch.setenv("OPENAI_API_KEY", "sk-alias")
        s = Settings()  # type: ignore[call-arg]
        assert s.llm_api_key.get_secret_value() == "sk-preferred"


class TestSettingsDefaults:
    def test_defaults(self, settings: Settings) -> None:
        assert settings.env == "dev"
        assert settings.log_level == "INFO"
        assert settings.llm_base_url == "https://api.core42.ai/v1"
        assert settings.llm_timeout_seconds == 30
        assert settings.postgres_pool_min_size == 2
        assert settings.postgres_pool_max_size == 10
        assert settings.cosmos_session_ttl_seconds == 86400
        assert settings.prompts_source == PromptsSource.BUNDLE
        assert settings.orch_dispatch_mode == DispatchMode.SEQUENTIAL
        assert settings.orch_max_fanout_width == 1
        assert settings.orch_iteration_budget == 12

    def test_env_override(self, monkeypatch: pytest.MonkeyPatch, settings: Settings) -> None:
        monkeypatch.setenv("EGP_ENV", "prod")
        s = Settings()  # type: ignore[call-arg]
        assert s.env == "prod"
        assert s.is_production() is True


class TestSettingsValidation:
    def test_pool_min_size_bounds(
        self, monkeypatch: pytest.MonkeyPatch, minimal_env: None
    ) -> None:
        monkeypatch.setenv("POSTGRES_POOL_MIN_SIZE", "-1")
        with pytest.raises(ValidationError):
            Settings()  # type: ignore[call-arg]

    def test_max_fanout_width_bounds(
        self, monkeypatch: pytest.MonkeyPatch, minimal_env: None
    ) -> None:
        monkeypatch.setenv("ORCH_MAX_FANOUT_WIDTH", "6")
        with pytest.raises(ValidationError):
            Settings()  # type: ignore[call-arg]

    def test_credentials_valid_with_password(self, settings: Settings) -> None:
        assert settings.credentials_are_valid() is True

    def test_credentials_valid_with_managed_identity(
        self, monkeypatch: pytest.MonkeyPatch, minimal_env: None
    ) -> None:
        monkeypatch.delenv("POSTGRES_PASSWORD", raising=False)
        monkeypatch.delenv("COSMOS_KEY", raising=False)
        monkeypatch.setenv("POSTGRES_USE_MANAGED_IDENTITY", "true")
        monkeypatch.setenv("COSMOS_USE_MANAGED_IDENTITY", "true")
        s = Settings()  # type: ignore[call-arg]
        assert s.credentials_are_valid() is True


class TestSettingsCache:
    def test_get_settings_caches(self, minimal_env: None) -> None:
        first = get_settings()
        second = get_settings()
        assert first is second

    def test_secretstr_not_leaked_in_repr(self, settings: Settings) -> None:
        rep = repr(settings)
        assert "sk-test-unit" not in rep
        assert "test-pw" not in rep
        assert "test-cosmos-key" not in rep
