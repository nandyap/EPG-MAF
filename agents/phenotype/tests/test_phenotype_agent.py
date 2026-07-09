"""
Integration test for the phenotype subagent.

Verifies that phenotype_node correctly retrieves, groups, and interprets
a patient's diagnosis history and returns a complete PhenotypeStateOutput.

Run from project root:
    python3 agents/phenotype/tests/test_phenotype_agent.py
    python3 -m agents.phenotype.tests.test_phenotype_agent
"""
from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[3]  # .../EGP-Window/EGP-Window
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import duckdb

import agents.phenotype.tools.tools as phenotype_tools
from agents.phenotype.graph.graph import phenotype_node
from agents.phenotype.tools.tools import QueryExecutor
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
    rows = executor("SELECT patient_id FROM diagnoses LIMIT 1", [])
    if not rows:
        raise RuntimeError("No rows in diagnoses — is the DB seeded?")
    return str(rows[0]["patient_id"])


def test_phenotype_agent() -> None:
    settings = get_settings()
    executor = make_duckdb_executor(settings.db_path)
    phenotype_tools.configure(executor)

    patient_id = get_test_patient_id(executor)
    print(f"\n--- Running phenotype agent for patient_id={patient_id!r} ---\n")

    result = phenotype_node({
        "patient_id": patient_id,
        "original_query": (
            "What diagnosed conditions does this patient have that may be "
            "relevant to their Alzheimer's disease risk assessment?"
        ),
    })

    ph_out = result["phenotype"]
    print(f"Status                : {ph_out.status}")
    print(f"Errors                : {ph_out.errors}")

    if ph_out.output:
        print(f"Total conditions      : {len(ph_out.output.results)}")
        print(f"Relevant conditions   : {ph_out.output.relevant_disease_names}")
        print(f"Summary               : {ph_out.output.summary}")
        for r in ph_out.output.results:
            marker = "[RELEVANT]" if r.relevant_to_query else "          "
            print(
                f"  {marker} {r.disease_name!r} "
                f"— {r.encounter_count} encounter(s) "
                f"({r.first_encounter_date} → {r.last_encounter_date})"
            )

    assert ph_out.status == "complete", (
        f"Phenotype agent status={ph_out.status!r}. Errors: {ph_out.errors}"
    )
    assert ph_out.output is not None, "Phenotype output should not be None"
    assert len(ph_out.output.results) > 0, "Expected at least one diagnosis group"
    assert isinstance(ph_out.output.relevant_disease_names, list), (
        "relevant_disease_names should be a list"
    )

    print("\n--- All assertions passed ---")


if __name__ == "__main__":
    test_phenotype_agent()
    sys.exit(0)
