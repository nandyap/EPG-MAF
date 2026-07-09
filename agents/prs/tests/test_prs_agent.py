"""
Integration test for the PRS subagent.

Runs prs_node end-to-end. The test is responsible for spinning up a
QueryExecutor and injecting it into the tools — the same pattern used
when swapping in any other DB backend.

Run either way from the project root:
    python3 agents/prs/tests/test_prs_agent.py
    python3 -m agents.prs.tests.test_prs_agent
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

import agents.prs.tools.tools as prs_tools
from agents.prs.graph.graph import prs_node
from agents.prs.tools.tools import QueryExecutor
from config.settings import get_settings


def make_duckdb_executor(db_path: str) -> QueryExecutor:
    """
    Build a QueryExecutor backed by DuckDB.

    Defined here rather than inside tools.py to show the pattern:
    any backend (Postgres, SQLite, REST, etc.) can be wired in the
    same way — build a (sql, params) -> list[dict] callable and pass
    it to prs_tools.configure().
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
    """Pick the first patient that has at least one PRS score in the DB."""
    rows = executor("SELECT patient_id FROM patient_prs LIMIT 1", [])
    if not rows:
        raise RuntimeError("No rows in patient_prs — is the DB seeded?")
    return str(rows[0]["patient_id"])


def test_prs_node() -> None:
    settings = get_settings()
    executor = make_duckdb_executor(settings.db_path)

    # Inject the executor so tools don't hardcode DuckDB
    prs_tools.configure(executor)

    patient_id = get_test_patient_id(executor)
    print(f"\n--- Running prs_node for patient_id={patient_id!r} ---\n")

    result = prs_node({
        "patient_id": patient_id,
        "original_query": "What are this patient's polygenic risk scores?",
    })

    prs_output = result["prs"]
    print("Status :", prs_output.status)

    if prs_output.errors:
        print("Errors :", prs_output.errors)

    if prs_output.output:
        print("Summary:", prs_output.output.summary)
        print(f"Results: {len(prs_output.output.results)} score(s)\n")
        for r in prs_output.output.results:
            print(json.dumps(r.model_dump(), indent=2, default=str))
            print()
    else:
        print("No output produced.")

    # ── Assertions ────────────────────────────────────────────────
    assert prs_output.status == "complete", (
        f"Expected status='complete', got {prs_output.status!r}. "
        f"Errors: {prs_output.errors}"
    )
    assert prs_output.output is not None, "prs_output.output should not be None"
    assert len(prs_output.output.results) > 0, "Expected at least one PRSResult"

    for r in prs_output.output.results:
        assert r.prs_name, f"Missing prs_name on result: {r}"
        assert r.disease_name, f"Missing disease_name on result: {r}"
        assert r.prs_score is not None, f"Missing prs_score on result: {r}"

    print("--- All assertions passed ---")


if __name__ == "__main__":
    test_prs_node()
    sys.exit(0)
