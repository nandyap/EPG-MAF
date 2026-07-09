"""Cosmos-backed session (thread) state provider.

Reads and writes :class:`~egp_maf.state.session_document.SessionDocument`
records in Cosmos with:

- Partition key = ``clinician_id``.
- Item id = ``thread_id``.
- ETag-based optimistic concurrency on writes.
- ``ttl`` refreshed on every save (Cosmos native TTL sweeps expired docs).

Cosmos concurrency policy (Design §11.4, §13.8):
- ``save`` uses ``if_match=<etag>`` when the document already exists.
- On ``PreconditionFailed`` (412), one retry with a fresh load. Second
  conflict raises :class:`ConcurrencyConflict`.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from egp_maf.config.settings import Settings
from egp_maf.errors import ConcurrencyConflict, CosmosUnavailable
from egp_maf.infrastructure.cosmos_client import CosmosClientFactory
from egp_maf.logging.setup import get_logger
from egp_maf.state.session_document import CURRENT_SCHEMA_VERSION, SessionDocument

if TYPE_CHECKING:  # pragma: no cover
    from azure.cosmos.aio import ContainerProxy

_logger = get_logger(__name__)


class ThreadStateProvider:
    """Persists :class:`SessionDocument` records in Cosmos DB."""

    def __init__(
        self,
        cosmos_factory: CosmosClientFactory,
        settings: Settings,
    ) -> None:
        self._cosmos = cosmos_factory
        self._settings = settings
        self._container: "ContainerProxy | None" = None

    async def _container_proxy(self) -> "ContainerProxy":
        if self._container is None:
            self._container = await self._cosmos.get_container()
        return self._container

    # ── CRUD ────────────────────────────────────────────────────────
    async def load(self, thread_id: str, clinician_id: str) -> SessionDocument | None:
        """Return the session document, or ``None`` if it does not exist."""
        # Import lazily so tests can run without azure-cosmos installed.
        from azure.cosmos import exceptions as cosmos_exc  # type: ignore[import-untyped]

        container = await self._container_proxy()

        try:
            item = await container.read_item(item=thread_id, partition_key=clinician_id)
        except cosmos_exc.CosmosResourceNotFoundError:
            return None
        except cosmos_exc.CosmosHttpResponseError as exc:  # pragma: no cover
            raise CosmosUnavailable(
                f"Failed to load session {thread_id} for {clinician_id}"
            ) from exc

        return self._document_from_item(item)

    async def save(self, doc: SessionDocument) -> SessionDocument:
        """Persist the document with ETag-conditional concurrency.

        Returns a new :class:`SessionDocument` with an updated ``etag``.
        On concurrency conflict, retries once with a fresh load. If the
        retry also conflicts, raises :class:`ConcurrencyConflict`.
        """
        from azure.cosmos import exceptions as cosmos_exc  # type: ignore[import-untyped]

        container = await self._container_proxy()

        # Refresh mutable timestamps + TTL on every save.
        stamped = doc.model_copy(
            update={
                "last_activity": datetime.now(timezone.utc),
                "ttl": self._settings.cosmos_session_ttl_seconds,
                "schema_version": doc.schema_version or CURRENT_SCHEMA_VERSION,
            }
        )
        payload = self._item_from_document(stamped)

        for attempt in (1, 2):
            try:
                if doc.etag is None:
                    response = await container.upsert_item(body=payload)
                else:
                    response = await container.replace_item(
                        item=stamped.thread_id,
                        body=payload,
                        etag=doc.etag,
                        match_condition="IfMatch",
                    )
                new_etag = response.get("_etag")
                return stamped.model_copy(update={"etag": new_etag})
            except cosmos_exc.CosmosAccessConditionFailedError:
                _logger.warning(
                    "session.save.etag_conflict",
                    thread_id=stamped.thread_id,
                    attempt=attempt,
                )
                if attempt == 2:
                    raise ConcurrencyConflict(
                        f"ETag conflict on session {stamped.thread_id} after retry"
                    )
                # Reload and merge — simplest strategy is: use the caller's
                # payload but with the fresh etag. The caller is responsible
                # for message-append semantics.
                latest = await self.load(stamped.thread_id, stamped.clinician_id)
                if latest is not None:
                    doc = doc.model_copy(update={"etag": latest.etag})
            except cosmos_exc.CosmosHttpResponseError as exc:  # pragma: no cover
                raise CosmosUnavailable(
                    f"Failed to save session {stamped.thread_id}"
                ) from exc
        # Unreachable: the loop always returns or raises.
        raise ConcurrencyConflict("Unreachable")

    async def delete(self, thread_id: str, clinician_id: str) -> None:
        """Delete the session document if it exists."""
        from azure.cosmos import exceptions as cosmos_exc  # type: ignore[import-untyped]

        container = await self._container_proxy()
        try:
            await container.delete_item(item=thread_id, partition_key=clinician_id)
        except cosmos_exc.CosmosResourceNotFoundError:
            return
        except cosmos_exc.CosmosHttpResponseError as exc:  # pragma: no cover
            raise CosmosUnavailable(
                f"Failed to delete session {thread_id} for {clinician_id}"
            ) from exc

    # ── Serialisation helpers ───────────────────────────────────────
    @staticmethod
    def _document_from_item(item: dict[str, Any]) -> SessionDocument:
        etag = item.pop("_etag", None)
        # Strip Cosmos-internal keys that would fail ``extra='forbid'``.
        for key in ("_rid", "_self", "_attachments", "_ts"):
            item.pop(key, None)
        # Cosmos serialises datetimes as ISO strings — Pydantic parses them.
        doc = SessionDocument.model_validate(item)
        return doc.model_copy(update={"etag": etag})

    def _item_from_document(self, doc: SessionDocument) -> dict[str, Any]:
        """Dump the document to a JSON-serialisable ``dict`` for Cosmos."""
        payload = doc.model_dump(mode="json")
        payload["id"] = doc.thread_id  # Cosmos requires ``id`` at the root.
        return payload
