"""
Integration test for the family history subagent.

Runs family_history_node end-to-end against the real DuckDB.

Run from project root:
    python3 agents/family_history/tests/test_family_history_agent.py
    python3 -m agents.family_history.tests.test_family_history_agent
"""
from __future__ import annotations

# ── sys.path fix ──────────────────────────────────────────────────
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[3]  # .../EGP-Window/EGP-Window
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
# ──────────────────────────────────────────────────────────────────

import duckdb
import json

import agents.family_history.tools.tools as fh_tools
from agents.family_history.graph.graph import family_history_node
from agents.family_history.tools.tools import QueryExecutor
from config.settings import get_settings


def make_duckdb_executor(db_path: str) -> QueryExecutor:
    """DuckDB-backed QueryExecutor injected into the tool module."""
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
    """Pick the first patient that has family history records in the DB."""
    rows = executor("SELECT patient_id FROM patient_kinship_history LIMIT 1", [])
    if not rows:
        raise RuntimeError(
            "No rows in patient_kinship_history — is the DB seeded?"
        )
    return str(rows[0]["patient_id"])


def test_family_history_node() -> None:
    settings = get_settings()
    executor = make_duckdb_executor(settings.db_path)
    fh_tools.configure(executor)

    patient_id = get_test_patient_id(executor)
    print(f"\n--- Running family_history_node for patient_id={patient_id!r} ---\n")

    result = family_history_node({
        "patient_id": patient_id,
        "original_query": (
            "What is this patient's family history of hereditary cancer and "
            "Alzheimer's disease, and do they meet any clinical threshold criteria?"
        ),
    })

    fh_output = result["family_history"]
    print("Status                   :", fh_output.status)

    if fh_output.errors:
        print("Errors                   :", fh_output.errors)

    if fh_output.output:
        print("Summary                  :", fh_output.output.summary)
        print("Diseases meeting threshold:", fh_output.output.diseases_meeting_threshold)
        print(f"Results                  : {len(fh_output.output.results)} record(s)\n")
        for r in fh_output.output.results:
            print(json.dumps(r.model_dump(), indent=2, default=str))
            print()
    else:
        print("No output produced.")

    # ── Assertions ────────────────────────────────────────────────
    assert fh_output.status == "complete", (
        f"Expected status='complete', got {fh_output.status!r}. "
        f"Errors: {fh_output.errors}"
    )
    assert fh_output.output is not None, "fh_output.output should not be None"
    assert len(fh_output.output.results) > 0, "Expected at least one result"
    assert isinstance(fh_output.output.diseases_meeting_threshold, list), (
        "diseases_meeting_threshold should be a list"
    )

    for r in fh_output.output.results:
        assert r.disease_name, f"Missing disease_name on result: {r}"
        assert r.criteria_name, f"Missing criteria_name on result: {r}"
        assert isinstance(r.meets_threshold, bool), (
            f"meets_threshold should be bool, got {type(r.meets_threshold)} on: {r}"
        )

    print("--- All assertions passed ---")


if __name__ == "__main__":
    test_family_history_node()
    sys.exit(0)
