"""Slice 5 — frontend-facing endpoints.

Covers:

- ``GET /api/me`` — identity lookup that never raises.
- ``GET /threads/{thread_id}`` — thread transcript with the same
  ``patient_unavailable`` enumeration defence as the rest of the API.
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from fastapi.testclient import TestClient

from egp_maf.api import create_app

from .test_thread_endpoints import _make_container, _token

pytestmark = pytest.mark.unit


# ── GET /api/me ────────────────────────────────────────────────────


class TestGetMe:
    def test_returns_authenticated_true_with_valid_bearer(self) -> None:
        client = TestClient(create_app(_make_container()))
        resp = client.get(
            "/api/me",
            headers={"Authorization": f"Bearer {_token()}"},
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["authenticated"] is True
        assert body["clinician_id"] == "OID-1"
        assert "Clinician" in body["roles"]

    def test_no_bearer_returns_unauthenticated_not_error(self) -> None:
        client = TestClient(create_app(_make_container()))
        resp = client.get("/api/me")
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["authenticated"] is False
        assert body["clinician_id"] is None
        assert body["roles"] == []

    def test_invalid_bearer_returns_unauthenticated_not_error(self) -> None:
        client = TestClient(create_app(_make_container()))
        resp = client.get(
            "/api/me",
            headers={"Authorization": "Bearer not-json"},
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["authenticated"] is False


# ── GET /threads/{thread_id} ───────────────────────────────────────


def _create_thread(client: TestClient, token: str, patient_id: str) -> str:
    resp = client.post(
        "/threads",
        headers={"Authorization": f"Bearer {token}"},
        json={"patient_id": patient_id},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["thread_id"]


class TestGetThread:
    def test_owner_gets_thread_with_empty_messages(self) -> None:
        client = TestClient(create_app(_make_container()))
        token = _token()
        thread_id = _create_thread(client, token, "PGP001")

        resp = client.get(
            f"/threads/{thread_id}",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["thread_id"] == thread_id
        assert body["patient_id"] == "PGP001"
        assert body["messages"] == []

    def test_unknown_thread_returns_404_patient_unavailable(self) -> None:
        client = TestClient(create_app(_make_container()))
        resp = client.get(
            "/threads/T-does-not-exist",
            headers={"Authorization": f"Bearer {_token()}"},
        )
        assert resp.status_code == 404
        body = resp.json()
        assert body["error_code"] == "patient_unavailable"
        assert "not available" in body["message"].lower()

    def test_cross_clinician_returns_404_same_shape(self) -> None:
        """Enumeration defence: a thread owned by another clinician is
        indistinguishable from a non-existent one.
        """
        client = TestClient(create_app(_make_container()))
        thread_id = _create_thread(client, _token(oid="OID-1"), "PGP001")

        resp = client.get(
            f"/threads/{thread_id}",
            headers={"Authorization": f"Bearer {_token(oid='OID-2')}"},
        )
        assert resp.status_code == 404
        assert resp.json()["error_code"] == "patient_unavailable"

    def test_missing_bearer_returns_401(self) -> None:
        client = TestClient(create_app(_make_container()))
        resp = client.get("/threads/T-anything")
        assert resp.status_code == 401
