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
        from azure.core import MatchConditions  # type: ignore[import-untyped]
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
                    # ``match_condition`` must be the azure.core enum, not a
                    # string — the SDK raises ``TypeError: Invalid match
                    # condition`` for anything else, client-side, before any
                    # request is issued. ``IfNotModified`` is the enum that
                    # maps to the ``If-Match: <etag>`` header.
                    response = await container.replace_item(
                        item=stamped.thread_id,
                        body=payload,
                        etag=doc.etag,
                        match_condition=MatchConditions.IfNotModified,
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

    # ── Slice 1: thread pinning helpers (B-002 + B-005) ─────────────
    # Every thread pins exactly one ``patient_id`` at create time. The
    # pin is immutable — a new patient means a new thread.

    async def create_thread(
        self,
        *,
        clinician_id: str,
        tenant_id: str,
        patient_id: str,
        thread_id: str | None = None,
        clinician_specialty: str | None = None,
        title: str | None = None,
    ) -> SessionDocument:
        """Create and persist a fresh thread pinned to ``patient_id``.

        Callers (typically the ``POST /threads`` route) MUST have already
        verified that the patient exists and that the clinician is
        allow-listed. This method only performs the write.
        """
        import uuid

        doc = SessionDocument(
            thread_id=thread_id or f"T-{uuid.uuid4().hex[:16]}",
            clinician_id=clinician_id,
            tenant_id=tenant_id,
            patient_id=patient_id,
            clinician_specialty=clinician_specialty,
            title=title,
        )
        return await self.save(doc)

    async def get_patient_id(
        self, thread_id: str, clinician_id: str
    ) -> str | None:
        """Return the ``patient_id`` pinned on the thread, or ``None`` if
        the thread does not exist.

        Called on every ``POST /chat`` to enforce
        ``body.patient_id == thread.patient_id``.
        """
        doc = await self.load(thread_id, clinician_id)
        return doc.patient_id if doc is not None else None

    async def list_by_patient(
        self,
        *,
        clinician_id: str,
        patient_id: str,
        limit: int = 50,
    ) -> list[SessionDocument]:
        """Return the clinician's threads for a specific patient.

        Ordered by ``last_activity`` DESC. Powers the ChatGPT-style
        sidebar (B-005).
        """
        from azure.cosmos import exceptions as cosmos_exc  # type: ignore[import-untyped]

        container = await self._container_proxy()
        query = (
            "SELECT * FROM c "
            "WHERE c.clinician_id = @clinician_id "
            "  AND c.patient_id = @patient_id "
            "ORDER BY c.last_activity DESC"
        )
        params: list[dict[str, Any]] = [
            {"name": "@clinician_id", "value": clinician_id},
            {"name": "@patient_id", "value": patient_id},
        ]
        results: list[SessionDocument] = []
        try:
            async for item in container.query_items(
                query=query,
                parameters=params,
                partition_key=clinician_id,
            ):
                results.append(self._document_from_item(item))
                if len(results) >= limit:
                    break
        except cosmos_exc.CosmosHttpResponseError as exc:  # pragma: no cover
            raise CosmosUnavailable(
                f"Failed to list threads for clinician {clinician_id}"
            ) from exc
        return results

    async def list_recent(
        self,
        *,
        clinician_id: str,
        limit: int = 50,
    ) -> list[SessionDocument]:
        """Return the clinician's most recently active threads across all
        patients — ordered by ``last_activity`` DESC.

        Powers the frontend's initial sidebar load (Slice 2).
        """
        from azure.cosmos import exceptions as cosmos_exc  # type: ignore[import-untyped]

        container = await self._container_proxy()
        query = (
            "SELECT * FROM c "
            "WHERE c.clinician_id = @clinician_id "
            "ORDER BY c.last_activity DESC"
        )
        params: list[dict[str, Any]] = [
            {"name": "@clinician_id", "value": clinician_id},
        ]
        results: list[SessionDocument] = []
        try:
            async for item in container.query_items(
                query=query,
                parameters=params,
                partition_key=clinician_id,
            ):
                results.append(self._document_from_item(item))
                if len(results) >= limit:
                    break
        except cosmos_exc.CosmosHttpResponseError as exc:  # pragma: no cover
            raise CosmosUnavailable(
                f"Failed to list recent threads for clinician {clinician_id}"
            ) from exc
        return results

    # ── Serialisation helpers ───────────────────────────────────────
    @staticmethod
    def _document_from_item(item: dict[str, Any]) -> SessionDocument:
        """Map a raw Cosmos item onto :class:`SessionDocument`.

        Cosmos decorates every stored document with system-managed keys
        that are NOT part of our schema:

        - ``id`` — the item key. We write it in :meth:`_item_from_document`
          (Cosmos requires it) and it mirrors ``thread_id``.
        - ``_etag`` — concurrency token, lifted onto the model's ``etag``.
        - ``_rid`` / ``_self`` / ``_attachments`` / ``_ts`` — internal.

        :class:`SessionDocument` is ``extra='forbid'``, so every one of
        these must be removed before validation or the read raises
        ``ValidationError``. We drop ``id`` plus any underscore-prefixed
        key so future Cosmos system fields cannot break reads again.
        """
        # Copy — never mutate the caller's dict (query_items reuses pages).
        payload = {k: v for k, v in item.items() if not k.startswith("_")}
        etag = item.get("_etag")

        # ``id`` is Cosmos' item key and duplicates ``thread_id``. Drop it,
        # but assert the invariant first so a mismatch is loud, not silent.
        item_id = payload.pop("id", None)
        if item_id is not None and payload.get("thread_id") != item_id:
            _logger.warning(
                "session.item_id_thread_id_mismatch",
                item_id=item_id,
                thread_id=payload.get("thread_id"),
            )
            payload["thread_id"] = item_id

        # Cosmos serialises datetimes as ISO strings — Pydantic parses them.
        doc = SessionDocument.model_validate(payload)
        return doc.model_copy(update={"etag": etag})

    def _item_from_document(self, doc: SessionDocument) -> dict[str, Any]:
        """Dump the document to a JSON-serialisable ``dict`` for Cosmos."""
        payload = doc.model_dump(mode="json")
        payload["id"] = doc.thread_id  # Cosmos requires ``id`` at the root.
        return payload
