"""Lazy re-open behaviour for :class:`DbPoolFactory`.

Regression: when the startup connect failed and
``POSTGRES_STARTUP_REQUIRED`` was false, ``Container.startup`` logged a
warning and carried on with ``_pool is None``. Nothing ever retried, so:

- every later request died on "Postgres pool has not been opened", which
  is a symptom of the earlier failure and hides the real cause (the
  psycopg error from startup);
- the process could never recover from a transient database outage
  without a redeploy.

Observed in production as::

    Function failed. Error: Postgres pool has not been opened.
        Call DbPoolFactory.open() first.

while the actual fault, minutes earlier at startup, was
``PoolTimeout: pool initialization incomplete after 10.0 sec``.
"""

from __future__ import annotations

from typing import Any

import pytest

from egp_maf.config.settings import Settings
from egp_maf.errors import DatabaseUnavailable
from egp_maf.infrastructure import db_pool as db_pool_module
from egp_maf.infrastructure.db_pool import DbPoolFactory

pytestmark = pytest.mark.unit


def _settings() -> Settings:
    return Settings(
        LLM_API_KEY="test-key",
        POSTGRES_HOST="db.example.invalid",
        POSTGRES_PASSWORD="pw",
        POSTGRES_CONNECT_MAX_ATTEMPTS=1,
        POSTGRES_CONNECT_BASE_DELAY_MS=1,
    )


class _Sentinel:
    """Stands in for an ``AsyncConnectionPool``."""


class TestLazyOpen:
    @pytest.mark.asyncio
    async def test_opens_on_first_use(self) -> None:
        factory = DbPoolFactory(_settings())
        calls: list[int] = []

        async def _fake_open() -> None:
            calls.append(1)
            factory._pool = _Sentinel()  # type: ignore[assignment]

        factory.open = _fake_open  # type: ignore[method-assign]

        pool = await factory.get_pool()

        assert isinstance(pool, _Sentinel)
        assert calls == [1]

    @pytest.mark.asyncio
    async def test_reuses_an_open_pool(self) -> None:
        factory = DbPoolFactory(_settings())
        sentinel = _Sentinel()
        factory._pool = sentinel  # type: ignore[assignment]

        async def _fail() -> None:
            raise AssertionError("open() must not be called when already open")

        factory.open = _fail  # type: ignore[method-assign]

        assert await factory.get_pool() is sentinel

    @pytest.mark.asyncio
    async def test_recovers_after_a_failed_startup(self) -> None:
        """The core regression — a failed startup must not be terminal."""
        factory = DbPoolFactory(_settings())
        attempts: list[int] = []

        async def _flaky_open() -> None:
            attempts.append(1)
            if len(attempts) == 1:
                raise DatabaseUnavailable("connect timed out")
            factory._pool = _Sentinel()  # type: ignore[assignment]

        factory.open = _flaky_open  # type: ignore[method-assign]

        with pytest.raises(DatabaseUnavailable):
            await factory.get_pool()

        # Cooldown would otherwise replay the cached error.
        factory._last_open_attempt = 0.0

        pool = await factory.get_pool()
        assert isinstance(pool, _Sentinel)
        assert len(attempts) == 2

    @pytest.mark.asyncio
    async def test_cooldown_prevents_a_connect_storm(self) -> None:
        """A genuinely dead database must not be hammered per request."""
        factory = DbPoolFactory(_settings())
        attempts: list[int] = []

        async def _always_fails() -> None:
            attempts.append(1)
            factory._last_open_error = "connect timed out"
            raise DatabaseUnavailable("connect timed out")

        factory.open = _always_fails  # type: ignore[method-assign]

        for _ in range(5):
            with pytest.raises(DatabaseUnavailable):
                await factory.get_pool()

        assert len(attempts) == 1

    @pytest.mark.asyncio
    async def test_replayed_error_keeps_the_real_cause(self) -> None:
        """Callers in the cooldown window still see the underlying fault,
        not the misleading 'pool has not been opened'."""
        factory = DbPoolFactory(_settings())

        async def _fails() -> None:
            factory._last_open_error = "PoolTimeout: pool initialization incomplete"
            raise DatabaseUnavailable("PoolTimeout: pool initialization incomplete")

        factory.open = _fails  # type: ignore[method-assign]

        with pytest.raises(DatabaseUnavailable):
            await factory.get_pool()
        with pytest.raises(DatabaseUnavailable, match="PoolTimeout"):
            await factory.get_pool()


class TestManagedIdentityConnectionClass:
    def test_no_custom_class_without_managed_identity(self) -> None:
        factory = DbPoolFactory(_settings())

        assert factory._connection_class() is None

    def test_conninfo_omits_password_under_managed_identity(self) -> None:
        """The token is supplied per connection, so it must not be frozen
        into the conninfo string at startup."""
        settings = Settings(
            LLM_API_KEY="test-key",
            POSTGRES_HOST="db.example.invalid",
            POSTGRES_USE_MANAGED_IDENTITY=True,
        )
        factory = DbPoolFactory(settings, token_provider=lambda: "tok")

        conninfo = factory._build_conninfo()

        assert "password=" not in conninfo
        assert "host=db.example.invalid" in conninfo


class TestCredentialReuse:
    def test_credential_is_constructed_once(self) -> None:
        """A fresh ``DefaultAzureCredential`` per call defeats the SDK's
        token cache — the deployed logs showed an IMDS round-trip for
        every connection attempt."""
        settings = Settings(
            LLM_API_KEY="test-key",
            POSTGRES_HOST="db.example.invalid",
            POSTGRES_USE_MANAGED_IDENTITY=True,
        )
        factory = DbPoolFactory(settings)
        constructed: list[int] = []

        class _FakeToken:
            token = "tok"

        class _FakeCredential:
            def __init__(self) -> None:
                constructed.append(1)

            def get_token(self, _scope: str) -> object:
                return _FakeToken()

        factory._credential = _FakeCredential()
        constructed.clear()

        assert factory._acquire_token() == "tok"
        assert factory._acquire_token() == "tok"
        assert constructed == []  # reused, never rebuilt


class TestConfigureCallback:
    @pytest.mark.asyncio
    async def test_configure_leaves_connection_untouched(self) -> None:
        """Anything executed here leaves the connection INTRANS and the
        pool discards it. The hook must stay inert."""
        factory = DbPoolFactory(_settings())

        class _Conn:
            def __init__(self) -> None:
                self.executed: list[str] = []

            async def execute(self, sql: str) -> None:
                self.executed.append(sql)

        conn = _Conn()
        await factory._configure_connection(conn)

        assert conn.executed == []
