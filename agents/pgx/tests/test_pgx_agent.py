"""
Integration test for the PGX subagent.

Verifies that pgx_node correctly retrieves and interprets pharmacogenomics
data for a patient and returns a complete PGXStateOutput.

Run from project root:
    python3 agents/pgx/tests/test_pgx_agent.py
    python3 -m agents.pgx.tests.test_pgx_agent
"""
from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[3]  # .../EGP-Window/EGP-Window
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import duckdb

import agents.pgx.tools.tools as pgx_tools
from agents.pgx.graph.graph import pgx_node
from agents.pgx.tools.tools import QueryExecutor
from config.settings import get_settings


def make_duckdb_executor(db_path: str) -> QueryExecutor:
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
    rows = executor("SELECT patient_id FROM patient_pgx_status LIMIT 1", [])
    if not rows:
        raise RuntimeError("No rows in patient_pgx_status — is the DB seeded?")
    return str(rows[0]["patient_id"])


def test_pgx_agent() -> None:
    settings = get_settings()
    executor = make_duckdb_executor(settings.db_path)
    pgx_tools.configure(executor)

    patient_id = get_test_patient_id(executor)
    print(f"\n--- Running PGX agent for patient_id={patient_id!r} ---\n")

    result = pgx_node({
        "patient_id": patient_id,
        "original_query": (
            "What drug-gene interactions should be considered for this patient "
            "based on their pharmacogenomics profile?"
        ),
    })

    pgx_out = result["pgx"]
    print(f"Status          : {pgx_out.status}")
    print(f"Errors          : {pgx_out.errors}")

    if pgx_out.output:
        print(f"Genes assessed  : {pgx_out.output.genes_assessed}")
        print(f"Drugs with recs : {pgx_out.output.drugs_with_recommendations}")
        print(f"Results         : {len(pgx_out.output.results)} drug-gene pair(s)")
        print(f"Summary         : {pgx_out.output.summary}")
        for r in pgx_out.output.results:
            print(
                f"  {r.gene} / {r.drug!r} "
                f"— phenotype={r.phenotype!r} "
                f"— {r.interpretation}"
            )

    assert pgx_out.status == "complete", (
        f"PGX agent status={pgx_out.status!r}. Errors: {pgx_out.errors}"
    )
    assert pgx_out.output is not None, "PGX output should not be None"
    assert len(pgx_out.output.results) > 0, "Expected at least one drug-gene result"
    assert len(pgx_out.output.genes_assessed) > 0, "Expected at least one gene assessed"

    print("\n--- All assertions passed ---")


if __name__ == "__main__":
    test_pgx_agent()
    sys.exit(0)
