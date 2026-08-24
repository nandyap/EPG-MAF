"""Run the golden set against the live backend and print a scored report.

**Runs inside the backend container.** The backend Container App is
provisioned with ``ingress.external = false``, so nothing outside the
Container Apps environment can reach it — not the VDI, not the jumpbox.
Hitting ``localhost`` from within the container sidesteps that entirely
and needs no network change::

    az containerapp exec -n egpmaf-dev-backend \
        -g rg-ailz-egpwin-dev-m42-aen-001 --command /bin/sh

    python -m egp_maf.tools.golden_run --list
    python -m egp_maf.tools.golden_run --domain pgx
    python -m egp_maf.tools.golden_run --id golden.s1.prs_breast
    python -m egp_maf.tools.golden_run                 # all items
    python -m egp_maf.tools.golden_run --json > /tmp/golden.json

Each item is a real clinical turn (~35 s), so the full set of 55 takes
roughly half an hour. Use ``--domain`` while iterating.

Scoring is delegated to :mod:`egp_maf.evals.harness` — this module only
drives it over HTTP and formats the result. Items are given their own
thread id so no run inherits cached specialist slots from another.

The exit code is 1 if any item fails (excluding expected-fails), so this
can gate a release without anyone reading the output.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from typing import Any

import httpx

from egp_maf.evals.golden import GoldenItem, load_golden_set
from egp_maf.evals.scorers import (
    FactSubstringScorer,
    ForbiddenSubstringScorer,
    RefusalShapeScorer,
    ScorerResult,
)

# The image serves uvicorn on ``${PORT:-8080}`` (Dockerfile CMD), and the
# Container App sets targetPort 8080 — not 8000.
#
# Use the literal 127.0.0.1 rather than "localhost": httpx resolves
# localhost to ::1 first, and the container has no usable IPv6 loopback,
# which surfaces as ``[Errno 99] Cannot assign requested address`` at
# connect time — distinct from the ECONNREFUSED a wrong port would give.
_DEFAULT_BASE_URL = f"http://127.0.0.1:{os.environ.get('PORT', '8080')}"


# The stub authenticator treats the bearer token as a JSON claim dict
# (auth/authenticator.py::StubAuthenticator). ``oid`` and ``tid`` are the
# only required claims — claims_to_context raises without them.
#
# The role is read from settings rather than hardcoded: ``has_role`` is an
# exact, case-sensitive membership test against
# ``settings.auth_required_role`` (default "Clinician"), so a literal
# "clinician" here fails with 401 and no hint about the casing.
def _stub_claims() -> dict[str, Any]:
    from egp_maf.config.settings import get_settings

    required_role = get_settings().auth_required_role
    return {
        "oid": "golden-runner",
        "tid": "golden-tenant",
        "roles": [required_role] if required_role else [],
        "name": "Golden Set Runner",
    }


def _token() -> str:
    return os.environ.get("GOLDEN_BEARER_TOKEN") or json.dumps(_stub_claims())


def _score(item: GoldenItem, reply: str, agents: list[str]) -> dict[str, ScorerResult]:
    """Apply whichever scorers this item declares. Mirrors harness.py."""
    scores: dict[str, ScorerResult] = {}
    if item.expected_refusal_substrings or (item.tags and "cohort_allowed" in item.tags):
        scores["refusal_shape"] = RefusalShapeScorer().score(
            item, reply=reply, agents_completed=agents
        )
    if item.expected_fact_substrings:
        scores["fact_substring"] = FactSubstringScorer().score(item, reply=reply)
    if item.forbidden_substrings:
        scores["forbidden_substring"] = ForbiddenSubstringScorer().score(
            item, reply=reply
        )
    return scores


def _provenance_counts(body: dict[str, Any]) -> tuple[int, int]:
    """Return ``(findings, findings_with_provenance)`` across all slots.

    Not part of the declared golden-set scoring — surfaced because a
    finding with zero provenance renders in the UI as "No database record
    was linked to this finding", and that is worth catching in a batch run
    rather than one screenshot at a time.
    """
    findings = 0
    evidenced = 0
    for key in ("prs", "genomic_variants", "family_history", "pgx", "phenotype"):
        slot = body.get(key)
        if not isinstance(slot, dict):
            continue
        inner = (slot.get("output") or {}).get("output") or {}
        for result in inner.get("results") or []:
            if not isinstance(result, dict):
                continue
            findings += 1
            if result.get("provenance"):
                evidenced += 1
    return findings, evidenced


def run_item(
    client: httpx.Client,
    item: GoldenItem,
    *,
    timeout: float,
) -> dict[str, Any]:
    """Drive one item through ``POST /chat`` and score the reply."""
    started = time.monotonic()
    try:
        resp = client.post(
            "/chat",
            headers={"Authorization": f"Bearer {_token()}"},
            json={
                # Fresh thread per item: specialist slots are cached across
                # turns, so a shared thread would let one item's results
                # satisfy another's assertions.
                "thread_id": f"T-golden-{item.id}",
                "patient_id": item.patient_id,
                "message": item.question,
            },
            timeout=timeout,
        )
    except httpx.HTTPError as exc:
        return {
            "id": item.id,
            "domain": item.domain,
            "status": "ERROR",
            "error": f"{exc.__class__.__name__}: {exc}",
            "duration_s": round(time.monotonic() - started, 1),
        }

    duration = round(time.monotonic() - started, 1)
    if resp.status_code != 200:
        return {
            "id": item.id,
            "domain": item.domain,
            "status": "ERROR",
            "error": f"HTTP {resp.status_code}: {resp.text[:200]}",
            "duration_s": duration,
        }

    body = resp.json()
    reply = body.get("reply") or ""
    agents = body.get("agents_completed") or []

    # A full run is ~30 minutes of real clinical turns. An unexpected
    # error while scoring one item must not discard everything already
    # collected, so scoring failures are recorded as that item's result
    # rather than propagating.
    try:
        scores = _score(item, reply, agents)
        findings, evidenced = _provenance_counts(body)
    except Exception as exc:  # noqa: BLE001 — deliberately broad, see above
        return {
            "id": item.id,
            "domain": item.domain,
            "status": "ERROR",
            "error": f"scoring failed: {exc.__class__.__name__}: {exc}",
            "duration_s": duration,
            "reply": reply,
        }

    passed = all(s.passed for s in scores.values()) if scores else True

    if passed:
        status = "PASS"
    elif item.expected_fail_reason:
        status = "XFAIL"
    else:
        status = "FAIL"

    return {
        "id": item.id,
        "domain": item.domain,
        "question": item.question,
        "patient_id": item.patient_id,
        "status": status,
        "duration_s": duration,
        "agents_completed": agents,
        "findings": findings,
        "findings_with_provenance": evidenced,
        "failed_scorers": {
            # ScorerResult is (passed, score, reason) — the explanation
            # field is ``reason``, not ``detail``.
            name: f"{s.reason} (score {s.score:.2f})"
            for name, s in scores.items()
            if not s.passed
        },
        "expected_fail_reason": item.expected_fail_reason,
        "reply": reply,
    }


def _print_row(r: dict[str, Any]) -> None:
    mark = {"PASS": "PASS ", "FAIL": "FAIL ", "XFAIL": "xfail", "ERROR": "ERR  "}[
        r["status"]
    ]
    prov = ""
    if r.get("findings"):
        prov = f"  prov {r['findings_with_provenance']}/{r['findings']}"
    print(f"  {mark} {r['id']:<38} {r['domain']:<16} {r['duration_s']:>6}s{prov}")
    if r["status"] == "ERROR":
        print(f"        {r['error']}")
    for name, detail in (r.get("failed_scorers") or {}).items():
        print(f"        {name}: {detail}")
    # Show the reply whenever a scorer rejected it. The scorers are exact
    # substring tests, so "missing X" can mean the answer was wrong, or
    # that it said the same thing in different words, or that this run
    # simply produced a shorter answer than a previous one. Those need
    # different responses and cannot be told apart from the summary line.
    if r.get("failed_scorers") and r.get("reply"):
        print("        --- reply ---")
        for line in str(r["reply"]).splitlines():
            print(f"        {line}")
        print("        --- end ---")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m egp_maf.tools.golden_run",
        description="Run the golden set against the live backend.",
    )
    parser.add_argument("--base-url", default=_DEFAULT_BASE_URL)
    parser.add_argument("--domain", help="Only items in this domain.")
    parser.add_argument("--id", dest="item_id", help="Only this item id.")
    parser.add_argument(
        "--list", action="store_true", help="List items without running them."
    )
    parser.add_argument(
        "--json", action="store_true", help="Emit machine-readable JSON."
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=180.0,
        help="Per-item HTTP timeout. Clinical turns take ~35 s.",
    )
    args = parser.parse_args(argv)

    items = load_golden_set()
    if args.domain:
        items = [i for i in items if i.domain == args.domain]
    if args.item_id:
        items = [i for i in items if i.id == args.item_id]

    if not items:
        print("No items matched.", file=sys.stderr)
        return 2

    if args.list:
        for i in items:
            print(f"{i.id:<40} {i.domain:<16} {i.patient_id:<10} {i.question[:60]}")
        print(f"\n{len(items)} item(s).")
        return 0

    if not args.json:
        print(f"\nRunning {len(items)} item(s) against {args.base_url}")
        print("Each clinical turn takes ~35 s.\n")

    results: list[dict[str, Any]] = []
    with httpx.Client(base_url=args.base_url) as client:
        # Probe once before spending ~35 s per item discovering the same
        # connection failure 55 times over.
        try:
            client.get("/healthz", timeout=10.0).raise_for_status()
        except httpx.HTTPError as exc:
            print(
                f"Cannot reach the API at {args.base_url}: "
                f"{exc.__class__.__name__}: {exc}\n"
                "This runner is meant to be executed INSIDE the backend "
                "container (ingress is internal-only). Check the port with "
                "`env | grep PORT`, or pass --base-url.",
                file=sys.stderr,
            )
            return 2

        for item in items:
            r = run_item(client, item, timeout=args.timeout)
            results.append(r)
            if not args.json:
                _print_row(r)
            # 401/403 is a configuration problem, not an item problem — it
            # will recur identically for every remaining item, so stop
            # rather than printing the same line 54 more times.
            if r["status"] == "ERROR" and r.get("error", "").startswith(
                ("HTTP 401", "HTTP 403")
            ):
                print(
                    "\nAborting: the API rejected the runner's credentials. "
                    "The stub token's role must match EGP_AUTH_REQUIRED_ROLE "
                    "exactly (case-sensitive), or set GOLDEN_BEARER_TOKEN to "
                    "a real bearer token.",
                    file=sys.stderr,
                )
                break

    counts = {s: sum(1 for r in results if r["status"] == s) for s in
              ("PASS", "FAIL", "XFAIL", "ERROR")}

    if args.json:
        print(json.dumps({"summary": counts, "results": results}, indent=2))
    else:
        total_findings = sum(r.get("findings", 0) for r in results)
        total_evidenced = sum(r.get("findings_with_provenance", 0) for r in results)
        print(
            f"\n{counts['PASS']} passed, {counts['FAIL']} failed, "
            f"{counts['XFAIL']} expected-fail, {counts['ERROR']} errored."
        )
        if total_findings:
            print(
                f"Provenance: {total_evidenced}/{total_findings} findings carry "
                f"at least one database record."
            )
            if total_evidenced < total_findings:
                print(
                    "  Findings without provenance render in the UI as "
                    '"No database record was linked to this finding".'
                )

    return 1 if counts["FAIL"] or counts["ERROR"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
