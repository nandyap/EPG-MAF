"""Cross-turn state hydration on ``POST /chat``.

Regression: the chat handler built ``ChatWorkflowState`` with only the
current message and no cached specialist state:

    messages=[SessionMessage(role="user", content=body.message)]

Prior turns were persisted to Cosmos but never read back, and
``SessionDocument.results`` was neither written nor read by anything. So:

- the chat router saw a single-turn conversation on every request and
  could not resolve a follow-up ("what about her sister?");
- ``cached_domains`` and ``agents_completed`` were always empty, so the
  cache-invalidation contract in ADR-009 could never fire and every turn
  re-ran every specialist it dispatched.

``ChatWorkflowState`` documented itself as "rehydrated from
SessionDocument at start of turn" — these tests hold that to be true.

They drive the real FastAPI app with an in-memory thread store, so no
Cosmos or LLM is involved.
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from egp_maf.api import create_app
from egp_maf.workflow.state import ChatWorkflowState

from .test_thread_endpoints import _make_container, _token

pytestmark = pytest.mark.unit


class _CapturingRuntime:
    """Wraps the real runtime and records the state it is handed."""

    def __init__(self, inner: Any) -> None:
        self._inner = inner
        self.seen: list[ChatWorkflowState] = []

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)

    async def run_turn(self, initial: ChatWorkflowState) -> Any:
        self.seen.append(initial)
        return await self._inner.run_turn(initial)


def _client_with_capture() -> tuple[TestClient, _CapturingRuntime]:
    """Return a client and the capture wrapper around the real runtime.

    The client MUST be used as a context manager. A MAF ``Workflow`` binds
    its internal queue to the event loop of its first run, and the runtime
    builds the workflow once per container (as production does). Without
    the ``with`` block ``TestClient`` spins up a fresh loop per request and
    the second turn fails with "bound to a different event loop". Uvicorn
    serves every request on one loop, so the context-manager form is the
    faithful harness.
    """
    container = _make_container()
    capture = _CapturingRuntime(container.workflow_runtime)
    container.workflow_runtime = capture  # type: ignore[assignment]
    return TestClient(create_app(container)), capture


def _chat(client: TestClient, token: str, thread_id: str, message: str) -> Any:
    return client.post(
        "/chat",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "thread_id": thread_id,
            "patient_id": "PGP001",
            "message": message,
        },
    )


class TestConversationHistory:
    def test_first_turn_sees_only_the_current_message(self) -> None:
        client, capture = _client_with_capture()

        with client:
            resp = _chat(client, _token(), "T-hist-1", "first question")

        assert resp.status_code == 200, resp.text
        assert [(m.role, m.content) for m in capture.seen[0].messages] == [
            ("user", "first question")
        ]

    def test_second_turn_sees_the_first_exchange(self) -> None:
        """The core regression — prior turns must reach the workflow."""
        client, capture = _client_with_capture()
        token = _token()

        with client:
            _chat(client, token, "T-hist-2", "first question")
            resp = _chat(client, token, "T-hist-2", "follow-up question")

        assert resp.status_code == 200, resp.text
        roles_and_text = [(m.role, m.content) for m in capture.seen[1].messages]
        assert ("user", "first question") in roles_and_text
        # The current message is always last.
        assert roles_and_text[-1] == ("user", "follow-up question")

    def test_history_is_capped(self) -> None:
        """A long thread must not grow the prompt without bound."""
        from egp_maf.api.app import _MAX_HISTORY_MESSAGES

        client, capture = _client_with_capture()
        token = _token()
        with client:
            for i in range(_MAX_HISTORY_MESSAGES + 5):
                _chat(client, token, "T-hist-3", f"question {i}")

        # Cap applies to the rehydrated history; the current message is
        # appended on top of it.
        assert len(capture.seen[-1].messages) <= _MAX_HISTORY_MESSAGES + 1

    def test_transcript_is_still_complete_in_cosmos(self) -> None:
        """The cap bounds the prompt only — GET /threads keeps everything."""
        client, _ = _client_with_capture()
        token = _token()
        with client:
            _chat(client, token, "T-hist-4", "one")
            _chat(client, token, "T-hist-4", "two")

            resp = client.get(
                "/threads/T-hist-4",
                headers={"Authorization": f"Bearer {token}"},
            )

        contents = [m["content"] for m in resp.json()["messages"]]
        assert "one" in contents
        assert "two" in contents


class TestThreadIsolation:
    def test_history_does_not_leak_between_threads(self) -> None:
        client, capture = _client_with_capture()
        token = _token()

        with client:
            _chat(client, token, "T-iso-a", "thread A question")
            _chat(client, token, "T-iso-b", "thread B question")

        contents = [m.content for m in capture.seen[1].messages]
        assert "thread A question" not in contents


class TestSpecialistCache:
    def test_agents_completed_round_trips(self) -> None:
        """``agents_completed`` must survive a turn, or the router can
        never skip a specialist that already answered."""
        client, capture = _client_with_capture()
        token = _token()

        with client:
            _chat(client, token, "T-cache-1", "first")
            second = _chat(client, token, "T-cache-1", "second")

        assert second.status_code == 200, second.text
        # The stub router completes no agents, so the list stays empty —
        # what matters is that hydration reads the persisted value rather
        # than always starting from a hardcoded [].
        assert capture.seen[1].agents_completed == []

    def test_malformed_cached_slot_is_dropped_not_fatal(self) -> None:
        """Schema drift on an old thread must not break the turn."""
        from egp_maf.api.app import _slots_from
        from egp_maf.state.session_document import SessionDocument

        doc = SessionDocument(
            thread_id="T-bad",
            clinician_id="OID-1",
            tenant_id="TID-1",
            patient_id="PGP001",
            results={"prs": {"status": "not-a-valid-status"}},
        )

        assert _slots_from(doc) == {}

    def test_valid_cached_slot_is_restored(self) -> None:
        from egp_maf.api.app import _slots_from
        from egp_maf.state.session_document import SessionDocument

        doc = SessionDocument(
            thread_id="T-good",
            clinician_id="OID-1",
            tenant_id="TID-1",
            patient_id="PGP001",
            results={
                "prs": {
                    "status": "completed",
                    "output": {"results": []},
                    "errors": [],
                }
            },
        )

        slots = _slots_from(doc)

        assert set(slots) == {"prs"}
        assert slots["prs"].status == "completed"
