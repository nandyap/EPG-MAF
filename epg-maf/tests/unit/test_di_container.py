"""Unit tests for :class:`egp_maf.di.container.Container`."""

from __future__ import annotations

from typing import Any

import pytest

from egp_maf.config.settings import Settings
from egp_maf.di.container import Container, build_container
from egp_maf.infrastructure.compass_client import LlmClientFactory
from egp_maf.infrastructure.cosmos_client import CosmosClientFactory
from egp_maf.infrastructure.db_pool import DbPoolFactory
from egp_maf.services.prompt_service import PromptService
from egp_maf.services.thread_state import ThreadStateProvider


# ── Test doubles ─────────────────────────────────────────────────────


class _FakeDbPoolFactory(DbPoolFactory):
    def __init__(self) -> None:
        self.opened = False
        self.closed = False

    async def open(self) -> None:
        self.opened = True

    async def close(self) -> None:
        self.closed = True


class _FakeCosmosFactory(CosmosClientFactory):
    def __init__(self) -> None:
        self.opened = False
        self.closed = False

    async def open(self) -> None:
        self.opened = True

    async def close(self) -> None:
        self.closed = True


class _FakePromptService(PromptService):
    def __init__(self) -> None:
        self.warmed = False

    async def warm(self) -> None:
        self.warmed = True

    @property
    def fallback_count(self) -> int:
        return 0


def _build_test_container(settings: Settings) -> tuple[
    Container, _FakeDbPoolFactory, _FakeCosmosFactory, _FakePromptService
]:
    db = _FakeDbPoolFactory()
    cosmos = _FakeCosmosFactory()
    llm = LlmClientFactory(settings, client_constructor=lambda **_: object())
    prompt = _FakePromptService()
    thread_state = ThreadStateProvider(cosmos, settings)  # type: ignore[arg-type]

    container = Container(
        settings=settings,
        db_pool_factory=db,  # type: ignore[arg-type]
        cosmos_client_factory=cosmos,  # type: ignore[arg-type]
        llm_client_factory=llm,
        prompt_service=prompt,  # type: ignore[arg-type]
        thread_state_provider=thread_state,
    )
    return container, db, cosmos, prompt


# ── Tests ────────────────────────────────────────────────────────────


class TestContainerLifecycle:
    async def test_startup_opens_all(self, settings: Settings) -> None:
        container, db, cosmos, prompt = _build_test_container(settings)
        assert not container.is_started
        await container.startup()
        assert container.is_started
        assert db.opened is True
        assert cosmos.opened is True
        assert prompt.warmed is True

    async def test_startup_is_idempotent(self, settings: Settings) -> None:
        container, db, _, _ = _build_test_container(settings)
        await container.startup()
        db.opened = False  # reset
        await container.startup()
        # Second call should be a no-op.
        assert db.opened is False

    async def test_shutdown_closes_all(self, settings: Settings) -> None:
        container, db, cosmos, _ = _build_test_container(settings)
        await container.startup()
        await container.shutdown()
        assert db.closed is True
        assert cosmos.closed is True
        assert not container.is_started

    async def test_shutdown_before_startup_is_safe(self, settings: Settings) -> None:
        container, db, cosmos, _ = _build_test_container(settings)
        await container.shutdown()  # must not raise
        assert db.closed is True
        assert cosmos.closed is True

    async def test_startup_failure_triggers_shutdown(self, settings: Settings) -> None:
        container, db, cosmos, prompt = _build_test_container(settings)

        async def failing_warm() -> None:
            raise RuntimeError("simulated warm failure")

        prompt.warm = failing_warm  # type: ignore[method-assign]

        with pytest.raises(RuntimeError, match="simulated warm failure"):
            await container.startup()

        # The DB pool and Cosmos client were opened before the failing step,
        # so shutdown must close them.
        assert db.closed is True
        assert cosmos.closed is True


class TestBuildContainerWiring:
    def test_build_container_returns_container(self, settings: Settings) -> None:
        container = build_container(settings)
        assert isinstance(container, Container)
        assert container.settings is settings
        assert isinstance(container.db_pool_factory, DbPoolFactory)
        assert isinstance(container.cosmos_client_factory, CosmosClientFactory)
        assert isinstance(container.llm_client_factory, LlmClientFactory)
        assert isinstance(container.prompt_service, PromptService)
        assert isinstance(container.thread_state_provider, ThreadStateProvider)
