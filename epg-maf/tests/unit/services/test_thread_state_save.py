"""``ThreadStateProvider.save`` write-path tests against a fake container.

Regression guard: ``save`` passed ``match_condition="IfMatch"`` (a plain
string) to ``ContainerProxy.replace_item``. The Cosmos SDK requires the
``azure.core.MatchConditions`` enum and raises

    TypeError: Invalid match condition: IfMatch

client-side, *before* issuing any request (see ``azure/cosmos/_base.py``).

Consequences in production:

- Thread creation worked, because a brand-new ``SessionDocument`` has
  ``etag is None`` and takes the ``upsert_item`` branch.
- Every *subsequent* write failed, because a document loaded from Cosmos
  carries an ETag and takes the ``replace_item`` branch. Chat transcripts
  were therefore never persisted (B-009), and the caller only saw a
  ``chat.persist_messages_failed`` warning with no cause attached.

These tests drive the real ``save`` method with a fake container proxy,
so the write path is covered without an emulator. The pre-existing
``tests/integration/test_cosmos.py`` covers this too, but is gated behind
``EGP_TEST_COSMOS=1``.
"""

from __future__ import annotations

from typing import Any

import pytest
from azure.core import MatchConditions

from egp_maf.config.settings import Settings
from egp_maf.services.thread_state import ThreadStateProvider
from egp_maf.state.session_document import SessionDocument, SessionMessage

pytestmark = pytest.mark.unit


class _FakeContainer:
    """Minimal ``ContainerProxy`` double recording the calls it receives."""

    def __init__(self) -> None:
        self.upserts: list[dict[str, Any]] = []
        self.replaces: list[dict[str, Any]] = []

    async def upsert_item(self, body: dict[str, Any]) -> dict[str, Any]:
        self.upserts.append(body)
        return {**body, "_etag": '"etag-after-upsert"'}

    async def replace_item(
        self,
        item: str,
        body: dict[str, Any],
        **kwargs: Any,
    ) -> dict[str, Any]:
        # Mirror the SDK's own validation so a wrong type fails here too.
        match_condition = kwargs.get("match_condition")
        if match_condition is not None and not isinstance(
            match_condition, MatchConditions
        ):
            raise TypeError(f"Invalid match condition: {match_condition}")
        self.replaces.append({"item": item, "body": body, **kwargs})
        return {**body, "_etag": '"etag-after-replace"'}


def _provider(container: _FakeContainer) -> ThreadStateProvider:
    provider = ThreadStateProvider.__new__(ThreadStateProvider)
    provider._settings = Settings(  # type: ignore[attr-defined]
        LLM_API_KEY="test-key",
    )
    provider._container = container  # type: ignore[attr-defined]
    provider._cosmos = None  # type: ignore[attr-defined]
    return provider


def _doc(**overrides: Any) -> SessionDocument:
    base: dict[str, Any] = {
        "thread_id": "T-abc",
        "clinician_id": "demo",
        "tenant_id": "t1",
        "patient_id": "PGP001",
    }
    base.update(overrides)
    return SessionDocument(**base)


class TestSaveNewDocument:
    @pytest.mark.asyncio
    async def test_uses_upsert_when_no_etag(self) -> None:
        container = _FakeContainer()
        provider = _provider(container)

        saved = await provider.save(_doc())

        assert len(container.upserts) == 1
        assert not container.replaces
        assert container.upserts[0]["id"] == "T-abc"
        assert saved.etag == '"etag-after-upsert"'


class TestSaveExistingDocument:
    @pytest.mark.asyncio
    async def test_replace_uses_match_conditions_enum(self) -> None:
        """The core regression — a string here raises TypeError."""
        container = _FakeContainer()
        provider = _provider(container)

        await provider.save(_doc(etag='"existing-etag"'))

        assert len(container.replaces) == 1
        call = container.replaces[0]
        assert call["match_condition"] is MatchConditions.IfNotModified
        assert call["etag"] == '"existing-etag"'

    @pytest.mark.asyncio
    async def test_persists_appended_messages(self) -> None:
        """The end-to-end symptom: transcripts must survive a save."""
        container = _FakeContainer()
        provider = _provider(container)
        doc = _doc(etag='"existing-etag"').with_message(
            SessionMessage(role="user", content="does this patient have X?")
        )

        saved = await provider.save(doc)

        body = container.replaces[0]["body"]
        assert [m["role"] for m in body["messages"]] == ["user"]
        assert body["messages"][0]["content"] == "does this patient have X?"
        assert saved.etag == '"etag-after-replace"'

    @pytest.mark.asyncio
    async def test_refreshes_ttl_and_last_activity(self) -> None:
        container = _FakeContainer()
        provider = _provider(container)
        original = _doc(etag='"existing-etag"')

        saved = await provider.save(original)

        body = container.replaces[0]["body"]
        assert body["ttl"] == provider._settings.cosmos_session_ttl_seconds  # type: ignore[attr-defined]
        assert saved.last_activity >= original.last_activity
