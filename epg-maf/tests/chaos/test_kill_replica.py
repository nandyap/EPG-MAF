"""Chaos: kill an ACA revision replica.

Trigger only — expected recovery is documented in
``docs/runbooks/cutover.md`` §6 rollback and Front Door replica
rebalancing.
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
def test_kill_aca_replica() -> None:
    """Restart the current ACA revision.

    Expected: Front Door detects the failed replica within 30 s; new
    requests route to healthy replicas; in-flight requests fail with
    typed 5xx. No state corruption. See
    ``docs/testing/chaos.md`` §1.1.
    """
    app = os.environ["EGP_CHAOS_APP_NAME"]
    rg = os.environ["EGP_CHAOS_RG"]
    revision = os.environ["EGP_CHAOS_REVISION"]
    result = subprocess.run(
        [
            "az",
            "containerapp",
            "revision",
            "restart",
            "--name",
            app,
            "--resource-group",
            rg,
            "--revision",
            revision,
        ],
        check=True,
    )
    assert result.returncode == 0
