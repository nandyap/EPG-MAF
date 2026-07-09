"""Integration-test fixtures — external services required."""

from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator

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
