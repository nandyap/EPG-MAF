"""Tests for :class:`InMemoryThreadStateProvider` — Slice 1."""

from __future__ import annotations

import pytest

from egp_maf.services.thread_state_memory import InMemoryThreadStateProvider

pytestmark = pytest.mark.unit


class TestCreateThread:
    @pytest.mark.asyncio
    async def test_persists_patient_id_pin(self) -> None:
        p = InMemoryThreadStateProvider()

        doc = await p.create_thread(
            clinician_id="alice",
            tenant_id="t1",
            patient_id="PGP001",
        )

        assert doc.clinician_id == "alice"
        assert doc.patient_id == "PGP001"
        assert doc.thread_id.startswith("T-")
        assert doc.etag is not None

    @pytest.mark.asyncio
    async def test_generates_unique_thread_ids(self) -> None:
        p = InMemoryThreadStateProvider()

        a = await p.create_thread(
            clinician_id="alice", tenant_id="t1", patient_id="PGP001"
        )
        b = await p.create_thread(
            clinician_id="alice", tenant_id="t1", patient_id="PGP002"
        )

        assert a.thread_id != b.thread_id


class TestGetPatientId:
    @pytest.mark.asyncio
    async def test_returns_pinned_patient(self) -> None:
        p = InMemoryThreadStateProvider()
        doc = await p.create_thread(
            clinician_id="alice", tenant_id="t1", patient_id="PGP001"
        )

        pid = await p.get_patient_id(doc.thread_id, "alice")

        assert pid == "PGP001"

    @pytest.mark.asyncio
    async def test_returns_none_for_unknown_thread(self) -> None:
        p = InMemoryThreadStateProvider()
        assert await p.get_patient_id("does-not-exist", "alice") is None

    @pytest.mark.asyncio
    async def test_returns_none_for_wrong_clinician(self) -> None:
        p = InMemoryThreadStateProvider()
        doc = await p.create_thread(
            clinician_id="alice", tenant_id="t1", patient_id="PGP001"
        )

        # Wrong clinician for that thread — treat as not found.
        assert await p.get_patient_id(doc.thread_id, "bob") is None


class TestPatientIdIsImmutable:
    """Slice 1 invariant — the pin cannot be changed after create."""

    @pytest.mark.asyncio
    async def test_save_ignores_patient_id_change(self) -> None:
        p = InMemoryThreadStateProvider()
        doc = await p.create_thread(
            clinician_id="alice", tenant_id="t1", patient_id="PGP001"
        )

        # Attempt to smuggle a different patient onto the existing thread.
        tampered = doc.model_copy(update={"patient_id": "PGP999"})
        saved = await p.save(tampered)

        # The original pin wins.
        assert saved.patient_id == "PGP001"

        # And a fresh load still reports the original.
        assert await p.get_patient_id(doc.thread_id, "alice") == "PGP001"


class TestListByPatient:
    @pytest.mark.asyncio
    async def test_returns_only_matching_threads(self) -> None:
        p = InMemoryThreadStateProvider()
        await p.create_thread(clinician_id="alice", tenant_id="t1", patient_id="PGP001")
        await p.create_thread(clinician_id="alice", tenant_id="t1", patient_id="PGP001")
        await p.create_thread(clinician_id="alice", tenant_id="t1", patient_id="PGP002")
        await p.create_thread(clinician_id="bob", tenant_id="t1", patient_id="PGP001")

        threads = await p.list_by_patient(clinician_id="alice", patient_id="PGP001")

        assert len(threads) == 2
        assert all(t.clinician_id == "alice" for t in threads)
        assert all(t.patient_id == "PGP001" for t in threads)

    @pytest.mark.asyncio
    async def test_respects_limit(self) -> None:
        p = InMemoryThreadStateProvider()
        for _ in range(5):
            await p.create_thread(
                clinician_id="alice", tenant_id="t1", patient_id="PGP001"
            )

        threads = await p.list_by_patient(
            clinician_id="alice", patient_id="PGP001", limit=2
        )

        assert len(threads) == 2


class TestListRecent:
    """Slice 2: cross-patient listing for the sidebar's initial load."""

    @pytest.mark.asyncio
    async def test_returns_all_clinicians_threads_across_patients(self) -> None:
        p = InMemoryThreadStateProvider()
        await p.create_thread(clinician_id="alice", tenant_id="t1", patient_id="PGP001")
        await p.create_thread(clinician_id="alice", tenant_id="t1", patient_id="PGP002")
        await p.create_thread(clinician_id="alice", tenant_id="t1", patient_id="PGP003")
        # Different clinician — must not appear.
        await p.create_thread(clinician_id="bob", tenant_id="t1", patient_id="PGP001")

        threads = await p.list_recent(clinician_id="alice")

        assert len(threads) == 3
        assert {t.patient_id for t in threads} == {"PGP001", "PGP002", "PGP003"}

    @pytest.mark.asyncio
    async def test_ordered_by_last_activity_desc(self) -> None:
        p = InMemoryThreadStateProvider()
        first = await p.create_thread(
            clinician_id="alice", tenant_id="t1", patient_id="PGP001"
        )
        # Touch first's activity so it's clearly newer than second.
        second = await p.create_thread(
            clinician_id="alice", tenant_id="t1", patient_id="PGP002"
        )
        # Re-save first so its last_activity is later than second's.
        await p.save(first)

        threads = await p.list_recent(clinician_id="alice")

        assert threads[0].thread_id == first.thread_id
        assert threads[1].thread_id == second.thread_id


class TestTitleField:
    @pytest.mark.asyncio
    async def test_title_persists_through_save(self) -> None:
        p = InMemoryThreadStateProvider()
        doc = await p.create_thread(
            clinician_id="alice",
            tenant_id="t1",
            patient_id="PGP001",
            title="Follow-up chat",
        )
        assert doc.title == "Follow-up chat"

        loaded = await p.load(doc.thread_id, "alice")
        assert loaded is not None
        assert loaded.title == "Follow-up chat"
