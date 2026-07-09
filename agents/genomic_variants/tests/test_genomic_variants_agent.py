"""
Integration test for the genomic variants subagent.

Runs genomic_variants_node end-to-end. The test spins up a DuckDB
executor and injects it into the tools — the same pattern used when
swapping in any other DB backend.

Run either way from the project root:
    python3 agents/genomic_variants/tests/test_genomic_variants_agent.py
    python3 -m agents.genomic_variants.tests.test_genomic_variants_agent
"""
from __future__ import annotations

# ── sys.path fix ──────────────────────────────────────────────────
# Needed when run as a plain script (python3 path/to/test.py).
# When run as a module (-m), the project root is already on sys.path.
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[3]  # .../EGP-Window/EGP-Window
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
# ──────────────────────────────────────────────────────────────────

import duckdb
import json

import agents.genomic_variants.tools.tools as gv_tools
from agents.genomic_variants.graph.graph import genomic_variants_node
from agents.genomic_variants.tools.tools import QueryExecutor
from config.settings import get_settings


def make_duckdb_executor(db_path: str) -> QueryExecutor:
    """
    Build a QueryExecutor backed by DuckDB.

    Any backend (Postgres, SQLite, REST, etc.) can be wired in the
    same way — build a (sql, params) -> list[dict] callable and pass
    it to gv_tools.configure().
    """
    def execute(sql: str, params) -> list[dict]:
        con = duckdb.connect(db_path, read_only=True)
        try:
            cur = con.execute(sql, list(params))
            cols = [d[0] for d in cur.description]
            return [dict(zip(cols, row)) for row in cur.fetchall()]
        finally:
            con.close()
    return execute


def get_test_patient_id(executor: QueryExecutor) -> str:
    """Pick the first patient that has at least one variant in the DB."""
    rows = executor("SELECT patient_id FROM patient_variants LIMIT 1", [])
    if not rows:
        raise RuntimeError("No rows in patient_variants — is the DB seeded?")
    return str(rows[0]["patient_id"])


def test_genomic_variants_node() -> None:
    settings = get_settings()
    executor = make_duckdb_executor(settings.db_path)

    # Inject the executor so tools don't hardcode DuckDB
    gv_tools.configure(executor)

    patient_id = get_test_patient_id(executor)
    print(f"\n--- Running genomic_variants_node for patient_id={patient_id!r} ---\n")

    result = genomic_variants_node({
        "patient_id": patient_id,
        "original_query": "What genomic variants does this patient have?",
    })

    gv_output = result["genomic_variants"]
    print("Status          :", gv_output.status)

    if gv_output.errors:
        print("Errors          :", gv_output.errors)

    if gv_output.output:
        output = gv_output.output
        print("Patient ID      :", output.patient_id)
        print("Pathogenic count:", output.pathogenic_count)
        print("Summary         :", output.summary)
        print(f"Results         : {len(output.results)} variant(s)\n")
        for r in output.results:
            print(json.dumps(r.model_dump(), indent=2, default=str))
            print()
    else:
        print("No output produced.")

    # ── Assertions ────────────────────────────────────────────────
    assert gv_output.status == "complete", (
        f"Expected status='complete', got {gv_output.status!r}. "
        f"Errors: {gv_output.errors}"
    )
    assert gv_output.output is not None, "gv_output.output should not be None"

    output = gv_output.output
    assert output.patient_id == patient_id, (
        f"patient_id mismatch: expected {patient_id!r}, got {output.patient_id!r}"
    )
    assert len(output.results) > 0, "Expected at least one GenomicVariantResult"
    assert output.pathogenic_count >= 0, "pathogenic_count should be non-negative"

    for r in output.results:
        assert r.variant_id, f"Missing variant_id on result: {r}"

    print("--- All assertions passed ---")


if __name__ == "__main__":
    test_genomic_variants_node()
    sys.exit(0)
