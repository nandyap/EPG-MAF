"""Integration-test fixtures — external services required."""

from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator
from urllib.parse import quote_plus

import pytest

from egp_maf.config.settings import Settings
from egp_maf.infrastructure.cosmos_client import CosmosClientFactory
from egp_maf.infrastructure.db_pool import DbPoolFactory


def _skip_unless(env_flag: str) -> pytest.MarkDecorator:
    if os.environ.get(env_flag, "0") not in {"1", "true", "yes"}:
        return pytest.mark.skip(reason=f"{env_flag} not set — integration test skipped")
    return pytest.mark.integration


require_postgres = _skip_unless("EGP_TEST_POSTGRES")
require_cosmos = _skip_unless("EGP_TEST_COSMOS")


@pytest.fixture
async def db_pool_factory(settings: Settings) -> AsyncIterator[DbPoolFactory]:
    factory = DbPoolFactory(settings)
    await factory.open()
    try:
        yield factory
    finally:
        await factory.close()


@pytest.fixture
async def cosmos_factory(settings: Settings) -> AsyncIterator[CosmosClientFactory]:
    factory = CosmosClientFactory(settings)
    await factory.open()
    try:
        yield factory
    finally:
        await factory.close()


# ── Helpers used by W02 schema + seed integration tests ─────────────


def _build_agent_ro_conninfo() -> str:
    """Synchronous conninfo for the read-only application role.

    Used by tests/integration/test_seed_invariants.py which uses synchronous
    ``psycopg.connect`` to keep the test code simple.
    """
    host = os.environ.get("POSTGRES_HOST", "localhost")
    port = os.environ.get("POSTGRES_PORT", "5432")
    db = os.environ.get("POSTGRES_DATABASE", "egp")
    user = os.environ.get("POSTGRES_USER", "egp_agent_ro")
    password = os.environ.get("POSTGRES_PASSWORD", "")
    ssl = os.environ.get("POSTGRES_SSL_MODE", "disable")
    return (
        f"host={host} port={port} dbname={db} user={user} password={password} "
        f"sslmode={ssl} application_name=egp-maf-test"
    )


def _build_migrator_conninfo() -> str:
    """Synchronous conninfo for the migrator role.

    Used by tests/integration/test_schema.py to run information_schema
    queries after Alembic upgrade/downgrade.
    """
    host = os.environ.get("POSTGRES_HOST", "localhost")
    port = os.environ.get("POSTGRES_PORT", "5432")
    db = os.environ.get("POSTGRES_DATABASE", "egp")
    user = os.environ.get("POSTGRES_MIGRATOR_USER", "egp_migrator")
    password = os.environ.get("POSTGRES_MIGRATOR_PASSWORD", "")
    ssl = os.environ.get("POSTGRES_SSL_MODE", "disable")
    return (
        f"host={host} port={port} dbname={db} user={user} password={password} "
        f"sslmode={ssl} application_name=egp-maf-test-migrator"
    )
