"""F11.3 — DB pool connect retries.

The pool's ``open()`` retries the initial connect
``postgres_connect_max_attempts`` times with jittered exponential
backoff. Final failure raises :class:`DatabaseUnavailable`.

We test the retry policy behaviour directly against
:func:`retry_async` since the real ``AsyncConnectionPool`` requires a
running Postgres. The integration test in ``tests/integration/`` covers
the real connect path.
"""

from __future__ import annotations

from typing import Any

import pytest

from egp_maf.errors import DatabaseUnavailable
from egp_maf.resilience.retry import RetryPolicy, retry_async

pytestmark = pytest.mark.unit


async def _sleep_noop(_d: float) -> None:
    return None


class TestDbPoolConnectRetry:
    async def test_retry_policy_matches_settings_defaults(self) -> None:
        from egp_maf.config.settings import Settings

        s = Settings()  # type: ignore[call-arg]
        assert s.postgres_connect_max_attempts >= 1
        assert s.postgres_connect_base_delay_ms >= 0
        assert s.postgres_connect_max_delay_ms >= s.postgres_connect_base_delay_ms

    async def test_open_retries_transient_connect_errors(self) -> None:
        attempts = {"n": 0}

        async def _connect() -> str:
            attempts["n"] += 1
            if attempts["n"] < 3:
                raise ConnectionError("host unreachable")
            return "pool"

        result = await retry_async(
            RetryPolicy(max_attempts=3, base_delay_ms=0, retryable=lambda _: True),
            _connect,
            sleeper=_sleep_noop,
        )
        assert result == "pool"
        assert attempts["n"] == 3

    async def test_open_gives_up_after_max_attempts(self) -> None:
        attempts = {"n": 0}

        async def _connect() -> Any:
            attempts["n"] += 1
            raise ConnectionError("still down")

        with pytest.raises(ConnectionError):
            await retry_async(
                RetryPolicy(max_attempts=3, base_delay_ms=0, retryable=lambda _: True),
                _connect,
                sleeper=_sleep_noop,
            )
        assert attempts["n"] == 3

    def test_database_unavailable_is_the_wrapper_error(self) -> None:
        """Contract: production ``open()`` wraps the final exception."""
        exc = DatabaseUnavailable("pool open failed")
        assert exc.error_code == "database_unavailable"
        assert exc.http_status == 503
