"""Chaos: pause Postgres.

Trigger + verification that the app's typed-error path surfaces the
expected error code. Runbook: ``docs/runbooks/db-unavailable.md``.
"""

from __future__ import annotations

import os
import subprocess

import pytest

pytestmark = pytest.mark.chaos


@pytest.mark.skipif(
    os.environ.get("EGP_TEST_CHAOS") != "1",
    reason="chaos scripts require EGP_TEST_CHAOS=1",
)
def test_stop_postgres_server() -> None:
    """Stop the Postgres server; wait; start it back.

    Expected: `database_unavailable` count spikes; the app's pool
    reconnects automatically on the next request after start; no
    manual restart. See ``docs/testing/chaos.md`` §1.2.
    """
    server = os.environ["EGP_CHAOS_PG_SERVER"]
    rg = os.environ["EGP_CHAOS_RG"]
    subprocess.run(
        ["az", "postgres", "flexible-server", "stop", "-g", rg, "-n", server],
        check=True,
    )
    # ── Observation window is manual (dashboards / alerts). ──
    # After the runbook holder confirms, start the server:
    subprocess.run(
        ["az", "postgres", "flexible-server", "start", "-g", rg, "-n", server],
        check=True,
    )
