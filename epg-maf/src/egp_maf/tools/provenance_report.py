"""Render DBProvenance from Cosmos as a readable audit report.

Cosmos is private-endpoint only, so this runs **inside the backend
container**, which already holds Data Contributor via the UAMI. It ships
in the image (``scripts/`` is excluded by ``.dockerignore``, this package
is not), so no file needs pasting in::

    az containerapp exec -n egpmaf-dev-backend \
        -g rg-ailz-egpwin-dev-m42-aen-001 --command /bin/sh

    python -m egp_maf.tools.provenance_report --list    # threads, newest first
    python -m egp_maf.tools.provenance_report           # newest thread
    python -m egp_maf.tools.provenance_report T-abc123  # one specific thread
    python -m egp_maf.tools.provenance_report --all     # every thread

Read-only. For every clinical fact the assistant reported, it prints the
evidence chain: which tool ran, with which parameters, against which
table, the exact database row returned, and when.

Threads are sorted newest-first. Cosmos does not return items in any
particular order, so picking "the top one" from a raw query is a good way
to read a stale document and conclude something is broken.
"""

from __future__ import annotations

import os
import sys
from datetime import datetime
from typing import Any

from azure.cosmos import CosmosClient
from azure.identity import DefaultAzureCredential

W = 78

DOMAINS: dict[str, str] = {
    "genomic_variants": "GENOMIC VARIANTS",
    "prs": "POLYGENIC RISK SCORES",
    "pgx": "PHARMACOGENOMICS",
    "family_history": "FAMILY HISTORY",
    "phenotype": "PHENOTYPE / DIAGNOSES",
}

# Row values are truncated for display only — the stored record is
# complete. Annotation notes in particular run to a full paragraph.
ROW_INDENT = 10


# ── formatting helpers ──────────────────────────────────────────────


def _ts(raw: Any) -> str:
    """ISO-8601 → '2026-08-21 12:47:08 UTC'."""
    if not raw:
        return "—"
    try:
        dt = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except ValueError:
        return str(raw)
    return dt.strftime("%Y-%m-%d %H:%M:%S UTC")


def _short(value: Any, limit: int) -> str:
    if value is None:
        text = "null"
    else:
        text = str(value)
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _params(params: dict[str, Any]) -> str:
    if not params:
        return "—"
    return ", ".join(f"{k}={v}" for k, v in params.items())


def _label(domain: str, result: dict[str, Any]) -> tuple[str, str]:
    """Return (headline, detail) for one result row."""
    core = result.get("core_annotations") or {}

    if domain == "genomic_variants":
        gene = core.get("gene") or "—"
        head = f"{gene}  {result.get('variant_id', '')}".strip()
        bits = [
            core.get("pathogenicity"),
            core.get("variant_type"),
            core.get("disease_name"),
        ]
    elif domain == "prs":
        head = f"{result.get('prs_name', '')}  {result.get('disease_name', '')}".strip()
        pct = result.get("percentile")
        bits = [
            f"score {result.get('prs_score')}" if result.get("prs_score") is not None else None,
            f"{pct}th percentile" if pct is not None else None,
            result.get("risk_band"),
        ]
    elif domain == "pgx":
        head = f"{result.get('gene', '')}  {result.get('phenotype') or ''}".strip()
        bits = [result.get("drug"), result.get("recommendation")]
    elif domain == "family_history":
        head = f"{result.get('disease_name', '')}".strip()
        met = result.get("meets_threshold")
        bits = [
            result.get("criteria_name"),
            "threshold met" if met else "threshold not met" if met is not None else None,
        ]
    else:  # phenotype
        head = f"{result.get('disease_name') or result.get('term') or ''}".strip()
        bits = [result.get("code"), result.get("code_type")]

    detail = " · ".join(str(b) for b in bits if b)
    return head or "(unnamed)", detail


# ── report ──────────────────────────────────────────────────────────


def _print_evidence(prov: dict[str, Any]) -> None:
    print("      EVIDENCE")
    print(f"        Retrieved    {_ts(prov.get('retrieved_at'))}")
    print(f"        Tool         {prov.get('tool_name', '—')}")
    print(f"        Parameters   {_params(prov.get('tool_parameters') or {})}")
    print(f"        Source       {prov.get('source_table', '—')}")

    derived = prov.get("fields_derived") or []
    if derived:
        print(f"        Populated    {', '.join(derived)}")

    trace = prov.get("trace_id")
    if trace:
        print(f"        Trace        {trace}")

    row = prov.get("source_row") or {}
    if row:
        print()
        print("        Database row as retrieved:")
        pad = max(len(k) for k in row) + 2
        limit = max(20, W - ROW_INDENT - pad)
        for key, value in row.items():
            print(f"{' ' * ROW_INDENT}{key.ljust(pad)}{_short(value, limit)}")
    print()


