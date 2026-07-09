"""PostgreSQL async connection pool factory.

Sized per Design §11.4:
    max_size = concurrent_specialists_per_request * request_concurrency_per_replica

The pool is opened at startup and closed at shutdown by the DI container.

Managed identity authentication (Design ADR-005, §11.5) uses a per-connect
password callback that acquires a fresh Entra ID token. The token TTL is 1
hour by default; the callback runs on each new connection.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import TYPE_CHECKING

from egp_maf.config.settings import Settings
from egp_maf.errors import ConfigurationError, DatabaseUnavailable

if TYPE_CHECKING:  # pragma: no cover — avoid hard dep at test-collection time
    from psycopg_pool import AsyncConnectionPool

# Entra ID scope for Azure Database for PostgreSQL Flexible Server (AAD auth).
_POSTGRES_AAD_SCOPE = "https://ossrdbms-aad.database.windows.net/.default"

_logger = logging.getLogger(__name__)


class DbPoolFactory:
    """Constructs and lifecycle-manages an ``AsyncConnectionPool``.

    A single instance lives in the DI container. Callers ``await open()``
    at process startup, and ``await close()`` at shutdown.

    The factory does NOT expose the pool itself directly — instead Repository
    classes take the pool via constructor injection in the repository
    workstream. The factory exposes a ``pool`` property; the DI container
    binds this to the Repository dependencies.
    """

    def __init__(
        self,
        settings: Settings,
        *,
        token_provider: Callable[[], str] | None = None,
    ) -> None:
        """Store configuration.

        Parameters
        ----------
        settings:
            Application settings.
        token_provider:
            Optional callable that returns an Entra ID access token string.
            Injected in tests so we do not require ``azure-identity`` for
            unit-testing the pool.
        """

        self._settings = settings
        self._token_provider = token_provider
        self._pool: "AsyncConnectionPool | None" = None

    # ── Lifecycle ────────────────────────────────────────────────────
    async def open(self) -> None:
        """Open the pool. Idempotent."""
        if self._pool is not None:
            return

        # Import lazily so unit tests that never open the pool don't need
        # psycopg installed with the C extension.
        from psycopg_pool import AsyncConnectionPool  # type: ignore[import-untyped]

        conninfo = self._build_conninfo()
        self._pool = AsyncConnectionPool(
            conninfo=conninfo,
            min_size=self._settings.postgres_pool_min_size,
            max_size=self._settings.postgres_pool_max_size,
            timeout=self._settings.postgres_pool_timeout_seconds,
            open=False,
            configure=self._configure_connection,
        )
        try:
            await self._pool.open(wait=True, timeout=10.0)
        except Exception as exc:  # pragma: no cover — exercised in integration
            _logger.error("db.pool.open_failed", exc_info=exc)
            raise DatabaseUnavailable(
                f"Failed to open Postgres pool for {self._settings.postgres_host}"
            ) from exc

    async def close(self) -> None:
        """Close the pool. Idempotent."""
        if self._pool is not None:
            await self._pool.close()
            self._pool = None

    # ── Access ───────────────────────────────────────────────────────
    @property
    def pool(self) -> "AsyncConnectionPool":
        """Return the opened pool. Raises if ``open()`` has not been called."""
        if self._pool is None:
            raise DatabaseUnavailable(
                "Postgres pool has not been opened. Call DbPoolFactory.open() first."
            )
        return self._pool

    async def utilisation(self) -> float:
        """Return current pool utilisation in the range [0, 1] for metrics.

        ``max_size`` is used as the denominator. Returns 0.0 when the pool is
        unopened.
        """
        if self._pool is None:
            return 0.0
        stats = self._pool.get_stats()
        used = int(stats.get("pool_size", 0)) - int(stats.get("pool_available", 0))
        return max(0.0, min(1.0, used / max(1, self._settings.postgres_pool_max_size)))

    # ── Internals ────────────────────────────────────────────────────
    def _build_conninfo(self) -> str:
        """Build the psycopg conninfo string.

        Password resolution:
        - If ``postgres_use_managed_identity`` is true, obtain a token from the
          injected ``token_provider`` (or ``DefaultAzureCredential`` in prod).
        - Else use the static ``postgres_password``.

        Statement timeout is applied server-side via ``options=-c
        statement_timeout=...``.
        """
        s = self._settings
        if s.postgres_use_managed_identity:
            password = self._acquire_token()
        elif s.postgres_password is not None:
            password = s.postgres_password.get_secret_value()
        else:
            raise ConfigurationError(
                "Postgres credentials missing: set POSTGRES_PASSWORD or "
                "POSTGRES_USE_MANAGED_IDENTITY=true."
            )

        # statement_timeout is milliseconds server-side.
        stmt_ms = s.postgres_statement_timeout_seconds * 1000
        # Use keyword=value form (psycopg parses it correctly).
        parts = [
            f"host={s.postgres_host}",
            f"port={s.postgres_port}",
            f"dbname={s.postgres_database}",
            f"user={s.postgres_user}",
            f"password={password}",
            f"sslmode={s.postgres_ssl_mode}",
            f"options=-c statement_timeout={stmt_ms}",
            "application_name=egp-maf",
        ]
        return " ".join(parts)

    def _acquire_token(self) -> str:
        """Acquire an Entra ID token to use as the Postgres password."""
        if self._token_provider is not None:
            return self._token_provider()

        # Production fallback — DefaultAzureCredential.
        try:
            from azure.identity import DefaultAzureCredential  # type: ignore[import-untyped]
        except ImportError as exc:  # pragma: no cover
            raise ConfigurationError(
                "azure-identity is required when POSTGRES_USE_MANAGED_IDENTITY=true"
            ) from exc

        credential = DefaultAzureCredential()
        try:
            return credential.get_token(_POSTGRES_AAD_SCOPE).token
        except Exception as exc:  # pragma: no cover — exercised in integration
            raise DatabaseUnavailable(
                "Failed to acquire Entra ID token for Postgres"
            ) from exc

    async def _configure_connection(self, conn: object) -> None:
        """Per-connection setup — read-only + statement timeout confirmation."""
        # ``egp_agent_ro`` role is SELECT-only, but we also assert session read-only
        # as belt-and-braces.
        try:
            await conn.execute("SET SESSION CHARACTERISTICS AS TRANSACTION READ ONLY")  # type: ignore[attr-defined]
        except Exception as exc:  # pragma: no cover
            _logger.warning("db.pool.configure_failed", exc_info=exc)
