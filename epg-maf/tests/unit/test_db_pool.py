"""Unit tests for :class:`egp_maf.infrastructure.db_pool.DbPoolFactory`.

These tests avoid opening a real Postgres — they verify the conninfo-building
logic and error paths. Real pool exercise happens in
``tests/integration/test_db_pool.py``.
"""

from __future__ import annotations

import pytest

from egp_maf.config.settings import Settings
from egp_maf.errors import ConfigurationError
from egp_maf.infrastructure.db_pool import DbPoolFactory


class TestDbPoolFactoryConnInfo:
    def test_password_conninfo(self, settings: Settings) -> None:
        f = DbPoolFactory(settings)
        info = f._build_conninfo()  # noqa: SLF001 — internal helper
        assert "host=localhost" in info
        assert "user=egp_agent_ro" in info
        assert "password=test-pw" in info
        assert "sslmode=disable" in info
        assert "statement_timeout=30000" in info
        assert "application_name=egp-maf" in info

    def test_managed_identity_omits_password_from_conninfo(
        self, monkeypatch: pytest.MonkeyPatch, minimal_env: None
    ) -> None:
        """Under managed identity the password must NOT be in the conninfo.

        It used to be: ``_build_conninfo`` called the token provider once and
        froze the result into the string. The pool then reused that string
        for every connection it opened later, so once the Entra token
        expired (~60-90 min) every new connection failed to authenticate --
        the app worked for an hour and then degraded silently.

        The token is now supplied per connection by the connection class
        returned from ``_connection_class``.
        """
        monkeypatch.delenv("POSTGRES_PASSWORD", raising=False)
        monkeypatch.setenv("POSTGRES_USE_MANAGED_IDENTITY", "true")
        s = Settings()  # type: ignore[call-arg]

        f = DbPoolFactory(s, token_provider=lambda: "aad-token-value")
        info = f._build_conninfo()  # noqa: SLF001
        assert "password=" not in info
        assert f._connection_class() is not None  # noqa: SLF001

    def test_missing_credentials_raises(
        self, monkeypatch: pytest.MonkeyPatch, minimal_env: None
    ) -> None:
        monkeypatch.delenv("POSTGRES_PASSWORD", raising=False)
        s = Settings()  # type: ignore[call-arg]
        f = DbPoolFactory(s)  # neither password nor MI
        with pytest.raises(ConfigurationError):
            f._build_conninfo()  # noqa: SLF001


class TestDbPoolFactoryAccess:
    async def test_pool_property_raises_before_open(self, settings: Settings) -> None:
        f = DbPoolFactory(settings)
        with pytest.raises(Exception):  # DatabaseUnavailable
            _ = f.pool

    async def test_utilisation_zero_before_open(self, settings: Settings) -> None:
        f = DbPoolFactory(settings)
        assert await f.utilisation() == 0.0
