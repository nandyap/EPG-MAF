"""Load-test entry — F12.5 (activated in W11).

Usage (against preprod):

    locust --host https://egp-preprod.example.com \
           -u 20 -r 2 --run-time 15m -f tests/load/locustfile.py

Configure via env:

- ``EGP_LOAD_BEARER`` — pre-minted Entra token for the load user
  (see ``docs/security/entra.md`` for a service-principal minting
  script; NEVER hard-code a real clinician's token).
- ``EGP_LOAD_PATIENT_IDS`` — comma-separated list of seeded patient
  ids (defaults to ``P001,P002,P003,P004,P005``).

Results feed the baseline captured in
``docs/testing/load-history/``.
"""

from __future__ import annotations

import os
import random
import uuid

from locust import HttpUser, between, task


_TOKEN = os.environ.get("EGP_LOAD_BEARER", "")
_PATIENTS = [
    pid.strip()
    for pid in os.environ.get(
        "EGP_LOAD_PATIENT_IDS", "P001,P002,P003,P004,P005"
    ).split(",")
    if pid.strip()
]


def _fresh_thread() -> str:
    return f"load-{uuid.uuid4()}"


class ClinicianUser(HttpUser):
    """One virtual clinician issuing a mix of turn types."""

    wait_time = between(1.0, 3.0)

    def on_start(self) -> None:
        if not _TOKEN:
            raise RuntimeError(
                "EGP_LOAD_BEARER is not set. Mint a service-principal token "
                "per docs/security/entra.md before running."
            )
        self.headers = {"Authorization": f"Bearer {_TOKEN}"}

    @task(3)
    def multi_domain_turn(self) -> None:
        self.client.post(
            "/chat",
            headers=self.headers,
            json={
                "thread_id": _fresh_thread(),
                "patient_id": random.choice(_PATIENTS),
                "message": "Summarise everything we know about this patient.",
            },
            name="/chat multi-domain",
        )

    @task(2)
    def prs_turn(self) -> None:
        self.client.post(
            "/chat",
            headers=self.headers,
            json={
                "thread_id": _fresh_thread(),
                "patient_id": random.choice(_PATIENTS),
                "message": "What PRS does this patient have?",
            },
            name="/chat prs",
        )

    @task(1)
    def family_history_turn(self) -> None:
        self.client.post(
            "/chat",
            headers=self.headers,
            json={
                "thread_id": _fresh_thread(),
                "patient_id": random.choice(_PATIENTS),
                "message": "Does the patient meet NCCN HBOC criteria?",
            },
            name="/chat family-history",
        )

    @task(1)
    def healthz(self) -> None:
        self.client.get("/healthz", name="/healthz")
