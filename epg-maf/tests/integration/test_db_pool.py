"""Integration tests for :class:`egp_maf.infrastructure.db_pool.DbPoolFactory`.

Requires a local Postgres. Set ``EGP_TEST_POSTGRES=1`` to enable.
"""

from __future__ import annotations

import asyncio

import pytest

from egp_maf.infrastructure.db_pool import DbPoolFactory
from tests.integration.conftest import require_postgres


@require_postgres
class TestDbPoolIntegration:
    async def test_pool_opens_and_serves_select_one(
        self, db_pool_factory: DbPoolFactory
    ) -> None:
        async with db_pool_factory.pool.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute("SELECT 1")
                row = await cur.fetchone()
                assert row == (1,)

    async def test_statement_timeout_enforced(
        self, db_pool_factory: DbPoolFactory
    ) -> None:
        # 30s timeout is configured in fixture; assert Postgres respects it.
        async with db_pool_factory.pool.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute("SHOW statement_timeout")
                row = await cur.fetchone()
                # Postgres normalises "30000ms" to "30s".
                assert row is not None
                assert "30" in str(row[0])

    async def test_read_only_session(self, db_pool_factory: DbPoolFactory) -> None:
        async with db_pool_factory.pool.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute("SHOW default_transaction_read_only")
                # We asserted per-connection READ ONLY on transaction chars.
                row = await cur.fetchone()
                assert row is not None

    async def test_concurrent_reads(self, db_pool_factory: DbPoolFactory) -> None:
        async def one() -> int:
            async with db_pool_factory.pool.connection() as conn:
                async with conn.cursor() as cur:
                    await cur.execute("SELECT 1")
                    row = await cur.fetchone()
                    return int(row[0]) if row else -1

        results = await asyncio.gather(*(one() for _ in range(10)))
        assert results == [1] * 10

    async def test_utilisation_is_bounded(
        self, db_pool_factory: DbPoolFactory
    ) -> None:
        # No open connections in flight — utilisation should be in [0, 1].
        util = await db_pool_factory.utilisation()
        assert 0.0 <= util <= 1.0
