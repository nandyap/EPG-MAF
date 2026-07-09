"""Global test configuration.

Provides the standard fixtures used by unit and integration tests. The
integration tests have their own ``conftest.py`` with fixtures that require
external services (Postgres, Cosmos emulator).
"""

from __future__ import annotations

import os
from collections.abc import Iterator

import pytest

from egp_maf.config.settings import Settings, get_settings


@pytest.fixture(autouse=True)
def _clear_settings_cache() -> Iterator[None]:
    """Ensure each test constructs a fresh :class:`Settings` via env vars."""
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def minimal_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Minimum viable env for :class:`Settings` construction."""
    monkeypatch.setenv("LLM_API_KEY", "sk-test-unit")
    monkeypatch.setenv("POSTGRES_PASSWORD", "test-pw")
    monkeypatch.setenv("COSMOS_KEY", "test-cosmos-key")
    monkeypatch.setenv("POSTGRES_SSL_MODE", "disable")
    monkeypatch.setenv("EGP_ENV", "dev")


@pytest.fixture
def settings(minimal_env: None) -> Settings:
    """Return a :class:`Settings` instance built from the minimal env."""
    return Settings()  # type: ignore[call-arg]


@pytest.fixture(autouse=True)
def _restore_working_dir(tmp_path_factory: pytest.TempPathFactory) -> Iterator[None]:
    """Prevent tests from picking up an ambient ``.env`` file."""
    original = os.getcwd()
    tmp = tmp_path_factory.mktemp("cwd")
    os.chdir(tmp)
    yield
    os.chdir(original)
