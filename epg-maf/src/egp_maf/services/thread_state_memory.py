"""In-memory :class:`ThreadStateProvider` — smoke server + unit tests.

Duck-types the same public API as
:class:`egp_maf.services.thread_state.ThreadStateProvider` (Cosmos-backed)
so it can be substituted at container-build time without any type
changes on the consumer side.

Never used in production — Cosmos is the source of truth there.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from egp_maf.state.session_document import CURRENT_SCHEMA_VERSION, SessionDocument


class InMemoryThreadStateProvider:
    """Dict-backed store keyed by ``(clinician_id, thread_id)``.

    Preserves the immutability guarantee on ``patient_id`` by ignoring
    any attempted change on ``save`` and logging a warning instead.
    """

    def __init__(self) -> None:
        # {(clinician_id, thread_id): SessionDocument}
        self._store: dict[tuple[str, str], SessionDocument] = {}
        self._etag_counter = 0

    # ── Same public API as ThreadStateProvider ─────────────────────

    async def load(
        self, thread_id: str, clinician_id: str
    ) -> SessionDocument | None:
        return self._store.get((clinician_id, thread_id))

    async def save(self, doc: SessionDocument) -> SessionDocument:
        key = (doc.clinician_id, doc.thread_id)
        # patient_id is immutable — if the caller tries to change it,
        # keep the original and log.
        existing = self._store.get(key)
        if existing is not None and existing.patient_id != doc.patient_id:
            doc = doc.model_copy(update={"patient_id": existing.patient_id})
        self._etag_counter += 1
        stamped = doc.model_copy(
            update={
                "last_activity": datetime.now(timezone.utc),
                "schema_version": doc.schema_version or CURRENT_SCHEMA_VERSION,
                "etag": f"mem-{self._etag_counter}",
            }
        )
        self._store[key] = stamped
        return stamped

    async def delete(self, thread_id: str, clinician_id: str) -> None:
        self._store.pop((clinician_id, thread_id), None)

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
        doc = await self.load(thread_id, clinician_id)
        return doc.patient_id if doc is not None else None

    async def list_by_patient(
        self,
        *,
        clinician_id: str,
        patient_id: str,
        limit: int = 50,
    ) -> list[SessionDocument]:
        matches = [
            doc
            for (cid, _tid), doc in self._store.items()
            if cid == clinician_id and doc.patient_id == patient_id
        ]
        matches.sort(key=lambda d: d.last_activity, reverse=True)
        return matches[:limit]

    async def list_recent(
        self,
        *,
        clinician_id: str,
        limit: int = 50,
    ) -> list[SessionDocument]:
        matches = [
            doc for (cid, _tid), doc in self._store.items() if cid == clinician_id
        ]
        matches.sort(key=lambda d: d.last_activity, reverse=True)
        return matches[:limit]
