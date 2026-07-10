"""Chaos scripts (F12.6) — activate against preprod only.

Each script has a matching runbook in ``docs/runbooks/`` that
describes the expected observable behaviour + recovery steps. These
scripts perform the *trigger* only; observation is manual (dashboards
+ alerts) and captured in a `chaos_run_manifest.json` alongside the
run.

Gated by the ``EGP_TEST_CHAOS=1`` env var and the ``chaos`` pytest
marker.
"""
