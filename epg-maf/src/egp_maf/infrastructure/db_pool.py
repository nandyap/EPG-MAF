"""PostgreSQL async connection pool factory.

Sized per Design §11.4:
    max_size = concurrent_specialists_per_request * request_concurrency_per_replica

The pool is opened at startup and closed at shutdown by the DI container.

Managed identity authentication (Design ADR-005, §11.5) uses a per-connect
password callback that acquires a fresh Entra ID token. The token TTL is 1
hour by default; the callback runs on each new connection.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from egp_maf.config.settings import Settings
from egp_maf.errors import ConfigurationError, DatabaseUnavailable

if TYPE_CHECKING:  # pragma: no cover — avoid hard dep at test-collection time
    from psycopg_pool import AsyncConnectionPool

# Entra ID scope for Azure Database for PostgreSQL Flexible Server (AAD auth).
_POSTGRES_AAD_SCOPE = "https://ossrdbms-aad.database.windows.net/.default"

# Minimum gap between lazy re-open attempts. Without it, every request on a
# dead database would trigger a fresh connect storm.
_REOPEN_COOLDOWN_SECONDS = 10.0

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
        self._last_open_attempt: float = 0.0
        self._last_open_error: str | None = None
        self._open_lock: asyncio.Lock | None = None

    # ── Lifecycle ────────────────────────────────────────────────────
    async def open(self) -> None:
        """Open the pool. Idempotent.

        Retries the initial connect ``postgres_connect_max_attempts``
        times with jittered exponential backoff (F11.3 — Design §26).
        Final failure surfaces as :class:`DatabaseUnavailable`.
        """
        if self._pool is not None:
            return

        # Import lazily so unit tests that never open the pool don't need
        # psycopg installed with the C extension.
        from psycopg_pool import AsyncConnectionPool  # type: ignore[import-untyped]

        # Local import — resilience module is optional at collection
        # time and avoids a top-of-module cycle with settings.
        from egp_maf.resilience.retry import RetryPolicy, retry_async

        conninfo = self._build_conninfo()
        connection_class = self._connection_class()

        async def _open_once() -> "AsyncConnectionPool":
            kwargs: dict[str, Any] = {
                "conninfo": conninfo,
                "min_size": self._settings.postgres_pool_min_size,
                "max_size": self._settings.postgres_pool_max_size,
                "timeout": self._settings.postgres_pool_timeout_seconds,
                "open": False,
                "configure": self._configure_connection,
            }
            if connection_class is not None:
                kwargs["connection_class"] = connection_class
            pool = AsyncConnectionPool(**kwargs)
            await pool.open(wait=True, timeout=10.0)
            return pool

        policy = RetryPolicy(
            max_attempts=self._settings.postgres_connect_max_attempts,
            base_delay_ms=self._settings.postgres_connect_base_delay_ms,
            max_delay_ms=self._settings.postgres_connect_max_delay_ms,
            retryable=lambda _exc: True,  # any connect error is retryable
        )
        self._last_open_attempt = time.monotonic()
        try:
            self._pool = await retry_async(policy, _open_once)
            self._last_open_error = None
        except Exception as exc:  # pragma: no cover — exercised in integration
            _logger.error("db.pool.open_failed", exc_info=exc)
            # Surface the underlying driver error in the message itself.
            # The chained ``__cause__`` is only visible if the full
            # traceback survives, and in Container Apps the log stream is
            # frequently truncated — leaving operators with a wrapper that
            # says "failed" but not *why*. psycopg's message distinguishes
            # DNS / timeout / auth / missing-database, which are four very
            # different fixes. It does not echo the connection password.
            detail = (
                f"Failed to open Postgres pool for {self._settings.postgres_host} "
                f"(db={self._settings.postgres_database}, "
                f"user={self._settings.postgres_user}, "
                f"managed_identity={self._settings.postgres_use_managed_identity}) "
                f"after {self._settings.postgres_connect_max_attempts} attempts: "
                f"{type(exc).__name__}: {exc}"
            )
            self._last_open_error = detail
            raise DatabaseUnavailable(detail) from exc

    async def close(self) -> None:
        """Close the pool. Idempotent."""
        if self._pool is not None:
            await self._pool.close()
            self._pool = None

    # ── Access ───────────────────────────────────────────────────────
    async def get_pool(self) -> "AsyncConnectionPool":
        """Return the pool, opening it on demand.

        Startup opens the pool eagerly, but when ``POSTGRES_STARTUP_REQUIRED``
        is false a failure there is only logged — the process keeps running
        with ``_pool is None``. Without a lazy retry every later request
        died on "pool has not been opened", which is a symptom of the
        earlier failure rather than a cause, and the app could never
        recover from a transient outage without a redeploy.

        Re-open attempts are spaced by ``_REOPEN_COOLDOWN_SECONDS`` so a
        genuinely unreachable database does not trigger a connect storm;
        in the cooldown window the last real error is replayed.
        """
        if self._pool is not None:
            return self._pool

        # Created lazily: the factory is constructed at import time, before
        # an event loop exists.
        if self._open_lock is None:
            self._open_lock = asyncio.Lock()

        async with self._open_lock:
            # Another coroutine may have opened it while we waited.
            if self._pool is not None:
                return self._pool

            elapsed = time.monotonic() - self._last_open_attempt
            if self._last_open_error is not None and elapsed < _REOPEN_COOLDOWN_SECONDS:
                raise DatabaseUnavailable(self._last_open_error)

            _logger.info("db.pool.lazy_open_attempt")
            self._last_open_attempt = time.monotonic()
            await self.open()
            assert self._pool is not None  # open() raises on failure
            _logger.info("db.pool.lazy_open_succeeded")
            return self._pool

    @property
    def pool(self) -> "AsyncConnectionPool":
        """Return the opened pool. Raises if it is not open.

        Prefer :meth:`get_pool`, which opens on demand. This property
        remains for callers that already hold an open pool (metrics,
        tests).
        """
        if self._pool is None:
            raise DatabaseUnavailable(
                self._last_open_error
                or "Postgres pool has not been opened. Call DbPoolFactory.open() first."
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
    def _connection_class(self) -> Any | None:
        """Return a connection class that refreshes the AAD token per connect.

        Only used when ``postgres_use_managed_identity`` is set. Entra
        tokens live ~60–90 minutes, but a pool outlives that: it opens new
        connections whenever one is recycled or the pool grows. Baking the
        startup token into the conninfo string means every connection
        created after expiry fails to authenticate, so the app works for
        an hour and then degrades for no visible reason.

        Fetching per connect keeps every connection current. The credential
        caches internally, so this is normally a cheap in-memory read; it
        runs in a worker thread because the SDK call is synchronous and
        must not block the event loop.
        """
        if not self._settings.postgres_use_managed_identity:
            return None

        from psycopg import AsyncConnection  # type: ignore[import-untyped]

        acquire = self._acquire_token

        class _AadTokenConnection(AsyncConnection):  # type: ignore[misc]
            @classmethod
            async def connect(  # type: ignore[override]
                cls, conninfo: str = "", **kwargs: Any
            ) -> Any:
                kwargs["password"] = await asyncio.to_thread(acquire)
                return await super().connect(conninfo, **kwargs)

        return _AadTokenConnection

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
        # Under managed identity the password is an Entra token supplied
        # per connection by ``_connection_class`` — see the note there on
        # why it must not be frozen into this string.
        password: str | None
        if s.postgres_use_managed_identity:
            password = None
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
            f"sslmode={s.postgres_ssl_mode}",
            f"options=-c statement_timeout={stmt_ms}",
            "application_name=egp-maf",
        ]
        if password is not None:
            parts.insert(4, f"password={password}")
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
