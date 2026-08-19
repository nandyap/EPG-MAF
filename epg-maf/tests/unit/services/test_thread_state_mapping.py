"""Cosmos <-> :class:`SessionDocument` round-trip mapping tests.

These exercise :meth:`ThreadStateProvider._document_from_item` and
:meth:`_item_from_document` directly, with **realistic Cosmos payloads**
(system-managed keys included). No Cosmos connection required.

Regression guard: ``SessionDocument`` is ``extra='forbid'`` and Cosmos
decorates every stored document with ``id`` + underscore-prefixed system
keys. Before this test existed, ``_document_from_item`` stripped the
underscore keys but *not* ``id``, so every read (``GET /threads``,
``GET /threads/{id}``, and the thread-pin lookup on ``POST /chat``)
raised ``ValidationError`` and surfaced to the caller as a misleading
HTTP 400 "Request body failed validation".

The only pre-existing coverage was ``tests/integration/test_cosmos.py``,
which is gated behind ``EGP_TEST_COSMOS=1`` and needs an emulator — so
the break went unnoticed until deployment.
"""

from __future__ import annotations

from typing import Any

import pytest

from egp_maf.services.thread_state import ThreadStateProvider
from egp_maf.state.session_document import SessionDocument, SessionMessage

pytestmark = pytest.mark.unit


def _cosmos_item(**overrides: Any) -> dict[str, Any]:
    """A document shaped exactly as Cosmos returns it.

    Mirrors a real ``read_item`` response: our persisted fields, the
    ``id`` item key, and the five system-managed underscore keys.
    """
    item: dict[str, Any] = {
        "id": "T-549eb8ec3e654c1b",
        "schema_version": 1,
        "thread_id": "T-549eb8ec3e654c1b",
        "clinician_id": "demo",
        "tenant_id": "t1",
        "patient_id": "PGP001",
        "clinician_specialty": None,
        "title": "Family history review",
        "created_at": "2026-08-19T07:14:32.662149Z",
        "last_activity": "2026-08-19T07:14:32.662149Z",
        "ttl": 86400,
        "messages": [],
        "agents_completed": [],
        "results": {},
        # Cosmos system-managed keys.
        "_rid": "DqFcAKjthO8BAAAAAAAAAA==",
        "_self": "dbs/DqFcAA==/colls/DqFcAKjthO8=/docs/DqFcAKjthO8BAAAAAAAAAA==/",
        "_etag": '"0f00f206-0000-3200-0000-6a8557d80000"',
        "_attachments": "attachments/",
        "_ts": 1787066072,
    }
    item.update(overrides)
    return item


class TestDocumentFromItem:
    def test_accepts_realistic_cosmos_item(self) -> None:
        """The core regression: a real Cosmos payload must validate."""
        doc = ThreadStateProvider._document_from_item(_cosmos_item())

        assert doc.thread_id == "T-549eb8ec3e654c1b"
        assert doc.clinician_id == "demo"
        assert doc.patient_id == "PGP001"
        assert doc.title == "Family history review"

    def test_lifts_etag_onto_model(self) -> None:
        doc = ThreadStateProvider._document_from_item(_cosmos_item())

        assert doc.etag == '"0f00f206-0000-3200-0000-6a8557d80000"'

    def test_does_not_mutate_caller_dict(self) -> None:
        """``query_items`` pages are reused — mapping must be pure."""
        item = _cosmos_item()
        before = dict(item)

        ThreadStateProvider._document_from_item(item)

        assert item == before

    def test_tolerates_unknown_future_system_keys(self) -> None:
        """Any new underscore-prefixed Cosmos key must not break reads."""
        item = _cosmos_item(_lsn=56, _some_future_field="whatever")

        doc = ThreadStateProvider._document_from_item(item)

        assert doc.thread_id == "T-549eb8ec3e654c1b"

    def test_parses_messages(self) -> None:
        item = _cosmos_item(
            messages=[
                {
                    "role": "user",
                    "content": "What is this patient's BRCA1 status?",
                    "timestamp": "2026-08-19T07:14:33Z",
                    "message_id": None,
                },
                {
                    "role": "assistant",
                    "content": "Retrieved 2 variants.",
                    "timestamp": "2026-08-19T07:14:39Z",
                    "message_id": None,
                },
            ]
        )

        doc = ThreadStateProvider._document_from_item(item)

        assert [m.role for m in doc.messages] == ["user", "assistant"]
        assert doc.messages[0].content.startswith("What is this patient's")

    def test_item_id_wins_when_thread_id_disagrees(self) -> None:
        """``id`` is the authoritative Cosmos key; a mismatch is repaired."""
        item = _cosmos_item(thread_id="T-stale")

        doc = ThreadStateProvider._document_from_item(item)

        assert doc.thread_id == "T-549eb8ec3e654c1b"


class TestRoundTrip:
    def test_save_shape_reloads_cleanly(self) -> None:
        """What we write must be readable back — the invariant that broke.

        Simulates the full path: dump for Cosmos, let Cosmos decorate the
        payload with its system keys, then read it back.
        """
        provider = ThreadStateProvider.__new__(ThreadStateProvider)
        original = SessionDocument(
            thread_id="T-roundtrip",
            clinician_id="demo",
            tenant_id="t1",
            patient_id="PGP001",
            title="Round trip",
        ).with_message(SessionMessage(role="user", content="hello"))

        stored = provider._item_from_document(original)
        # Cosmos stamps these on write.
        stored.update(
            {
                "_rid": "abc==",
                "_self": "dbs/x/colls/y/docs/z/",
                "_etag": '"aaaa-bbbb"',
                "_attachments": "attachments/",
                "_ts": 1787066072,
            }
        )

        reloaded = ThreadStateProvider._document_from_item(stored)

        assert reloaded.thread_id == original.thread_id
        assert reloaded.clinician_id == original.clinician_id
        assert reloaded.patient_id == original.patient_id
        assert reloaded.title == original.title
        assert len(reloaded.messages) == 1
        assert reloaded.messages[0].content == "hello"
        assert reloaded.etag == '"aaaa-bbbb"'

    def test_item_from_document_sets_cosmos_id(self) -> None:
        provider = ThreadStateProvider.__new__(ThreadStateProvider)
        doc = SessionDocument(
            thread_id="T-abc",
            clinician_id="demo",
            tenant_id="t1",
            patient_id="PGP001",
        )

        payload = provider._item_from_document(doc)

        assert payload["id"] == "T-abc"
        # ``etag`` is ``exclude=True`` — it must never be persisted.
        assert "etag" not in payload
