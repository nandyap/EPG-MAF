"""Integration tests for :class:`egp_maf.services.thread_state.ThreadStateProvider`.

Requires a Cosmos emulator. Set ``EGP_TEST_COSMOS=1`` to enable.

The tests create and drop a temporary container so they can be re-run.
"""

from __future__ import annotations

import pytest

from egp_maf.config.settings import Settings
from egp_maf.errors import ConcurrencyConflict
from egp_maf.infrastructure.cosmos_client import CosmosClientFactory
from egp_maf.services.thread_state import ThreadStateProvider
from egp_maf.state.session_document import SessionDocument, SessionMessage
from tests.integration.conftest import require_cosmos


async def _ensure_container(factory: CosmosClientFactory, settings: Settings) -> None:
    db = factory.client.get_database_client(settings.cosmos_database)
    try:
        await db.create_database(id=settings.cosmos_database)
    except Exception:  # noqa: BLE001 — already exists
        pass
    try:
        await db.create_container(
            id=settings.cosmos_container,
            partition_key={"paths": ["/clinician_id"], "kind": "Hash"},
            default_ttl=settings.cosmos_session_ttl_seconds,
        )
    except Exception:  # noqa: BLE001 — already exists
        pass


@require_cosmos
class TestThreadStateProviderIntegration:
    async def test_load_returns_none_for_missing(
        self, cosmos_factory: CosmosClientFactory, settings: Settings
    ) -> None:
        await _ensure_container(cosmos_factory, settings)
        provider = ThreadStateProvider(cosmos_factory, settings)
        result = await provider.load("th-nonexistent", "c-nonexistent")
        assert result is None

    async def test_save_and_load_round_trip(
        self, cosmos_factory: CosmosClientFactory, settings: Settings
    ) -> None:
        await _ensure_container(cosmos_factory, settings)
        provider = ThreadStateProvider(cosmos_factory, settings)

        doc = SessionDocument(
            thread_id="th-rt-1",
            clinician_id="c-rt-1",
            tenant_id="t1",
            patient_id="P001",
        ).with_message(SessionMessage(role="user", content="hi"))

        saved = await provider.save(doc)
        assert saved.etag is not None

        reloaded = await provider.load("th-rt-1", "c-rt-1")
        assert reloaded is not None
        assert reloaded.patient_id == "P001"
        assert len(reloaded.messages) == 1
        assert reloaded.messages[0].content == "hi"
        assert reloaded.etag == saved.etag

    async def test_etag_conflict_raises(
        self, cosmos_factory: CosmosClientFactory, settings: Settings
    ) -> None:
        await _ensure_container(cosmos_factory, settings)
        provider = ThreadStateProvider(cosmos_factory, settings)

        base = SessionDocument(
            thread_id="th-conflict",
            clinician_id="c-conflict",
            tenant_id="t1",
            patient_id="P001",
        )
        saved = await provider.save(base)

        # Simulate concurrent writers with the same stale etag.
        stale = saved.model_copy(update={"messages": [SessionMessage(role="user", content="A")]})
        _ = await provider.save(stale)  # first update — succeeds

        # Second attempt with the original etag should conflict.
        with pytest.raises(ConcurrencyConflict):
            await provider.save(stale)

    async def test_delete(
        self, cosmos_factory: CosmosClientFactory, settings: Settings
    ) -> None:
        await _ensure_container(cosmos_factory, settings)
        provider = ThreadStateProvider(cosmos_factory, settings)

        doc = SessionDocument(
            thread_id="th-del",
            clinician_id="c-del",
            tenant_id="t1",
            patient_id="P001",
        )
        await provider.save(doc)
        await provider.delete("th-del", "c-del")
        result = await provider.load("th-del", "c-del")
        assert result is None