def _print_domain(domain: str, slot: dict[str, Any]) -> tuple[int, int]:
    """Print one domain. Returns (facts, facts_without_evidence)."""
    inner = (slot or {}).get("output") or {}
    payload = inner.get("output") or {}
    results = payload.get("results") or []
    status = (slot or {}).get("status", "?")

    print()
    print(f"{DOMAINS.get(domain, domain.upper())}".ljust(W - 12) + status.upper())
    print("─" * W)

    if not results:
        errors = (slot or {}).get("errors") or []
        print("  No results." + (f"  ({errors[0]})" if errors else ""))
        return 0, 0

    facts = 0
    unevidenced = 0
    for result in results:
        head, detail = _label(domain, result)
        facts += 1
        print()
        print(f"  ▸ {head}")
        if detail:
            print(f"    {detail}")

        interpretation = result.get("interpretation")
        if interpretation:
            print()
            print(f"    Interpretation ({result.get('interpretation_model') or 'llm'}):")
            for line in _wrap(interpretation, W - 8):
                print(f"      {line}")

        prov_list = result.get("provenance") or []
        print()
        if not prov_list:
            unevidenced += 1
            print("      EVIDENCE   ⚠ none recorded for this result")
            print()
            continue
        for prov in prov_list:
            _print_evidence(prov)

    return facts, unevidenced


def _wrap(text: str, width: int) -> list[str]:
    words = str(text).split()
    lines: list[str] = []
    current = ""
    for word in words:
        if len(current) + len(word) + 1 > width:
            lines.append(current)
            current = word
        else:
            current = f"{current} {word}".strip()
    if current:
        lines.append(current)
    return lines


def report(doc: dict[str, Any]) -> None:
    print()
    print("═" * W)
    print("  CLINICAL DATA PROVENANCE REPORT")
    print("═" * W)
    print(f"  Thread      {doc.get('thread_id')}")
    print(f"  Patient     {doc.get('patient_id')}")
    print(f"  Clinician   {doc.get('clinician_id')}")
    print(f"  Last active {_ts(doc.get('last_activity'))}")
    completed = doc.get("agents_completed") or []
    print(f"  Specialists {', '.join(completed) if completed else '—'}")
    print("═" * W)

    total = 0
    missing = 0
    results_map = doc.get("results") or {}
    for domain in DOMAINS:
        if domain in results_map and results_map[domain]:
            facts, unevidenced = _print_domain(domain, results_map[domain])
            total += facts
            missing += unevidenced

    print()
    print("═" * W)
    if total == 0:
        print("  No clinical results stored on this thread.")
    elif missing == 0:
        print(f"  ✓ {total} clinical fact(s), every one traceable to a database row.")
    else:
        print(f"  ⚠ {total} clinical fact(s); {missing} without recorded evidence.")
    print("═" * W)
    print()


# ── entry point ─────────────────────────────────────────────────────


def main() -> None:
    client = CosmosClient(
        os.environ["COSMOS_ENDPOINT"], credential=DefaultAzureCredential()
    )
    container = (
        client.get_database_client(os.environ.get("COSMOS_DATABASE", "egp"))
        .get_container_client(os.environ.get("COSMOS_CONTAINER", "sessions"))
    )

    docs = list(
        container.query_items(
            query="SELECT * FROM c", enable_cross_partition_query=True
        )
    )
    docs.sort(key=lambda d: d.get("last_activity") or "", reverse=True)

    if not docs:
        print("No threads found.")
        return

    arg = sys.argv[1] if len(sys.argv) > 1 else None

    if arg == "--list":
        print()
        print(f"{'THREAD':<26} {'PATIENT':<10} {'LAST ACTIVE':<24} SPECIALISTS")
        print("─" * W)
        for d in docs:
            print(
                f"{d.get('thread_id', ''):<26} "
                f"{d.get('patient_id', ''):<10} "
                f"{_ts(d.get('last_activity')):<24} "
                f"{','.join(d.get('agents_completed') or []) or '—'}"
            )
        print()
        return

    if arg == "--all":
        for d in docs:
            report(d)
        return

    if arg:
        matches = [d for d in docs if d.get("thread_id") == arg]
        if not matches:
            print(f"Thread {arg} not found. Use --list to see available threads.")
            return
        report(matches[0])
        return

    report(docs[0])  # newest


if __name__ == "__main__":
    main()
